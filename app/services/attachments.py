"""팔로업 메일 첨부 파일 저장/검증.

파일은 웹으로 직접 열리지 않는 instance/attachments/<followup_id>/ 아래에 uuid 이름으로
저장한다 (원본 파일명은 DB에만 기록 - 한글 파일명이 안전하게 유지되고 경로 조작도 막힌다).
"""

import mimetypes
import os
import shutil
import uuid

from flask import current_app

from app.extensions import db
from app.models import FollowupAttachment

MAX_FILE_BYTES = 10 * 1024 * 1024  # 파일 1개
# Gmail은 인코딩(base64, 약 1.37배) 후 메일 전체가 25MB를 넘으면 거부한다.
MAX_TOTAL_BYTES = 15 * 1024 * 1024

# Gmail이 보안상 차단하는 형식 (첨부하면 발송 자체가 실패한다)
BLOCKED_EXTS = {
    "ade", "adp", "apk", "appx", "bat", "cab", "chm", "cmd", "com", "cpl", "dll", "dmg",
    "exe", "hta", "ins", "isp", "iso", "jar", "js", "jse", "lib", "lnk", "mde", "msc",
    "msi", "msp", "mst", "pif", "ps1", "scr", "sct", "shb", "sys", "vb", "vbe", "vbs",
    "vxd", "wsc", "wsf", "wsh",
}


def _folder(followup_id):
    return os.path.join(current_app.instance_path, "attachments", str(followup_id))


def path_for(attachment):
    return os.path.join(_folder(attachment.followup_id), attachment.stored_name)


def existing_total(followup):
    return sum(a.size for a in followup.attachments) if followup else 0


def read_uploads(files, already_attached_bytes=0):
    """업로드된 FileStorage 목록을 검증하고 [(파일명, content_type, 바이트)]로 돌려준다.
    문제가 있으면 사용자에게 그대로 보여줄 한글 메시지의 ValueError를 낸다."""
    items = []
    total = already_attached_bytes
    for f in files:
        if not f or not f.filename:
            continue
        name = os.path.basename(f.filename.replace("\\", "/"))
        name = "".join(ch for ch in name if ch.isprintable()).strip()
        if not name:
            continue

        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in BLOCKED_EXTS:
            raise ValueError(f"'{name}'은(는) Gmail이 보안상 차단하는 파일 형식(.{ext})이라 첨부할 수 없습니다.")

        data = f.read()
        if not data:
            raise ValueError(f"'{name}' 파일이 비어 있습니다.")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"'{name}' 파일이 너무 큽니다. 파일당 {MAX_FILE_BYTES // (1024 * 1024)}MB 이하만 첨부할 수 있습니다.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"첨부 파일 합계가 {MAX_TOTAL_BYTES // (1024 * 1024)}MB를 넘습니다. 일부를 빼주세요.")

        content_type = f.mimetype or mimetypes.guess_type(name)[0] or "application/octet-stream"
        items.append((name, content_type, data))
    return items


def save_uploads(followup, items):
    """read_uploads()로 검증된 파일들을 디스크에 쓰고 DB에 기록한다."""
    if not items:
        return []
    folder = _folder(followup.id)
    os.makedirs(folder, exist_ok=True)

    saved = []
    for name, content_type, data in items:
        ext = "".join(ch for ch in os.path.splitext(name)[1].lower() if ch.isalnum() or ch == ".")[:12]
        stored_name = uuid.uuid4().hex + ext
        with open(os.path.join(folder, stored_name), "wb") as fh:
            fh.write(data)
        attachment = FollowupAttachment(
            followup_id=followup.id,
            filename=name[:255],
            stored_name=stored_name,
            content_type=content_type,
            size=len(data),
        )
        db.session.add(attachment)
        saved.append(attachment)
    db.session.commit()
    return saved


def load_for_send(followup):
    """발송용: [(파일명, content_type, 바이트)]. 디스크에서 사라진 파일이 있으면 FileNotFoundError."""
    result = []
    for a in followup.attachments if followup else []:
        try:
            with open(path_for(a), "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"첨부 파일 '{a.filename}'을(를) 찾을 수 없습니다. 다시 첨부해주세요.")
        result.append((a.filename, a.content_type or "application/octet-stream", data))
    return result


def delete_attachment(attachment):
    try:
        os.remove(path_for(attachment))
    except OSError:
        # 없거나 다른 곳에서 열려 있어 지우지 못해도 목록에서는 빼준다 (고아 파일만 남는다)
        pass
    db.session.delete(attachment)
    db.session.commit()


def purge_files(followup):
    """DB 행은 그대로 두고 이 메일의 첨부 파일 폴더만 지운다 (연락처 삭제 직전 등)."""
    if followup is not None and followup.id is not None:
        shutil.rmtree(_folder(followup.id), ignore_errors=True)


def clear_attachments(followup):
    """새 메일 초안을 시작할 때 이전에 보낸 메일의 첨부를 모두 비운다."""
    if followup is None:
        return
    purge_files(followup)
    for a in list(followup.attachments):
        db.session.delete(a)
    db.session.commit()

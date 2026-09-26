"""바이어 메일 관리 (buyer_mail 프로토타입 통합).

박람회에서 만난 바이어 연락처를 등록해두고, 공용 팔로업 메일 템플릿을 만들어
체크한 바이어들에게 본인 Gmail로 일괄/개별 발송한다. 발송에는 Gmail 발송 권한
연동(/buyers/gmail/connect)이 별도로 필요하다 (로그인 자체는 기존 이메일/비밀번호
로그인을 그대로 쓴다).
"""

from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Contact, ConceptDraft, EmailTemplate, Exhibition, FollowupEmail
from app.services import attachments as mail_attachments
from app.services.card_scan import scan_business_card
from app.services.google_oauth import build_flow, encrypt_token, fetch_userinfo
from app.services.mail_llm import revise_email_template, revise_individual_email
from app.services.mailer import send_via_gmail
from app.services.mailmerge import render_email

STALE_DAYS = 21
TEMPLATE_VERSIONS = (1, 2, 3)

contacts_bp = Blueprint("contacts", __name__, url_prefix="/buyers")
followup_bp = Blueprint("followup", __name__, url_prefix="/buyers")
mail_template_bp = Blueprint("mail_template", __name__, url_prefix="/buyers")
buyer_profile_bp = Blueprint("buyer_profile", __name__, url_prefix="/buyers")
buyer_gmail_bp = Blueprint("buyer_gmail", __name__, url_prefix="/buyers/gmail")


# ---------------------------------------------------------------- contacts --

def _is_stale(contact: Contact) -> bool:
    followup = contact.followup
    if not followup or followup.status != "sent" or not followup.sent_at or followup.dismissed:
        return False
    return datetime.utcnow() - followup.sent_at >= timedelta(days=STALE_DAYS)


def _drafted_exhibitions():
    """바이어 등록/검색 드롭다운에 띄울 박람회 목록. raw_exhibitions와 concept_drafts는
    서로 다른 DB(bind)라 JOIN이 안 돼서, exhibition_id를 먼저 뽑고 그걸로 다시 조회한다.
    '작성 중인 박람회' 목록(app/routes/drafts.py)과 동일하게 상태 구분 없이 그 사용자의
    ConceptDraft가 있는 박람회는 전부 포함한다."""
    exhibition_ids = [
        row[0]
        for row in db.session.query(ConceptDraft.exhibition_id)
        .filter(ConceptDraft.user_id == current_user.id)
        .distinct()
        .all()
    ]
    if not exhibition_ids:
        return []
    return (
        Exhibition.query.filter(Exhibition.id.in_(exhibition_ids), Exhibition.is_active == 1)
        .order_by(Exhibition.name)
        .all()
    )


@contacts_bp.route("/contacts")
@login_required
def list_contacts():
    query = Contact.query.filter_by(user_id=current_user.id)
    exhibition_id = request.args.get("exhibition_id", type=int)
    if exhibition_id:
        query = query.filter_by(exhibition_id=exhibition_id)
    sort = request.args.get("sort", "desc")
    if sort not in ("asc", "desc"):
        sort = "desc"
    order = Contact.created_at.asc() if sort == "asc" else Contact.created_at.desc()
    contacts = query.order_by(order).all()

    stale = [c for c in contacts if _is_stale(c)]
    others = [c for c in contacts if not _is_stale(c)]
    contacts = stale + others
    stale_ids = {c.id for c in stale}
    stale_days = {c.id: (datetime.utcnow() - c.followup.sent_at).days for c in stale}

    exhibitions = _drafted_exhibitions()
    active_template = EmailTemplate.query.filter_by(user_id=current_user.id, is_active=True).first()
    has_usable_template = bool(active_template and active_template.subject and active_template.body)
    template_labels = {
        t.version: t.label for t in EmailTemplate.query.filter_by(user_id=current_user.id).all()
    }
    return render_template(
        "buyers/buyer_manage.html",
        contacts=contacts,
        exhibitions=exhibitions,
        selected_exhibition_id=exhibition_id,
        sort=sort,
        stale_ids=stale_ids,
        stale_days=stale_days,
        active_version=active_template.version if has_usable_template else None,
        template_labels=template_labels,
    )


@contacts_bp.route("/contacts/new", methods=["GET", "POST"])
@login_required
def new_contact():
    exhibitions = _drafted_exhibitions()
    template_versions = (
        EmailTemplate.query.filter_by(user_id=current_user.id).order_by(EmailTemplate.version).all()
    )
    if request.method == "POST":
        exhibition = Exhibition.query.get(int(request.form["exhibition_id"]))
        contact = Contact(
            user_id=current_user.id,
            exhibition_id=exhibition.id,
            exhibition_name=exhibition.name,
            name=request.form["name"].strip(),
            company=request.form.get("company", "").strip(),
            position=request.form.get("position", "").strip(),
            email=request.form["email"].strip(),
            phone=request.form.get("phone", "").strip(),
            address=request.form.get("address", "").strip(),
            remarks=request.form.get("remarks", "").strip(),
            preferred_template_version=request.form.get("preferred_template_version", type=int),
        )
        db.session.add(contact)
        db.session.commit()
        flash("바이어가 등록되었습니다.", "success")
        return redirect(url_for("contacts.list_contacts"))
    prefill = session.pop("card_prefill", None)
    return render_template(
        "buyers/contact_form.html",
        contact=None,
        exhibitions=exhibitions,
        prefill=prefill,
        template_versions=template_versions,
    )


@contacts_bp.route("/contacts/scan_card", methods=["POST"])
@login_required
def scan_card():
    image = request.files.get("card_image")
    if not image or not image.filename:
        flash("명함 이미지를 선택해주세요.", "danger")
        return redirect(url_for("contacts.new_contact"))
    if not (image.mimetype or "").startswith("image/"):
        flash("이미지 파일만 업로드할 수 있습니다.", "danger")
        return redirect(url_for("contacts.new_contact"))

    try:
        session["card_prefill"] = scan_business_card(image.read(), image.mimetype)
    except Exception as exc:
        flash(f"명함 인식에 실패했습니다: {exc}", "danger")

    return redirect(url_for("contacts.new_contact"))


@contacts_bp.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contact(contact_id):
    contact = Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()
    exhibitions = _drafted_exhibitions()
    # 이 바이어가 등록된 박람회의 '작성 중인 박람회' 항목이 그 사이 지워졌다면
    # 드롭다운에서 통째로 사라져서 저장할 때 실수로 다른 박람회로 바뀔 수 있으니,
    # 그 경우엔 원래 박람회를 목록에 그대로 끼워넣는다.
    if contact.exhibition_id not in {e.id for e in exhibitions}:
        original = Exhibition.query.get(contact.exhibition_id)
        if original:
            exhibitions = sorted([*exhibitions, original], key=lambda e: e.name or "")
    template_versions = (
        EmailTemplate.query.filter_by(user_id=current_user.id).order_by(EmailTemplate.version).all()
    )
    if request.method == "POST":
        exhibition = Exhibition.query.get(int(request.form["exhibition_id"]))
        contact.exhibition_id = exhibition.id
        contact.exhibition_name = exhibition.name
        contact.name = request.form["name"].strip()
        contact.company = request.form.get("company", "").strip()
        contact.position = request.form.get("position", "").strip()
        contact.email = request.form["email"].strip()
        contact.phone = request.form.get("phone", "").strip()
        contact.address = request.form.get("address", "").strip()
        contact.remarks = request.form.get("remarks", "").strip()
        contact.preferred_template_version = request.form.get("preferred_template_version", type=int)
        db.session.commit()
        flash("수정되었습니다.", "success")
        return redirect(url_for("contacts.list_contacts"))
    return render_template(
        "buyers/contact_form.html",
        contact=contact,
        exhibitions=exhibitions,
        template_versions=template_versions,
    )


@contacts_bp.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(contact_id):
    contact = Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()
    mail_attachments.purge_files(contact.followup)
    db.session.delete(contact)
    db.session.commit()
    flash("삭제되었습니다.", "info")
    return redirect(url_for("contacts.list_contacts"))


# ---------------------------------------------------------------- followup --

def _get_owned_contact(contact_id):
    return Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()


def _get_active_template():
    return EmailTemplate.query.filter_by(user_id=current_user.id, is_active=True).first()


def _resolve_template(contact):
    """이 바이어에게 지정된 선호 버전이 있으면 그걸, 없으면 발송용(활성) 버전을 쓴다."""
    if contact.preferred_template_version:
        template = EmailTemplate.query.filter_by(
            version=contact.preferred_template_version, user_id=current_user.id
        ).first()
        if template and template.subject and template.body:
            return template
    return _get_active_template()


def _fill_contact_from_template(contact, template):
    subject, body = render_email(template.subject, template.body, contact, current_user)
    followup = contact.followup or FollowupEmail(contact_id=contact.id)
    followup.subject = subject
    followup.body = body
    followup.status = "draft"
    followup.template_version = template.version
    followup.generated_at = datetime.utcnow()
    followup.sent_at = None

    db.session.add(followup)
    db.session.commit()
    return followup


@followup_bp.route("/contacts/<int:contact_id>/followup")
@login_required
def view_followup(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None:
        template = _resolve_template(contact)
        if template is None or not template.subject or not template.body:
            flash("먼저 메일 템플릿을 작성해주세요.", "warning")
            return redirect(url_for("mail_template.home"))
        followup = _fill_contact_from_template(contact, template)

    templates_by_version = {
        t.version: t
        for t in EmailTemplate.query.filter(
            EmailTemplate.version.in_(TEMPLATE_VERSIONS), EmailTemplate.user_id == current_user.id
        ).all()
    }
    return render_template(
        "buyers/followup_edit.html",
        contact=contact,
        followup=followup,
        template_versions=TEMPLATE_VERSIONS,
        templates_by_version=templates_by_version,
    )


@followup_bp.route("/contacts/<int:contact_id>/followup/fill", methods=["POST"])
@login_required
def fill_from_template(contact_id):
    contact = _get_owned_contact(contact_id)
    if contact.followup and contact.followup.status == "sent":
        flash("이미 발송된 메일은 다시 채울 수 없습니다. 재발송을 이용해주세요.", "warning")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    version = request.form.get("version", type=int)

    if version:
        template = EmailTemplate.query.filter_by(version=version, user_id=current_user.id).first()
        if template is None or not template.subject or not template.body:
            flash(f"버전 {version} 템플릿에 아직 내용이 없습니다.", "warning")
            return redirect(url_for("followup.view_followup", contact_id=contact.id))
    else:
        template = _resolve_template(contact)
        if template is None or not template.subject or not template.body:
            flash("먼저 메일 템플릿을 작성해주세요.", "warning")
            return redirect(url_for("mail_template.home"))

    _fill_contact_from_template(contact, template)
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@followup_bp.route("/contacts/<int:contact_id>/followup/revise", methods=["POST"])
@login_required
def revise(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None or not followup.subject or not followup.body:
        flash("먼저 내용을 채워주세요.", "warning")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))
    if followup.status == "sent":
        flash("이미 발송된 메일은 수정할 수 없습니다. 재발송을 이용해주세요.", "warning")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    instruction = request.form.get("instruction", "").strip()
    try:
        subject, body = revise_individual_email(
            instruction,
            followup.subject,
            followup.body,
            sender_company=current_user.company or "",
            product_description=current_user.product_description or "",
        )
    except Exception as exc:
        flash(f"AI 수정에 실패했습니다: {exc}", "danger")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    followup.subject = subject
    followup.body = body
    if followup.status != "sent":
        followup.status = "edited"
    db.session.commit()
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@followup_bp.route("/contacts/<int:contact_id>/followup/save", methods=["POST"])
@login_required
def save(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None:
        flash("먼저 템플릿으로 채워주세요.", "warning")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))
    if followup.status == "sent":
        flash("이미 발송된 메일은 수정할 수 없습니다. 재발송을 이용해주세요.", "warning")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    followup.subject = request.form["subject"]
    followup.body = request.form["body"]
    followup.status = "edited"
    db.session.commit()

    try:
        items = mail_attachments.read_uploads(
            request.files.getlist("attachments"), mail_attachments.existing_total(followup)
        )
    except ValueError as exc:
        flash(f"내용은 저장됐지만 파일은 첨부되지 않았습니다. {exc}", "danger")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    mail_attachments.save_uploads(followup, items)
    flash(
        f"내용이 저장되고 파일 {len(items)}개가 첨부되었습니다." if items else "내용이 저장되었습니다.",
        "success",
    )
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


def _get_owned_attachment(contact_id, attachment_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    attachment = next((a for a in (followup.attachments if followup else []) if a.id == attachment_id), None)
    if attachment is None:
        abort(404)
    return contact, followup, attachment


@followup_bp.route("/contacts/<int:contact_id>/followup/attachments/<int:attachment_id>")
@login_required
def download_attachment(contact_id, attachment_id):
    _, _, attachment = _get_owned_attachment(contact_id, attachment_id)
    return send_file(
        mail_attachments.path_for(attachment),
        as_attachment=True,
        download_name=attachment.filename,
        mimetype=attachment.content_type or "application/octet-stream",
    )


@followup_bp.route("/contacts/<int:contact_id>/followup/attachments/<int:attachment_id>/delete", methods=["POST"])
@login_required
def delete_attachment(contact_id, attachment_id):
    contact, followup, attachment = _get_owned_attachment(contact_id, attachment_id)
    if followup.status == "sent":
        flash("이미 발송된 메일의 첨부는 지울 수 없습니다.", "warning")
    else:
        mail_attachments.delete_attachment(attachment)
        flash("첨부 파일을 삭제했습니다.", "info")
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@followup_bp.route("/contacts/<int:contact_id>/followup/send", methods=["POST"])
@login_required
def send(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None or not followup.subject or not followup.body:
        flash("발송할 내용이 없습니다.", "warning")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    if not current_user.google_refresh_token:
        flash("먼저 Gmail 발송 권한을 연동해주세요.", "warning")
        return redirect(url_for("buyer_gmail.connect"))

    try:
        send_via_gmail(
            current_user, contact.email, followup.subject, followup.body,
            attachments=mail_attachments.load_for_send(followup),
        )
    except Exception as exc:
        followup.status = "failed"
        db.session.commit()
        flash(f"발송에 실패했습니다: {exc}", "danger")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    followup.status = "sent"
    followup.sent_at = datetime.utcnow()
    followup.last_sent_at = followup.sent_at
    followup.dismissed = False
    db.session.commit()
    flash(f"{contact.email} 로 메일을 발송했습니다.", "success")
    return redirect(url_for("contacts.list_contacts"))


@followup_bp.route("/contacts/<int:contact_id>/followup/compose_new", methods=["POST"])
@login_required
def compose_new(contact_id):
    """이미 보낸 바이어에게 새 메일 초안을 템플릿에서 다시 만들고, 수정 화면으로 이동한다
    (여기서 바로 발송하지 않고 검토·수정 후 직접 발송하도록 한다)."""
    contact = _get_owned_contact(contact_id)
    template = _resolve_template(contact)
    if template is None or not template.subject or not template.body:
        flash("먼저 메일 템플릿을 작성해주세요.", "warning")
        return redirect(url_for("mail_template.home"))

    mail_attachments.clear_attachments(contact.followup)
    _fill_contact_from_template(contact, template)
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@followup_bp.route("/contacts/<int:contact_id>/followup/dismiss_stale", methods=["POST"])
@login_required
def dismiss_stale(contact_id):
    contact = _get_owned_contact(contact_id)
    if contact.followup:
        contact.followup.dismissed = True
        db.session.commit()
    return redirect(url_for("contacts.list_contacts"))


@followup_bp.route("/contacts/send_selected", methods=["POST"])
@login_required
def send_selected():
    ids = request.form.getlist("contact_ids", type=int)
    if not ids:
        flash("선택된 바이어가 없습니다.", "warning")
        return redirect(url_for("contacts.list_contacts"))

    if not current_user.google_refresh_token:
        flash("먼저 Gmail 발송 권한을 연동해주세요.", "warning")
        return redirect(url_for("buyer_gmail.connect"))

    try:
        bulk_attachments = mail_attachments.read_uploads(request.files.getlist("attachments"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("contacts.list_contacts"))

    contacts = Contact.query.filter(
        Contact.id.in_(ids), Contact.user_id == current_user.id
    ).all()

    sent, failed, skipped = 0, 0, 0
    for contact in contacts:
        template = _resolve_template(contact)
        if template is None or not template.subject or not template.body:
            skipped += 1
            continue

        subject, body = render_email(template.subject, template.body, contact, current_user)
        followup = contact.followup or FollowupEmail(contact_id=contact.id)
        followup.subject = subject
        followup.body = body
        followup.template_version = template.version
        followup.generated_at = datetime.utcnow()

        try:
            send_via_gmail(current_user, contact.email, subject, body, attachments=bulk_attachments)
            followup.status = "sent"
            followup.sent_at = datetime.utcnow()
            followup.last_sent_at = followup.sent_at
            followup.dismissed = False
            sent += 1
        except Exception:
            followup.status = "failed"
            failed += 1

        db.session.add(followup)
        db.session.commit()

    message = f"선택 발송 완료: 성공 {sent}건, 실패 {failed}건 (선택 {len(contacts)}건 중)"
    if bulk_attachments:
        message += f" — 첨부 파일 {len(bulk_attachments)}개 포함"
    if skipped:
        message += f" — 템플릿 없음으로 {skipped}건 건너뜀"
    flash(message, "info")
    return redirect(url_for("contacts.list_contacts"))


# ------------------------------------------------------------ mail_template --

def _get_version(version: int) -> EmailTemplate:
    template = EmailTemplate.query.filter_by(version=version, user_id=current_user.id).first()
    if template is None:
        # 이 사용자에게 아직 아무 버전도 없으면 처음 만드는 버전을 기본 활성으로 지정
        is_first_ever = EmailTemplate.query.filter_by(user_id=current_user.id).count() == 0
        template = EmailTemplate(version=version, user_id=current_user.id, is_active=is_first_ever)
        db.session.add(template)
        db.session.commit()
    return template


@mail_template_bp.route("/template")
@login_required
def home():
    active = EmailTemplate.query.filter_by(user_id=current_user.id, is_active=True).first()
    version = active.version if active else 1
    return redirect(url_for("mail_template.edit_template", version=version))


@mail_template_bp.route("/template/<int:version>")
@login_required
def edit_template(version):
    if version not in TEMPLATE_VERSIONS:
        version = 1
    template = _get_version(version)
    all_versions = [_get_version(v) for v in TEMPLATE_VERSIONS]
    return render_template(
        "buyers/template_edit.html", template=template, all_versions=all_versions, version=version
    )


@mail_template_bp.route("/template/<int:version>/save", methods=["POST"])
@login_required
def save(version):
    template = _get_version(version)
    template.subject = request.form["subject"]
    template.body = request.form["body"]
    template.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"버전 {version} 템플릿이 저장되었습니다.", "success")
    return redirect(url_for("mail_template.edit_template", version=version))


@mail_template_bp.route("/template/<int:version>/revise", methods=["POST"])
@login_required
def revise_template(version):
    template = _get_version(version)
    instruction = request.form.get("instruction", "").strip()

    try:
        subject, body = revise_email_template(
            instruction,
            template.subject or "",
            template.body or "",
            sender_company=current_user.company or "",
            product_description=current_user.product_description or "",
        )
    except Exception as exc:
        flash(f"템플릿 수정에 실패했습니다: {exc}", "danger")
        return redirect(url_for("mail_template.edit_template", version=version))

    template.subject = subject
    template.body = body
    template.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("mail_template.edit_template", version=version))


@mail_template_bp.route("/template/<int:version>/label", methods=["POST"])
@login_required
def rename(version):
    template = _get_version(version)
    template.label = request.form.get("label", "").strip() or None
    db.session.commit()
    return redirect(url_for("mail_template.edit_template", version=version))


@mail_template_bp.route("/template/<int:version>/activate", methods=["POST"])
@login_required
def activate(version):
    EmailTemplate.query.filter(
        EmailTemplate.user_id == current_user.id, EmailTemplate.version != version
    ).update({"is_active": False})
    template = _get_version(version)
    template.is_active = True
    db.session.commit()
    flash(f"버전 {version}이(가) 발송용 템플릿으로 설정되었습니다.", "success")
    return redirect(url_for("mail_template.edit_template", version=version))


# ---------------------------------------------------------------- profile --

@buyer_profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("이름은 필수 입력 항목입니다.", "danger")
            return redirect(url_for("buyer_profile.edit_profile"))
        current_user.name = name
        current_user.company = request.form.get("company", "").strip() or None
        current_user.position = request.form.get("position", "").strip() or None
        current_user.product_description = request.form.get("product_description", "").strip() or None
        db.session.commit()
        flash("내 정보가 저장되었습니다.", "success")
        return redirect(url_for("buyer_profile.edit_profile"))
    return render_template("buyers/profile.html")


# ------------------------------------------------------------------ gmail --

def _gmail_redirect_uri():
    """로컬 개발 중엔 지금 접속한 주소(localhost 또는 127.0.0.1) 그대로 구글이 되돌려 보내게 한다.
    브라우저는 두 주소를 다른 사이트로 보고 세션 쿠키를 따로 가져서, 접속 주소와 돌아오는
    주소가 다르면 연동 도중 로그인 세션이 끊긴다. 그 외(운영 등)엔 .env의 GOOGLE_REDIRECT_URI를 쓴다.
    구글 콘솔의 '승인된 리디렉션 URI'에 두 주소 모두 등록돼 있어야 한다."""
    if request.host.split(":")[0] in ("localhost", "127.0.0.1"):
        return url_for("auth.google_callback_redirect", _external=True)
    return None


@buyer_gmail_bp.route("/connect")
@login_required
def connect():
    flow = build_flow(_gmail_redirect_uri())
    # access_type=offline + prompt=consent 이어야 매번 refresh_token을 받을 수 있다
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["gmail_oauth_state"] = state
    session["gmail_code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@buyer_gmail_bp.route("/callback")
@login_required
def callback():
    state = session.get("gmail_oauth_state")
    if not state or state != request.args.get("state"):
        flash("연동 요청이 유효하지 않습니다. 다시 시도해주세요.", "danger")
        return redirect(url_for("contacts.list_contacts"))

    flow = build_flow(_gmail_redirect_uri())
    flow.code_verifier = session.get("gmail_code_verifier")
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    if not credentials.refresh_token:
        flash("Gmail 발송 권한 승인이 필요합니다. 다시 연동해주세요.", "danger")
        return redirect(url_for("contacts.list_contacts"))

    userinfo = fetch_userinfo(credentials)
    current_user.google_email = userinfo["email"]
    current_user.google_refresh_token = encrypt_token(credentials.refresh_token)
    db.session.commit()

    flash(f"{userinfo['email']} 계정으로 Gmail 발송이 연동되었습니다.", "success")
    return redirect(url_for("contacts.list_contacts"))

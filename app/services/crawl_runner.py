"""대시보드의 "크롤링 새로고침" 버튼이 호출하는 백그라운드 크롤링 실행기.

scripts/crawl/sync_to_db.py의 크롤링/동기화 함수를 그대로 재사용하되, 웹 요청을
막지 않도록 별도 스레드에서 돌리고 진행 상태를 메모리에 들고 있는다. 여러 명이
동시에 버튼을 눌러도 실제로는 한 번에 하나만 돌도록 락으로 막는다."""

import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone

_CRAWL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "crawl")
sys.path.insert(0, os.path.abspath(_CRAWL_DIR))
import sync_to_db as _sync  # noqa: E402  (경로 추가 이후에 import)

_lock = threading.Lock()
_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "new_count": 0,
    "updated_count": 0,
    "deactivated_count": 0,
    "failed_labels": [],
}


def get_status():
    with _lock:
        return dict(_state)


def start_crawl(db_path, site_keys=None, with_details=False):
    """이미 실행 중이면 아무것도 하지 않고 False 반환, 새로 시작했으면 True."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            running=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=None,
            error=None,
            failed_labels=[],
        )

    thread = threading.Thread(target=_run, args=(db_path, site_keys, with_details), daemon=True)
    thread.start()
    return True


def _run(db_path, site_keys, with_details):
    try:
        keys = site_keys or list(_sync.SITES.keys())
        labels_urls = [_sync.SITES[k] for k in keys]
        labels = [label for label, _ in labels_urls]

        conn = sqlite3.connect(db_path)
        _sync.init_db(conn)

        rows, failed_labels = _sync.crawl_selected_sites(
            labels_urls, with_details=with_details, verbose=False
        )
        new_count, updated_count, _unchanged, seen_urls = _sync.sync_rows(conn, rows)

        # 크롤링 자체가 실패한 카테고리는 "확인했더니 없어졌다"가 아니라 "확인을 못 했다"이므로
        # 비활성 처리 대상에서 제외 (안 그러면 일시적 네트워크 장애로 기존 데이터가 전부 사라져 보임)
        succeeded_labels = [label for label in labels if label not in failed_labels]
        deactivated = _sync.deactivate_missing(conn, succeeded_labels, seen_urls) if succeeded_labels else 0
        conn.close()

        with _lock:
            _state.update(
                new_count=new_count,
                updated_count=updated_count,
                deactivated_count=deactivated,
                failed_labels=failed_labels,
            )
    except Exception as e:
        with _lock:
            _state["error"] = str(e)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now(timezone.utc).isoformat()

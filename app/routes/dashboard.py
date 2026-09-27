import json
import subprocess
import sys
import threading
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required

from app.models import Exhibition

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_PIPELINE_SCRIPT = _BASE_DIR / "scripts" / "weekly_pipeline.py"
_RESULT_PATH = _BASE_DIR / "instance" / "logs" / "last_result.json"

# 박람회 갱신 파이프라인(크롤링+분류, 몇 분~몇십 분 걸림)을 웹 요청과 별도
# 스레드에서 돌리기 위한 아주 단순한 인메모리 상태. 여러 워커 프로세스로
# 띄우는 배포라면 워커별로 따로 도니 프로세스 간 공유는 안 되지만, 이
# 프로젝트는 단일 내부용 인스턴스라 이 정도로 충분하다.
_pipeline_lock = threading.Lock()
_pipeline_state = {"running": False, "process": None, "banner": None}


def is_pipeline_running():
    return _pipeline_state["running"]


def pop_pipeline_banner():
    """완료 배너 메시지를 한 번만 반환하고 지운다 (다음 페이지 로드부턴 안 뜸).
    "업데이트 완료! (신규 추가: N건 / 내용 업데이트: M건 / 변경 없음: K건)" 형태."""
    with _pipeline_lock:
        banner = _pipeline_state["banner"]
        _pipeline_state["banner"] = None
    return banner


def _build_banner_text(result):
    if not result.get("ok"):
        failed = ", ".join(result.get("failed_steps") or [])
        return f"업데이트 중 일부 단계 실패 ({failed}) - 자세한 내용은 instance/logs 폴더 확인"
    summary = result.get("crawl_summary")
    if not summary:
        return "업데이트 완료!"
    return (
        "업데이트 완료! (신규 추가: {new}건 / 내용 업데이트: {updated}건 / 변경 없음: {unchanged}건)"
    ).format(
        new=summary.get("new", 0), updated=summary.get("updated", 0), unchanged=summary.get("unchanged", 0),
    )


def _run_pipeline_background(skip_crawl):
    cmd = [sys.executable, str(_PIPELINE_SCRIPT)]
    if skip_crawl:
        cmd.append("--skip-crawl")
    process = subprocess.Popen(cmd, cwd=str(_BASE_DIR))
    _pipeline_state["process"] = process
    process.wait()

    banner = "업데이트 완료!"
    try:
        if _RESULT_PATH.exists():
            result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
            banner = _build_banner_text(result)
    except Exception:
        pass

    with _pipeline_lock:
        _pipeline_state["running"] = False
        _pipeline_state["process"] = None
        _pipeline_state["banner"] = banner

# 지도는 나중에 추가 예정 — 지금은 대륙 버튼만
CONTINENTS = ["아메리카", "유럽", "중동·아프리카", "아시아", "오세아니아"]

# DB에 들어있는 continent 값이 위 5개 권역 표기와 다르게 저장돼 있어서 매핑
CONTINENT_DB_VALUES = {
    "아메리카": ["북미", "북아메리카", "남미"],
    "유럽": ["유럽"],
    "중동·아프리카": ["아프리카", "중동"],
    "아시아": ["아시아"],
    "오세아니아": ["오세아니아"],
}


@bp.route("/")
@login_required
def index():
    from app.routes.exhibition import _build_list_context

    dup_ids = Exhibition.duplicate_ids()

    counts = {}
    for region, db_values in CONTINENT_DB_VALUES.items():
        counts[region] = Exhibition.query.filter(
            Exhibition.continent.in_(db_values),
            Exhibition.is_active == 1,
            Exhibition.id.notin_(dup_ids),
        ).count()

    all_list_ctx = _build_list_context(
        Exhibition.query.filter(Exhibition.is_active == 1, Exhibition.id.notin_(dup_ids)),
        "해외",
        "exhibition.expo_list_partial_all",
        {},
        "",
    )

    return render_template(
        "dashboard/continent_map.html", continents=CONTINENTS, counts=counts,
        pipeline_running=is_pipeline_running(), pipeline_banner=pop_pipeline_banner(), **all_list_ctx
    )


@bp.route("/run-weekly-pipeline", methods=["POST"])
@login_required
def run_weekly_pipeline():
    """박람회 크롤링+분류 4단계(scripts/weekly_pipeline.py)를 수동으로 즉시
    실행. 평소엔 서버 cron으로 주 1회 자동 실행되고, 이건 그 사이에 급하게
    최신 목록이 필요하거나 실패를 바로 재시도하고 싶을 때 쓰는 수동 트리거."""
    with _pipeline_lock:
        if _pipeline_state["running"]:
            flash("이미 파이프라인이 실행 중입니다. 끝날 때까지 기다려주세요.", "danger")
            return redirect(url_for("dashboard.index"))
        _pipeline_state["running"] = True

    thread = threading.Thread(target=_run_pipeline_background, args=(False,), daemon=True)
    thread.start()
    flash("박람회 업데이트를 시작했습니다. 몇 분~몇십 분 걸릴 수 있어요.", "success")
    return redirect(url_for("dashboard.index"))

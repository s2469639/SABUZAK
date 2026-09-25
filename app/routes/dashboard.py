import subprocess
import sys
import threading
from pathlib import Path

from flask import Blueprint, Response, flash, redirect, render_template, url_for
from flask_login import login_required

from app.models import Exhibition

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_PIPELINE_SCRIPT = _BASE_DIR / "scripts" / "weekly_pipeline.py"
_LOG_DIR = _BASE_DIR / "instance" / "logs"

# 박람회 갱신 파이프라인(크롤링+분류, 몇 분~몇십 분 걸림)을 웹 요청과 별도
# 스레드에서 돌리기 위한 아주 단순한 인메모리 상태. 여러 워커 프로세스로
# 띄우는 배포라면 워커별로 따로 도니 프로세스 간 공유는 안 되지만, 이
# 프로젝트는 단일 내부용 인스턴스라 이 정도로 충분하다.
_pipeline_lock = threading.Lock()
_pipeline_state = {"running": False, "process": None}


def _run_pipeline_background(skip_crawl):
    cmd = [sys.executable, str(_PIPELINE_SCRIPT)]
    if skip_crawl:
        cmd.append("--skip-crawl")
    process = subprocess.Popen(cmd, cwd=str(_BASE_DIR))
    _pipeline_state["process"] = process
    process.wait()
    with _pipeline_lock:
        _pipeline_state["running"] = False
        _pipeline_state["process"] = None

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
        pipeline_running=_pipeline_state["running"], **all_list_ctx
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
    flash("박람회 크롤링+분류를 백그라운드에서 시작했습니다. 몇 분~몇십 분 걸릴 수 있어요 (진행 로그는 아래 링크로 확인).", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/pipeline-status")
@login_required
def pipeline_status():
    """가장 최근 파이프라인 실행 로그 파일을 그대로 텍스트로 보여준다
    (별도 화면 없이 새로고침만으로 진행 상황을 볼 수 있게)."""
    if not _LOG_DIR.exists():
        return Response("아직 실행 로그가 없습니다.", mimetype="text/plain")

    logs = sorted(_LOG_DIR.glob("weekly_pipeline_*.log"), reverse=True)
    if not logs:
        return Response("아직 실행 로그가 없습니다.", mimetype="text/plain")

    content = logs[0].read_text(encoding="utf-8", errors="replace")
    status = "실행 중...\n\n" if _pipeline_state["running"] else "완료됨\n\n"
    return Response(status + content, mimetype="text/plain")

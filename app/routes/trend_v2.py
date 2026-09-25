"""JH님이 새로 만든 v15/(트렌드 조사 + 부스 컨셉, 3D 부스 뷰어 포함) 시스템을
그대로 Flask 앱에 붙이는 블루프린트.

v15/ 폴더 자체(app.py 제외한 services.py/jobs.py/research.py/...)는 손대지
않고 그대로 재사용한다 - 그 안의 모듈들이 서로 `import jobs`, `from services
import ...`처럼 flat하게(패키지 경로 없이) 서로를 import하기 때문에, v15/
폴더 자체를 sys.path에 넣어야 한다 (app/services/market_trend.py가
market_trend_analysis/를 붙이던 것과 같은 패턴).

라우트 경로는 v15/app.py가 원래 쓰던 절대경로(/trend/<id>, /booth,
/api/...)를 그대로 유지한다 - base.html의 JS가 이 경로들을 하드코딩해서
호출하기 때문에(예: fetch("/api/" + kind + "/" + id + "/progress")),
url_prefix를 붙이면 그 JS 호출이 다 깨진다. 입력 폼 화면(v15 원래의 "/")만
우리 앱 루트("/")가 이미 로그인 리다이렉트로 쓰이고 있어서 "/trend-research"로
옮겼다.

박람회 상세 페이지의 "트렌드 조사" 탭에서 특정 (박람회, 제품) 조합으로
바로 들어올 수 있게 /trend-research 진입점이 쿼리스트링으로 미리 값을
채워준다 (제품명/국가/강점/원재료/인증/가격/박람회명/박람회사이트).
"""

import os
import sys

from flask import Blueprint, jsonify, redirect, render_template, request
from flask_login import current_user, login_required

from app.extensions import db
from app.models import TrendResult

_V15_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "v15")
if _V15_ROOT not in sys.path:
    sys.path.insert(0, _V15_ROOT)

import jobs  # noqa: E402
from services import INPUT_FIELDS, run_booth, run_trend, start_booth_job, start_trend_job  # noqa: E402

pages_bp = Blueprint("trend_v2", __name__, template_folder="../templates/trend_v2")
api_bp = Blueprint("trend_v2_api", __name__, url_prefix="/api")

QUESTION_LABELS = {"Q1": "CONSUMER", "Q2": "COMPETITION", "Q3": "BUYER & CHANNEL", "Q4": "TRADE SHOW & BOOTH"}


def _form_from(source):
    return {f: (source.get(f) or "").strip() for f in INPUT_FIELDS}


def _empty_form():
    return {f: "" for f in INPUT_FIELDS}


def _booth_link(form, booth_job_id=None):
    if booth_job_id:
        return f"/booth/{booth_job_id}"
    from urllib.parse import urlencode
    return "/booth?" + urlencode({k: v for k, v in form.items() if v})


def _trend_page(form, data=None, error=None, force=False, booth_job_id=None, job_id=None, expo_id=None, product_id=None):
    return render_template(
        "trend_v2/trend.html", form=form, data=data, error=error, force=force,
        question_labels=QUESTION_LABELS, booth_link=_booth_link(form, booth_job_id),
        job_id=job_id, expo_id=expo_id, product_id=product_id,
    )


def _booth_page(form, data=None, error=None, force=False, job_id=None, running=False):
    return render_template(
        "trend_v2/booth.html", form=form, data=data, error=error, force=force,
        job_id=job_id, running=running,
    )


# ---------------------------------------------------------------------------
# 트렌드 조사
# ---------------------------------------------------------------------------

@pages_bp.route("/trend-research", methods=["GET", "POST"])
@login_required
def trend_index():
    """GET: 입력 화면(쿼리스트링으로 미리 채울 수 있음). POST: 자바스크립트가
    꺼진 브라우저용(진행률 없이 끝날 때까지 기다림)."""
    if request.method == "GET":
        prefill = _form_from(request.args) if request.args else _empty_form()
        return _trend_page(prefill, expo_id=request.args.get("expo_id"), product_id=request.args.get("product_id"))
    form, force = _form_from(request.form), bool(request.form.get("force"))
    expo_id = request.form.get("expo_id")
    product_id = request.form.get("product_id")
    try:
        return _trend_page(form, run_trend(form, force=force), force=force, expo_id=expo_id, product_id=product_id)
    except ValueError as e:
        return _trend_page(form, error=str(e), force=force, expo_id=expo_id, product_id=product_id)
    except Exception as e:
        return _trend_page(form, error=f"분석 중 오류가 발생했습니다: {e}", force=force, expo_id=expo_id, product_id=product_id)


def _build_trend_summary(result):
    """'작성 중인 박람회' 목록에 한 줄로 보여줄 요약. 리테일 가격대 + 대상
    국가 정도만 뽑는다 (전체 조사 결과는 /trend/<job_id>에서 확인)."""
    if not result:
        return ""
    s1 = result.get("section1") or {}
    s2 = result.get("section2") or {}
    rp = s2.get("retail_price") or {}
    parts = []
    if s1.get("country_ko"):
        parts.append(s1["country_ko"])
    if rp.get("price"):
        parts.append(f"소매가 {rp['price']}")
    return " · ".join(parts) or "분석 완료"


def _persist_trend_result(job, job_id):
    """트렌드 조사가 (박람회, 제품) 조합으로 시작된 경우, '작성 중인 박람회'
    목록에서 보여줄 수 있게 가벼운 요약 포인터를 남긴다. expo_id/product_id가
    없으면(예: v15 폼에서 직접 시작) 그냥 건너뛴다."""
    links = job.get("links") or {}
    expo_id, product_id = links.get("expo_id"), links.get("product_id")
    if not expo_id or not product_id:
        return
    try:
        expo_id, product_id = int(expo_id), int(product_id)
    except (TypeError, ValueError):
        return

    existing = TrendResult.query.filter_by(
        user_id=current_user.id, exhibition_id=expo_id, product_id=product_id,
    ).first()
    summary = _build_trend_summary(job.get("result"))
    if existing:
        existing.job_id, existing.summary = job_id, summary
    else:
        existing = TrendResult(
            user_id=current_user.id, exhibition_id=expo_id, product_id=product_id,
            job_id=job_id, summary=summary,
        )
        db.session.add(existing)
    db.session.commit()


@pages_bp.get("/trend/<job_id>")
@login_required
def trend_result(job_id):
    job = jobs.get(job_id, "trend")
    if not job or job["status"] == "running":
        return redirect("/trend-research")
    if job["status"] == "done":
        _persist_trend_result(job, job_id)
    booth_job_id = job.get("links", {}).get("booth_job_id")
    return _trend_page(
        job["form"], job["result"], job["error"], job["force"],
        booth_job_id=booth_job_id, job_id=job_id,
    )


# ---------------------------------------------------------------------------
# 부스 컨셉 (v15 자체 시스템 - 3D 부스 뷰어 포함)
# ---------------------------------------------------------------------------

@pages_bp.route("/booth", methods=["GET", "POST"])
@login_required
def booth_index():
    """GET: 부스 컨셉만 따로 실행하는 화면(쿼리스트링으로 미리 채울 수 있음).
    POST: 자바스크립트가 꺼진 브라우저용."""
    if request.method == "GET":
        return _booth_page(_form_from(request.args))
    form, force = _form_from(request.form), bool(request.form.get("force"))
    try:
        return _booth_page(form, run_booth(form, force=force), force=force)
    except ValueError as e:
        return _booth_page(form, error=str(e), force=force)


@pages_bp.get("/booth/<job_id>")
@login_required
def booth_result(job_id):
    job = jobs.get(job_id, "booth")
    if not job:
        return _booth_page(_empty_form(), error="부스 기획 작업을 찾지 못했습니다. 서버가 다시 시작되었을 수 있어요. 다시 실행해 주세요.")
    if job["status"] == "running":
        return _booth_page(job["form"], job_id=job_id, running=True)
    return _booth_page(job["form"], job["result"], job["error"], job["force"], job_id=job_id)


# ---------------------------------------------------------------------------
# JSON API (로딩 화면 폴링용 - base.html의 JS가 절대경로 /api/...로 호출)
# ---------------------------------------------------------------------------

def _progress_json(job):
    snap = job["progress"].snapshot()
    if job["status"] == "done":
        snap["percent"] = 100
    return {**snap, "status": job["status"], "error": job["error"], **job["links"]}


@api_bp.post("/trend/start")
@login_required
def api_trend_start():
    raw = request.form or request.get_json(silent=True) or {}
    try:
        ids = start_trend_job(_form_from(raw), force=bool(request.values.get("force")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    # 박람회 상세의 "트렌드 조사" 탭에서 시작된 경우에만 딸려오는 값 - 나중에
    # trend_result()가 "작성 중인 박람회" 목록용 요약을 남길 때 이 둘로 찾는다.
    expo_id, product_id = raw.get("expo_id"), raw.get("product_id")
    if expo_id and product_id:
        job = jobs.get(ids["job_id"])
        if job:
            job["links"]["expo_id"] = expo_id
            job["links"]["product_id"] = product_id
    return jsonify(ids)


@api_bp.post("/booth/start")
@login_required
def api_booth_start():
    try:
        job_id = start_booth_job(
            _form_from(request.form or request.get_json(silent=True) or {}),
            force=bool(request.values.get("force")),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"job_id": job_id})


@api_bp.get("/<kind>/<job_id>/progress")
@login_required
def api_progress(kind, job_id):
    job = jobs.get(job_id, kind)
    if not job:
        return jsonify({"status": "missing", "error": "작업을 찾지 못했어요. 서버가 다시 시작되었을 수 있어요."}), 404
    return jsonify(_progress_json(job))


@api_bp.get("/<kind>/<job_id>")
@login_required
def api_result(kind, job_id):
    job = jobs.get(job_id, kind)
    if not job:
        return jsonify({"status": "missing"}), 404
    return jsonify({"status": job["status"], "error": job["error"], "result": job["result"], **job["links"]})

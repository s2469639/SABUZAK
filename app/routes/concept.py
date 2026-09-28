import json
from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, Response, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import ConceptDraft, Exhibition, Product
from app.routes.trend_v2 import _get_job, start_booth_job
from app.services.booth_concept import draft_fields, v15_form
from app.services.pdf_report import pdf_font_context

bp = Blueprint("concept", __name__, url_prefix="/concept")


def _checked_products():
    return (
        Product.query.filter_by(user_id=current_user.id, is_checked=True)
        .order_by(Product.created_at.desc())
        .all()
    )


def _load_extra(draft):
    try:
        return json.loads(draft.extra_data) if draft.extra_data else {}
    except ValueError:
        return {}


def _save_extra(draft, extra):
    draft.extra_data = json.dumps(extra, ensure_ascii=False)
    db.session.commit()


def _apply_booth(draft, expo, booth, products):
    """v15 부스 기획 결과를 draft 항목에 옮긴다. 바이어 어필 포인트는 extra에 담아 돌려준다."""
    product_name = products[0].name if products else ""
    fields = draft_fields(booth, product_name)
    draft.theme = fields["theme"]
    draft.slogan = fields["slogan"]
    draft.description = fields["description"]
    draft.selling_points = json.dumps(fields["selling_points"], ensure_ascii=False)
    draft.events = json.dumps(fields["events"], ensure_ascii=False)
    draft.target_buyers = json.dumps(fields["target_buyers"], ensure_ascii=False)
    return fields["buyer_appeal"]


def _sync_booth_job(draft, expo, products):
    """진행 중인 v15 부스 작업이 끝났으면 결과를 draft에 반영한다. 아직 실행 중이면 True."""
    extra = _load_extra(draft)
    job_id = extra.get("booth_job_id")
    if not job_id or extra.get("applied_booth_job_id") == job_id:
        return extra, False

    job = _get_job(job_id, "booth")
    if job is None:
        extra.pop("booth_job_id")
        extra["booth_error"] = "부스 기획 작업을 찾지 못했어요. 서버가 다시 시작되었을 수 있어요. 다시 생성해 주세요."
        _save_extra(draft, extra)
        return extra, False
    if job["status"] == "running":
        return extra, True

    result = job.get("result") or {}
    booth = result.get("booth")
    if job["status"] == "done" and booth:
        extra["buyer_appeal"] = _apply_booth(draft, expo, booth, products)
        extra.pop("visitor_journey", None)
        extra.pop("booth_error", None)
    else:
        extra["booth_error"] = job.get("error") or result.get("booth_error") or "부스 기획안을 만들지 못했습니다."
    extra["applied_booth_job_id"] = job_id
    _save_extra(draft, extra)
    return extra, False


@bp.route("/start/<int:expo_id>", methods=["POST"])
@login_required
def start(expo_id):
    """'부스 컨셉 기획 →' 버튼. 박람회당 draft 하나를 만들고 화면으로 이동한다."""
    expo = Exhibition.query.get_or_404(expo_id)
    draft = ConceptDraft.query.filter_by(user_id=current_user.id, exhibition_id=expo_id).first()
    if draft is None:
        draft = ConceptDraft(
            user_id=current_user.id,
            exhibition_id=expo_id,
            exhibition_name=expo.name,
            exhibition_country=expo.country_ko or expo.country,
            status="concept",
        )
        db.session.add(draft)
        db.session.commit()
    return redirect(url_for("concept.detail", draft_id=draft.id))


@bp.route("/<int:draft_id>")
@login_required
def detail(draft_id):
    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    expo = Exhibition.query.get_or_404(draft.exhibition_id)
    products = _checked_products()
    extra, running = _sync_booth_job(draft, expo, products)

    return render_template(
        "concept/booth_concept.html",
        draft=draft,
        expo=expo,
        products=products,
        selling_points=json.loads(draft.selling_points) if draft.selling_points else [],
        events=json.loads(draft.events) if draft.events else [],
        target_buyers=json.loads(draft.target_buyers) if draft.target_buyers else [],
        buyer_appeal=extra.get("buyer_appeal") or [],
        booth_job_id=extra.get("booth_job_id") if running else None,
        booth_error=extra.get("booth_error"),
    )


@bp.route("/<int:draft_id>/report")
@login_required
def booth_report_pdf(draft_id):
    """이미 생성된 부스 컨셉 기획안(draft)을 인쇄용 레이아웃으로 다시 그려서
    PDF로 내려준다. 새로 생성하지 않는다 - AI를 다시 부르지 않으므로 추가
    비용이 들지 않는다."""
    from weasyprint import HTML

    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    if not draft.theme:
        flash("먼저 '컨셉 자동 생성하기'로 부스 컨셉을 만든 뒤 다시 시도해주세요.", "danger")
        return redirect(url_for("concept.detail", draft_id=draft.id))

    expo = Exhibition.query.get_or_404(draft.exhibition_id)
    products = _checked_products()
    extra = _load_extra(draft)

    html = render_template(
        "concept/booth_report_pdf.html",
        draft=draft, expo=expo, products=products,
        selling_points=json.loads(draft.selling_points) if draft.selling_points else [],
        events=json.loads(draft.events) if draft.events else [],
        target_buyers=json.loads(draft.target_buyers) if draft.target_buyers else [],
        buyer_appeal=extra.get("buyer_appeal") or [],
        current_user=current_user, generated_at=datetime.now(),
        **pdf_font_context(),
    )
    pdf_bytes = HTML(string=html).write_pdf()

    filename = f"{expo.name}_부스컨셉기획서.pdf".replace("/", "-")
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@bp.route("/<int:draft_id>/generate", methods=["POST"])
@login_required
def generate(draft_id):
    """v15 부스 기획을 백그라운드로 시작한다 (몇 분 걸림). 끝나면 detail()이 결과를 반영한다."""
    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    expo = Exhibition.query.get_or_404(draft.exhibition_id)
    products = _checked_products()
    if not products:
        flash("마이페이지에서 제품을 먼저 등록하고 체크해 주세요.", "danger")
        return redirect(url_for("concept.detail", draft_id=draft.id))

    try:
        # v15의 부스 기획 캐시는 draft 단위가 아니라 (제품명,국가,박람회명,
        # 웹사이트) 조합으로 전역 공유되고, 웹검색+상위 모델(gpt-5.6-sol)을
        # 쓰는 무거운 작업이라 매번 강제로 새로 돌리면 토큰 비용이 크게
        # 늘어난다. 그래서 절충안: 처음 생성할 때(draft.theme이 비어있을
        # 때)는 캐시를 허용하고(v15/services.py BOOTH_CACHE_DAYS=7일),
        # 이미 결과가 있는 draft를 "생성하기"로 다시 누른 경우(재생성 의도가
        # 분명한 경우)만 캐시를 건너뛰고 강제로 새로 기획한다.
        job_id = start_booth_job(v15_form(expo, products[0]), force=bool(draft.theme))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("concept.detail", draft_id=draft.id))

    extra = _load_extra(draft)
    extra["booth_job_id"] = job_id
    extra.pop("booth_error", None)
    _save_extra(draft, extra)
    return redirect(url_for("concept.detail", draft_id=draft.id))

import json
import os
import sqlite3

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import ConceptDraft, Exhibition, Product
from app.services.booth_concept import generate_booth_concept, generate_booth_image

bp = Blueprint("concept", __name__, url_prefix="/concept")


def _load_v15_trend_cache(job_id: str) -> dict:
    """v15의 cache.db에서 해당 job_id의 1~3번 시장 트렌드 분석 결과를 조회한다."""
    if not job_id:
        return {}
    # 프로젝트 내 cache.db 경로 탐색
    db_paths = [
        os.path.join(current_app.root_path, "..", "cache.db"),
        os.path.join(current_app.root_path, "cache.db"),
        os.path.join(os.getcwd(), "cache.db"),
        os.path.join(os.getcwd(), "v15", "cache.db"),
    ]
    for p in db_paths:
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                cur = conn.cursor()
                cur.execute("SELECT data FROM jobs WHERE id = ?", (job_id,))
                row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    return json.loads(row[0])
            except Exception:
                pass
    return {}


@bp.route("/start/<int:expo_id>", methods=["POST"])
@login_required
def start(expo_id):
    """'부스 컨셉 기획 →' 버튼. job_id가 있으면 draft에 기록해 두고 화면으로 이동한다."""
    expo = Exhibition.query.get_or_404(expo_id)
    job_id = request.form.get("job_id", "").strip()

    draft = ConceptDraft.query.filter_by(
        user_id=current_user.id, exhibition_id=expo_id
    ).first()

    if draft is None:
        draft = ConceptDraft(
            user_id=current_user.id,
            exhibition_id=expo_id,
            exhibition_name=expo.name,
            exhibition_country=expo.country_ko or expo.country,
            status="concept",
        )
        db.session.add(draft)

    # job_id가 전달되었으면 extra_data에 보존해 둠
    if job_id:
        existing_extra = {}
        if hasattr(draft, "extra_data") and draft.extra_data:
            try:
                existing_extra = json.loads(draft.extra_data) if isinstance(draft.extra_data, str) else draft.extra_data
            except Exception:
                pass
        existing_extra["trend_job_id"] = job_id
        if hasattr(draft, "extra_data"):
            draft.extra_data = json.dumps(existing_extra, ensure_ascii=False)

    db.session.commit()
    return redirect(url_for("concept.detail", draft_id=draft.id))


@bp.route("/<int:draft_id>")
@login_required
def detail(draft_id):
    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    expo = Exhibition.query.get(draft.exhibition_id)

    products = (
        Product.query.filter_by(user_id=current_user.id, is_checked=True)
        .order_by(Product.created_at.desc())
        .all()
    )

    selling_points = json.loads(draft.selling_points) if draft.selling_points else []
    events = json.loads(draft.events) if draft.events else []
    target_buyers = json.loads(draft.target_buyers) if draft.target_buyers else []

    visitor_journey = None
    if hasattr(draft, "extra_data") and draft.extra_data:
        try:
            extra = json.loads(draft.extra_data) if isinstance(draft.extra_data, str) else draft.extra_data
            visitor_journey = extra.get("visitor_journey")
        except Exception:
            visitor_journey = None
    elif hasattr(draft, "visitor_journey") and draft.visitor_journey:
        try:
            visitor_journey = json.loads(draft.visitor_journey) if isinstance(draft.visitor_journey, str) else draft.visitor_journey
        except Exception:
            visitor_journey = None

    return render_template(
        "concept/booth_concept.html",
        draft=draft,
        expo=expo,
        products=products,
        selling_points=selling_points,
        events=events,
        target_buyers=target_buyers,
        visitor_journey=visitor_journey,
    )


@bp.route("/<int:draft_id>/generate", methods=["POST"])
@login_required
def generate(draft_id):
    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    expo = Exhibition.query.get_or_404(draft.exhibition_id)

    products = (
        Product.query.filter_by(user_id=current_user.id, is_checked=True)
        .order_by(Product.created_at.desc())
        .all()
    )

    # 1. v15에서 전달된 트렌드 분석 캐시 데이터 확인
    trend_job_id = None
    existing_extra = {}
    if hasattr(draft, "extra_data") and draft.extra_data:
        try:
            existing_extra = json.loads(draft.extra_data) if isinstance(draft.extra_data, str) else draft.extra_data
            trend_job_id = existing_extra.get("trend_job_id")
        except Exception:
            pass

    trends_data = _load_v15_trend_cache(trend_job_id) if trend_job_id else None

    # 2. v15 트렌드 분석 데이터를 주입하여 부스 컨셉 생성 호출!
    result = generate_booth_concept(expo, products, trends_data=trends_data)
    theme = result.get("booth_theme", {})

    draft.theme = theme.get("title", "")
    draft.slogan = theme.get("slogan", "")
    draft.description = theme.get("description", "")
    draft.selling_points = json.dumps(result.get("selling_points", []), ensure_ascii=False)
    draft.events = json.dumps(result.get("event_plans", []), ensure_ascii=False)
    draft.target_buyers = json.dumps(result.get("target_buyers", []), ensure_ascii=False)
    draft.image_prompt = result.get("image_generation", {}).get("prompt", "")
    draft.image_path = None

    # 신규 기획 메타데이터 저장
    existing_extra["visitor_journey"] = result.get("visitor_journey")
    existing_extra["booth_3d"] = result.get("booth_3d")
    if hasattr(draft, "extra_data"):
        draft.extra_data = json.dumps(existing_extra, ensure_ascii=False)
    elif hasattr(draft, "visitor_journey"):
        draft.visitor_journey = json.dumps(result.get("visitor_journey", {}), ensure_ascii=False)

    db.session.commit()
    return redirect(url_for("concept.detail", draft_id=draft.id))


@bp.route("/<int:draft_id>/generate-image", methods=["POST"])
@login_required
def generate_image(draft_id):
    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    if not draft.image_prompt:
        flash("먼저 컨셉을 생성해주세요.", "danger")
        return redirect(url_for("concept.detail", draft_id=draft.id))

    try:
        image_bytes = generate_booth_image(draft.image_prompt)
    except Exception as e:
        flash(f"이미지 생성에 실패했습니다: {e}", "danger")
        return redirect(url_for("concept.detail", draft_id=draft.id))

    rel_path = f"generated/concept/{draft.id}.png"
    abs_path = os.path.join(current_app.static_folder, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(image_bytes)

    draft.image_path = rel_path
    db.session.commit()
    flash("부스 예상 이미지를 생성했습니다.", "success")

    return redirect(url_for("concept.detail", draft_id=draft.id))
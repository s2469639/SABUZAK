import json
import os

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import ConceptDraft, Exhibition, Product
from app.services.booth_concept import generate_booth_concept, generate_booth_image

bp = Blueprint("concept", __name__, url_prefix="/concept")


@bp.route("/start/<int:expo_id>", methods=["POST"])
@login_required
def start(expo_id):
    """'부스 컨셉 기획 →' 버튼. 이미 이 박람회로 만든 초안이 있으면 그대로 재사용하고,
    없으면 새로 만든 다음 컨셉 기획 화면으로 이동한다."""
    expo = Exhibition.query.get_or_404(expo_id)

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

    return render_template(
        "concept/booth_concept.html",
        draft=draft,
        expo=expo,
        products=products,
        selling_points=selling_points,
        events=events,
        target_buyers=target_buyers,
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

    result = generate_booth_concept(expo, products)
    theme = result.get("booth_theme", {})

    draft.theme = theme.get("title", "")
    draft.slogan = theme.get("slogan", "")
    draft.description = theme.get("description", "")
    draft.selling_points = json.dumps(result.get("selling_points", []), ensure_ascii=False)
    draft.events = json.dumps(result.get("event_plans", []), ensure_ascii=False)
    draft.target_buyers = json.dumps(result.get("target_buyers", []), ensure_ascii=False)
    draft.image_prompt = result.get("image_generation", {}).get("prompt", "")
    draft.image_path = None  # 컨셉이 바뀌었으니 이전 프롬프트로 만든 이미지는 무효
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

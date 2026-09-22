from flask import Blueprint, redirect, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import ConceptDraft, Exhibition

bp = Blueprint("concept", __name__, url_prefix="/concept")


@bp.route("/start/<int:expo_id>", methods=["POST"])
@login_required
def start(expo_id):
    """'부스 컨셉 기획 →' 버튼. 이미 이 박람회로 만든 초안이 있으면 그대로 재사용하고,
    없으면 새로 만든 다음 '작성 중인 박람회' 목록으로 이동한다.
    (컨셉 기획 화면 자체는 아직 없어서, 우선 초안 생성 + 목록 연결까지만 구현)"""
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

    return redirect(url_for("drafts.index"))

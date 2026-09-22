from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.models import ConceptDraft

bp = Blueprint("drafts", __name__, url_prefix="/drafts")

STATUS_LABELS = {
    "concept": "컨셉 기획 중",
    "proposal": "기안서 작성 중",
    "done": "완료",
}


@bp.route("/")
@login_required
def index():
    drafts = (
        ConceptDraft.query.filter_by(user_id=current_user.id)
        .order_by(ConceptDraft.updated_at.desc())
        .all()
    )
    return render_template(
        "drafts/drafts_list.html", drafts=drafts, status_labels=STATUS_LABELS
    )

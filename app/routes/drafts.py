from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import ConceptDraft, TrendResult

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

    # 박람회당 트렌드 조사 결과는 여러 제품에 걸쳐 있을 수 있는데, 여기서는
    # "이어서 작성" 옆에 한 줄만 보여줄 거라 가장 최근 것 하나만 가져온다.
    trend_by_expo = {}
    for draft in drafts:
        latest = (
            TrendResult.query.filter_by(user_id=current_user.id, exhibition_id=draft.exhibition_id)
            .order_by(TrendResult.fetched_at.desc())
            .first()
        )
        if latest:
            trend_by_expo[draft.id] = latest

    return render_template(
        "drafts/drafts_list.html", drafts=drafts, status_labels=STATUS_LABELS,
        trend_by_expo=trend_by_expo,
    )


@bp.route("/<int:draft_id>/delete", methods=["POST"])
@login_required
def delete(draft_id):
    draft = ConceptDraft.query.filter_by(id=draft_id, user_id=current_user.id).first_or_404()
    db.session.delete(draft)
    db.session.commit()
    return redirect(url_for("drafts.index"))

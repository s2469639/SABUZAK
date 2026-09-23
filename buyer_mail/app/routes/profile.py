from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db

bp = Blueprint("profile", __name__)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    if request.method == "POST":
        current_user.name = request.form["name"].strip()
        current_user.company_name = request.form.get("company_name", "").strip()
        current_user.position = request.form.get("position", "").strip()
        db.session.commit()
        flash("내 정보가 저장되었습니다.")
        return redirect(url_for("profile.edit_profile"))
    return render_template("profile.html")

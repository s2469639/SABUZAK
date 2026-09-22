from flask import Blueprint, render_template
from flask_login import login_required, current_user

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/")
@login_required
def index():
    # 더미 대시보드: 실제 세계 지도(continent_map.html)는 이후 구현
    return render_template("dashboard/index.html", user=current_user)

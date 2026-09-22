from flask import Blueprint, render_template
from flask_login import login_required

from app.models import Exhibition

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

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
    counts = {}
    for region, db_values in CONTINENT_DB_VALUES.items():
        counts[region] = Exhibition.query.filter(
            Exhibition.continent.in_(db_values), Exhibition.is_active == 1
        ).count()

    countries = [
        row[0]
        for row in Exhibition.query.filter(Exhibition.is_active == 1)
        .with_entities(Exhibition.country_ko)
        .distinct()
        .order_by(Exhibition.country_ko.asc())
        .all()
        if row[0]
    ]

    return render_template(
        "dashboard/continent_map.html", continents=CONTINENTS, counts=counts, countries=countries
    )

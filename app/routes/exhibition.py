import re

from flask import Blueprint, abort, render_template, request
from flask_login import login_required

from app.models import Exhibition
from app.routes.dashboard import CONTINENT_DB_VALUES

bp = Blueprint("exhibition", __name__, url_prefix="/exhibitions")


def _apply_filters(query):
    category = request.args.get("category", "")
    food_only = request.args.get("food_only", "")
    keyword = request.args.get("keyword", "").strip()

    if category:
        query = query.filter(Exhibition.category == category)
    if food_only == "1":
        query = query.filter(Exhibition.food_yn == 1)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (Exhibition.name.ilike(like))
            | (Exhibition.country_ko.ilike(like))
            | (Exhibition.city.ilike(like))
        )
    return query, category, food_only, keyword


def _categories_for(base_query):
    return [
        row[0]
        for row in base_query.with_entities(Exhibition.category).distinct().all()
        if row[0]
    ]


@bp.route("/<continent>")
@login_required
def expo_list(continent):
    db_values = CONTINENT_DB_VALUES.get(continent)
    if db_values is None:
        abort(404)

    base_query = Exhibition.query.filter(
        Exhibition.continent.in_(db_values), Exhibition.is_active == 1
    )
    query, category, food_only, keyword = _apply_filters(base_query)
    expos = query.order_by(Exhibition.start_date.asc()).all()
    categories = _categories_for(base_query)

    return render_template(
        "dashboard/expo_list.html",
        title=continent,
        list_url=("exhibition.expo_list", {"continent": continent}),
        continent=continent,
        expos=expos,
        categories=categories,
        selected_category=category,
        food_only=food_only,
        keyword=keyword,
    )


@bp.route("/country/<country>")
@login_required
def expo_list_by_country(country):
    base_query = Exhibition.query.filter(
        Exhibition.country_ko == country, Exhibition.is_active == 1
    )
    query, category, food_only, keyword = _apply_filters(base_query)
    expos = query.order_by(Exhibition.start_date.asc()).all()
    categories = _categories_for(base_query)

    return render_template(
        "dashboard/expo_list.html",
        title=country,
        list_url=("exhibition.expo_list_by_country", {"country": country}),
        continent="",
        expos=expos,
        categories=categories,
        selected_category=category,
        food_only=food_only,
        keyword=keyword,
    )


def _split_paragraphs(text):
    """긴 소개 문장을 2~3문장 단위로 끊어 문단을 나눔."""
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    paragraphs = []
    chunk = []
    for sentence in sentences:
        chunk.append(sentence)
        if len(chunk) >= 3:
            paragraphs.append(" ".join(chunk))
            chunk = []
    if chunk:
        paragraphs.append(" ".join(chunk))
    return paragraphs


@bp.route("/detail/<int:expo_id>")
@login_required
def detail(expo_id):
    expo = Exhibition.query.get_or_404(expo_id)
    intro_paragraphs = _split_paragraphs(expo.intro_ko) or _split_paragraphs(expo.intro)
    return render_template("exhibition/detail.html", expo=expo, intro_paragraphs=intro_paragraphs)

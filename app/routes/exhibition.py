import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Exhibition, NtmMeasure, Product
from app.routes.dashboard import CONTINENT_DB_VALUES
from app.services.hscode import build_hscode_context, resolve_country_iso
from app.services.trains_client import fetch_regulations, to_ntm_measure_rows

bp = Blueprint("exhibition", __name__, url_prefix="/exhibitions")


def _apply_filters(query):
    keyword_tag = request.args.get("keyword_tag", "")
    food_only = request.args.get("food_only", "")
    search = request.args.get("search", "").strip()

    if keyword_tag:
        query = query.filter(Exhibition.keywords.ilike(f"%{keyword_tag}%"))
    if food_only == "1":
        query = query.filter(Exhibition.food_yn == 1)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (Exhibition.name.ilike(like))
            | (Exhibition.country_ko.ilike(like))
            | (Exhibition.city.ilike(like))
        )
    return query, keyword_tag, food_only, search


def _keyword_tags_for(base_query, limit=15):
    seen = {}
    for row in base_query.with_entities(Exhibition.keywords).all():
        if not row[0]:
            continue
        for kw in row[0].split(","):
            kw = kw.strip()
            if kw:
                seen[kw] = seen.get(kw, 0) + 1
    return [kw for kw, _ in sorted(seen.items(), key=lambda x: -x[1])[:limit]]


def _build_list_context(base_query, title, list_endpoint, list_kwargs, continent):
    query, keyword_tag, food_only, search = _apply_filters(base_query)
    expos = query.order_by(Exhibition.start_date.asc()).all()
    keyword_tags = _keyword_tags_for(base_query)

    return {
        "title": title,
        "list_url": (list_endpoint, list_kwargs),
        "continent": continent,
        "expos": expos,
        "keyword_tags": keyword_tags,
        "selected_keyword_tag": keyword_tag,
        "food_only": food_only,
        "search": search,
    }


@bp.route("/<continent>")
@login_required
def expo_list(continent):
    db_values = CONTINENT_DB_VALUES.get(continent)
    if db_values is None:
        abort(404)

    base_query = Exhibition.query.filter(
        Exhibition.continent.in_(db_values), Exhibition.is_active == 1
    )
    ctx = _build_list_context(
        base_query, continent, "exhibition.expo_list", {"continent": continent}, continent
    )
    return render_template("dashboard/expo_list.html", **ctx)


@bp.route("/country/<country>")
@login_required
def expo_list_by_country(country):
    base_query = Exhibition.query.filter(
        Exhibition.country_ko == country, Exhibition.is_active == 1
    )
    ctx = _build_list_context(
        base_query, country, "exhibition.expo_list_by_country", {"country": country}, ""
    )
    return render_template("dashboard/expo_list.html", **ctx)


@bp.route("/partial/<continent>")
@login_required
def expo_list_partial(continent):
    db_values = CONTINENT_DB_VALUES.get(continent)
    if db_values is None:
        abort(404)

    base_query = Exhibition.query.filter(
        Exhibition.continent.in_(db_values), Exhibition.is_active == 1
    )
    ctx = _build_list_context(
        base_query, continent, "exhibition.expo_list_partial", {"continent": continent}, continent
    )
    return render_template("dashboard/_expo_list_partial.html", **ctx)


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

    # 시장 개요·트렌드 조사·HS코드 탭은 체크된 제품 + HS코드가 있어야 연결됨
    linked_products = Product.query.filter(
        Product.user_id == current_user.id,
        Product.is_checked == True,  # noqa: E712
        Product.hs_code.isnot(None),
        Product.hs_code != "",
    ).all()
    has_linked_product = len(linked_products) > 0

    hscode_ctx = build_hscode_context(expo, linked_products) if has_linked_product else None

    return render_template(
        "exhibition/detail.html",
        expo=expo,
        intro_paragraphs=intro_paragraphs,
        has_linked_product=has_linked_product,
        hscode_ctx=hscode_ctx,
    )


@bp.route("/detail/<int:expo_id>/sync-ntm", methods=["POST"])
@login_required
def sync_ntm(expo_id):
    """이 박람회 국가 하나에 대해 UNCTAD TRAINS Online을 그 자리에서 호출해
    캐시(NtmMeasure)를 채운다. TRAINS Online의 export-regulations는 실제로는
    HS코드로 필터링을 안 하고 국가 전체 규정 목록을 반환하기 때문에, HS코드별로
    나눠 부를 필요 없이 국가당 한 번만 호출한다 (app/services/hscode.py의
    get_country_regulations가 이후 식품 관련도로 걸러서 보여줌)."""
    expo = Exhibition.query.get_or_404(expo_id)
    country_iso = resolve_country_iso(expo.country)

    if not country_iso:
        flash(
            f"'{expo.country}' 국가명을 인식하지 못했습니다. "
            f"pip install pycountry 설치 여부를 확인해주세요.",
            "danger",
        )
        return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

    try:
        regulations = fetch_regulations(country_iso, [])
        rows = to_ntm_measure_rows(country_iso, "ALL", regulations)
        NtmMeasure.query.filter_by(reporter=country_iso, product="ALL").delete()
        for row in rows:
            db.session.add(NtmMeasure(**row))
        db.session.commit()
        flash(f"UNCTAD TRAINS에서 {len(rows)}건의 무역 규정 정보를 가져왔습니다.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"TRAINS 조회 중 오류가 발생했습니다: {e}", "danger")

    return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

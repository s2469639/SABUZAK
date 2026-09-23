import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Exhibition, NtmMeasure, Product
from app.routes.dashboard import CONTINENT_DB_VALUES
from app.services.hscode import build_hscode_context, resolve_country_iso
from app.services.trains_client import (
    fetch_regulations_for_country,
    to_ntm_measure_rows,
    top_relevant_regulations,
)

bp = Blueprint("exhibition", __name__, url_prefix="/exhibitions")

# scripts/crawl/tradefairdates_scraper.py의 UNKNOWN_DATE와 같은 값. 날짜 전체가
# 미상인 박람회는 start_date/end_date가 이 값으로 들어있다 (오름차순 정렬 시 항상
# 맨 뒤로 가도록 일부러 큰 값을 씀 -> "오래된순"으로 뒤집으면 반대로 맨 앞에
# "9999.99.99"로 튀어나와서, 그 경우엔 아예 목록에서 뺀다).
UNKNOWN_DATE = 99999999


def _ymd_int(value):
    """<input type="date"> 값("YYYY-MM-DD")을 start_date/end_date와 비교 가능한
    YYYYMMDD 정수로 변환. 비어있거나 형식이 이상하면 None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value.replace("-", ""))
    except ValueError:
        return None


def _apply_filters(query):
    keyword_tag = request.args.get("keyword_tag", "")
    food_only = request.args.get("food_only", "")
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

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

    date_from_int = _ymd_int(date_from)
    date_to_int = _ymd_int(date_to)
    if date_from_int or date_to_int:
        # 날짜 미상(UNKNOWN_DATE) 항목은 기간 비교 자체가 의미 없으니 범위 필터를
        # 걸 때는 아예 대상에서 뺀다 (박람회 기간이 요청 기간과 "겹치는지"로 판단:
        # 시작일이 조회 종료일 이전이면서, 종료일이 조회 시작일 이후인 것).
        query = query.filter(Exhibition.start_date != UNKNOWN_DATE)
        if date_from_int:
            query = query.filter(Exhibition.end_date >= date_from_int)
        if date_to_int:
            query = query.filter(Exhibition.start_date <= date_to_int)

    return query, keyword_tag, food_only, search, date_from, date_to


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
    query, keyword_tag, food_only, search, date_from, date_to = _apply_filters(base_query)
    sort = request.args.get("sort", "asc")
    if sort == "desc":
        query = query.filter(Exhibition.start_date != UNKNOWN_DATE)
        order = Exhibition.start_date.desc()
    else:
        order = Exhibition.start_date.asc()
    expos = query.order_by(order).all()
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
        "sort": sort,
        "date_from": date_from,
        "date_to": date_to,
    }


@bp.route("/<continent>")
@login_required
def expo_list(continent):
    db_values = CONTINENT_DB_VALUES.get(continent)
    if db_values is None:
        abort(404)

    dup_ids = Exhibition.duplicate_ids()
    base_query = Exhibition.query.filter(
        Exhibition.continent.in_(db_values),
        Exhibition.is_active == 1,
        Exhibition.id.notin_(dup_ids),
    )
    ctx = _build_list_context(
        base_query, continent, "exhibition.expo_list", {"continent": continent}, continent
    )
    return render_template("dashboard/expo_list.html", **ctx)


@bp.route("/country/<country>")
@login_required
def expo_list_by_country(country):
    dup_ids = Exhibition.duplicate_ids()
    base_query = Exhibition.query.filter(
        Exhibition.country_ko == country,
        Exhibition.is_active == 1,
        Exhibition.id.notin_(dup_ids),
    )
    ctx = _build_list_context(
        base_query, country, "exhibition.expo_list_by_country", {"country": country}, ""
    )
    return render_template("dashboard/expo_list.html", **ctx)


@bp.route("/partial/all")
@login_required
def expo_list_partial_all():
    dup_ids = Exhibition.duplicate_ids()
    base_query = Exhibition.query.filter(
        Exhibition.is_active == 1, Exhibition.id.notin_(dup_ids)
    )
    ctx = _build_list_context(base_query, "해외", "exhibition.expo_list_partial_all", {}, "")
    return render_template("dashboard/_expo_list_partial.html", **ctx)


@bp.route("/partial/<continent>")
@login_required
def expo_list_partial(continent):
    db_values = CONTINENT_DB_VALUES.get(continent)
    if db_values is None:
        abort(404)

    dup_ids = Exhibition.duplicate_ids()
    base_query = Exhibition.query.filter(
        Exhibition.continent.in_(db_values),
        Exhibition.is_active == 1,
        Exhibition.id.notin_(dup_ids),
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
    캐시(NtmMeasure)를 채운다. TRAINS의 새 API(denormalisedMeasures)는 국가를
    UNCTAD 내부 숫자 ID로만 지정할 수 있어서, 전세계를 한 번에 조회한 뒤
    응답에 포함된 국가명 문자열로 이 박람회 국가에 해당하는 것만 걸러낸다
    (app/services/trains_client.fetch_regulations_for_country).
    이후 app/services/hscode.py의 get_country_regulations가 식품 관련도로
    한 번 더 걸러서 보여준다."""
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
        regulations = fetch_regulations_for_country(country_iso)
        top6 = top_relevant_regulations(regulations, limit=6)
        rows = to_ntm_measure_rows(country_iso, "ALL", top6, summarize=True)
        NtmMeasure.query.filter_by(reporter=country_iso, product="ALL").delete()
        for row in rows:
            db.session.add(NtmMeasure(**row))
        db.session.commit()
        flash(f"UNCTAD TRAINS에서 가장 관련도 높은 {len(rows)}건을 한국어 요약으로 가져왔습니다.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"TRAINS 조회 중 오류가 발생했습니다: {e}", "danger")

    return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Exhibition, NtmMeasure, Product
from app.routes.dashboard import CONTINENT_DB_VALUES
from app.services.hscode import build_hscode_context, get_m49_code, resolve_country_iso
from app.services.macmap_client import fetch_ntm_rows, make_session

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
    """이 박람회 국가 하나에 대해서만, 지금 등록된 제품 HS코드 기준으로 macmap을
    그 자리에서 호출해 캐시(NtmMeasure)를 채운다. scripts/sync_ntm_cache.py를
    전체 국가로 돌리는 대신, 필요한 조합 하나만 버튼으로 즉시 채우는 용도."""
    expo = Exhibition.query.get_or_404(expo_id)
    country_iso = resolve_country_iso(expo.country)

    if not country_iso:
        flash(
            f"'{expo.country}' 국가명을 인식하지 못했습니다. "
            f"pip install pycountry 설치 여부를 확인해주세요.",
            "danger",
        )
        return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

    m49 = get_m49_code(country_iso)
    if not m49:
        flash(f"{expo.country_ko or expo.country}({country_iso})의 M49 코드를 찾지 못했습니다.", "danger")
        return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

    products = Product.query.filter(
        Product.user_id == current_user.id,
        Product.is_checked == True,  # noqa: E712
        Product.hs_code.isnot(None),
        Product.hs_code != "",
    ).all()
    hs6_list = sorted({p.hs_code.replace(".", "")[:6] for p in products})

    if not hs6_list:
        flash("체크된 제품(HS코드 포함)이 없습니다. 먼저 마이페이지에서 제품을 등록해주세요.", "danger")
        return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

    try:
        session = make_session()
        total = 0
        for hs6 in hs6_list:
            rows = fetch_ntm_rows(session, m49, hs6)
            NtmMeasure.query.filter_by(reporter=m49, product=hs6).delete()
            for row in rows:
                db.session.add(NtmMeasure(**row))
            total += len(rows)
        db.session.commit()
        flash(f"macmap에서 {total}건의 비관세장벽 정보를 가져왔습니다.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"macmap 조회 중 오류가 발생했습니다: {e}", "danger")

    return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

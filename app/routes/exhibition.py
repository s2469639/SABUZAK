import math
import re
from collections import Counter

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Exhibition, NtmMeasure, Product
from app.routes.dashboard import CONTINENT_DB_VALUES
from app.services.hscode import build_hscode_context, resolve_country_iso
from app.services import un_comtrade
from app.services.exchange import get_exchange_info
from app.services.wto_client import get_country_tariff_averages
from app.services import market_trend
from app.services.trains_client import (
    fetch_regulations_for_country,
    no_match_row,
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


def _centered_axis(values, center, floor=None, pad_ratio=0.15, edge=8.0):
    """평균(center)이 항상 축의 정중앙(50%)에 오도록 하는 축을 만든다
    (un_v6/app.py 그대로 이식). 평균보다 작은 쪽은 0~50%, 큰 쪽은 50~100%
    구간에 각각 따로 맞춰 그리므로 네 사분면의 면적이 항상 똑같다."""
    low_span = max([center - v for v in values] + [0])
    high_span = max([v - center for v in values] + [0])
    fallback = max(low_span, high_span) or abs(center) * 0.5 or 1
    low_span = (low_span or fallback) * (1 + pad_ratio)
    high_span = (high_span or fallback) * (1 + pad_ratio)

    low = center - low_span
    if floor is not None and low < floor <= center:
        low = floor
    high = center + high_span

    scale = (100 - 2 * edge) / 100

    def raw_pct(v):
        if v <= center:
            if center == low:
                return 50.0
            return (v - low) / (center - low) * 50
        return 50 + (v - center) / (high - center) * 50

    def to_pct(v):
        return edge + raw_pct(v) * scale

    ticks = []
    for raw, value in ((0.0, low), (25.0, (low + center) / 2), (50.0, center),
                       (75.0, (center + high) / 2), (100.0, high)):
        ticks.append((edge + raw * scale, value))
    return to_pct, ticks


def _with_scatter_positions(candidates, thresholds):
    """산점도 좌표(0~100%)를 계산한다 (un_v6/app.py 그대로 이식). 평균 기준선은
    항상 정중앙(50%, 50%)이라 사분면 네 칸의 크기가 같다."""
    if not candidates:
        return [], 50, 50, [], []

    avg_cagr = thresholds["avg_cagr_pct"]
    avg_share = thresholds.get("share_threshold_pct", thresholds["avg_korea_share_pct"])
    cagrs = [c["cagr_pct"] for c in candidates]
    shares = [c["korea_share_pct"] for c in candidates]

    x_of, x_raw_ticks = _centered_axis(cagrs, avg_cagr)
    share_floor = 0 if min(shares) >= 0 else None
    y_of, y_raw_ticks = _centered_axis(shares, avg_share, floor=share_floor)

    out = []
    for c in candidates:
        point = dict(c)
        point["x_pct"] = round(x_of(c["cagr_pct"]), 1)
        point["y_pct"] = round(100 - y_of(c["korea_share_pct"]), 1)
        out.append(point)

    x_ticks = [{"pct": pct, "value": round(v, 1)} for pct, v in x_raw_ticks]
    y_ticks = [{"pct": 100 - pct, "value": round(v, 2)} for pct, v in y_raw_ticks]
    return out, 50, 50, x_ticks, y_ticks


_QUADRANT_DEFAULTS = {
    "tr": "집중 공략",
    "tl": "현상 유지/수확",
    "br": "경쟁력 강화 필요",
    "bl": "우선순위 낮음",
}
_QUADRANT_CSS = {
    "집중 공략": "q-focus",
    "현상 유지/수확": "q-harvest",
    "경쟁력 강화 필요": "q-strengthen",
    "우선순위 낮음": "q-low",
}


def _quadrant_labels(candidates, thresholds):
    """사분면 라벨을 un_comtrade.py가 실제로 매긴 사분면(c["quadrant"])에 맞춘다
    (un_v6/app.py 그대로 이식)."""
    avg_cagr = thresholds["avg_cagr_pct"]
    avg_share = thresholds.get("share_threshold_pct", thresholds["avg_korea_share_pct"])
    votes = {pos: Counter() for pos in _QUADRANT_DEFAULTS}
    for c in candidates:
        if not c.get("quadrant"):
            continue
        vert = "t" if c["korea_share_pct"] >= avg_share else "b"
        horiz = "r" if c["cagr_pct"] >= avg_cagr else "l"
        votes[vert + horiz][c["quadrant"]] += 1

    labels = {}
    for pos, counter in votes.items():
        if counter:
            labels[pos] = counter.most_common(1)[0][0]
    if len(set(labels.values())) < len(labels):
        labels = {}
    used = set(labels.values())
    unused = [n for n in _QUADRANT_DEFAULTS.values() if n not in used]
    for pos, default in _QUADRANT_DEFAULTS.items():
        if pos in labels:
            continue
        if default not in used:
            labels[pos] = default
        elif unused:
            labels[pos] = unused.pop(0)
        else:
            labels[pos] = default
        used.add(labels[pos])
        if labels[pos] in unused:
            unused.remove(labels[pos])
    return labels


def build_matrix(candidates, thresholds, min_radius=10, max_radius=34):
    """③ 유망시장 매트릭스(통합 버블차트) 데이터를 만든다 (un_v6/app.py의
    _build_matrix 그대로 이식). X축 = 수입시장 성장률(CAGR), Y축 = 한국 점유율,
    버블 크기 = 수입금액 (넓이가 금액에 비례하도록 sqrt 스케일)."""
    empty = {
        "points": [], "threshold_x_pct": 50, "threshold_y_pct": 50,
        "x_ticks": [], "y_ticks": [], "quadrants": [],
    }
    if not candidates:
        return empty

    points, tx, ty, x_ticks, y_ticks = _with_scatter_positions(candidates, thresholds)

    values = [p["total_import_usd"] for p in points if p.get("total_import_usd")]
    v_min = min(values) if values else 0
    v_max = max(values) if values else 0
    for p in points:
        value = p.get("total_import_usd")
        if not value:
            t = 0.0
        elif v_max > v_min:
            t = math.sqrt(value - v_min) / math.sqrt(v_max - v_min)
        else:
            t = 1.0
        p["bubble_radius"] = round(min_radius + (max_radius - min_radius) * t, 1)

    labels = _quadrant_labels(candidates, thresholds)
    quadrants = []
    for pos in ("tl", "tr", "bl", "br"):
        name = labels[pos]
        quadrants.append({"pos": pos, "label": name, "css": _QUADRANT_CSS.get(name, "q-low")})

    return {
        "points": points, "threshold_x_pct": tx, "threshold_y_pct": ty,
        "x_ticks": x_ticks, "y_ticks": y_ticks, "quadrants": quadrants,
    }


_LINE_COLORS = ["#1a8cff", "#e8710a", "#7c3aed", "#d01884", "#00838f", "#8d6e63", "#f9ab00", "#5c6bc0"]
_KOREA_LINE_COLOR = "#20b26b"  # 한국은 트라이빅처럼 항상 초록색


def _is_korea_label(label):
    text = str(label).lower()
    return "korea" in text or text in ("kor", "한국", "대한민국")


def _svg_line_series(share_trend, width=560, height=180, pad_l=44, pad_r=16, pad_t=16, pad_b=26):
    """② 주요국 세계시장 점유율 추이 SVG 좌표 계산 (un_v6/app.py 그대로 이식)."""
    years = share_trend.get("years", [])
    series = share_trend.get("series", {})
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(years)
    base = {
        "years": years, "width": width, "height": height,
        "plot_w": plot_w, "plot_h": plot_h, "pad_l": pad_l, "pad_t": pad_t, "pad_b": pad_b,
    }
    if not years or not series:
        base.update({"lines": [], "x_labels": [], "y_max": 1})
        return base

    def x_at(j):
        return pad_l + plot_w * j / (n - 1) if n > 1 else pad_l + plot_w / 2

    all_vals = [p["share_pct"] for pts in series.values() for p in pts if p["share_pct"] is not None]
    y_max = (max(all_vals) * 1.15) if all_vals else 1
    y_max = y_max or 1

    lines = []
    color_idx = 0
    for label, pts in series.items():
        if _is_korea_label(label):
            color = _KOREA_LINE_COLOR
        else:
            color = _LINE_COLORS[color_idx % len(_LINE_COLORS)]
            color_idx += 1
        coords = []
        for j, p in enumerate(pts):
            if p["share_pct"] is None:
                continue
            x = x_at(j)
            y = pad_t + plot_h - (p["share_pct"] / y_max * plot_h)
            coords.append({"x": round(x, 1), "y": round(y, 1), "year": years[j], "share_pct": p["share_pct"]})
        points_str = " ".join(f"{pt['x']},{pt['y']}" for pt in coords)
        lines.append({
            "label": label, "color": color, "is_korea": _is_korea_label(label),
            "points": points_str, "coords": coords,
        })

    x_labels = [{"x": round(x_at(j), 1), "year": y} for j, y in enumerate(years)]
    base.update({"lines": lines, "x_labels": x_labels, "y_max": round(y_max, 1)})
    return base


def _hs6(hs_code):
    """UN Comtrade는 국제 공통 6자리 HS코드만 받는다. 등록된 제품의
    hs_code(예: '1905.90.1050' 또는 '1905.90')에서 숫자만 뽑아 앞 6자리를
    쓴다. 6자리가 안 되면(코드가 너무 짧으면) None."""
    digits = re.sub(r"\D", "", hs_code or "")
    return digits[:6] if len(digits) >= 6 else None


def _apply_filters(query):
    keyword_tag = request.args.get("keyword_tag", "")
    food_only = request.args.get("food_only", "")
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    scale_list = [s for s in request.args.getlist("scale") if s in ("대", "중", "소")]
    audience_list = [a for a in request.args.getlist("audience_type") if a in ("B2B", "B2C")]

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
    if scale_list:
        query = query.filter(Exhibition.scale.in_(scale_list))
    if audience_list:
        # audience_type이 "B2B/B2C"(둘 다 해당)로 저장된 행은 B2B만 골라도,
        # B2C만 골라도 나와야 하니 부분일치(LIKE)로 판정한다.
        query = query.filter(
            db.or_(*[Exhibition.audience_type.ilike(f"%{a}%") for a in audience_list])
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

    return query, keyword_tag, food_only, search, date_from, date_to, scale_list, audience_list


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
    query, keyword_tag, food_only, search, date_from, date_to, scale_list, audience_list = (
        _apply_filters(base_query)
    )
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
        "selected_scales": scale_list,
        "selected_audience_types": audience_list,
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


def _build_market_rows(expo, linked_products):
    """시장 개요 탭에 쓸 제품별 UN Comtrade 조사 현황. 네트워크 호출 없이
    캐시만 읽는다 (실제 조회는 "조사하기" 버튼 -> market_research 라우트가
    담당 - UNCTAD TRAINS 탭과 동일한 패턴으로, 페이지 열 때마다 외부 API를
    부르면 느리고 API 한도도 금방 닳기 때문)."""
    rows = []
    for product in linked_products:
        hs6 = _hs6(product.hs_code)
        cached = un_comtrade.get_cached_market_research(hs6, expo.country) if hs6 else None
        item_desc_ko = (
            un_comtrade.translate_item_desc(cached.get("official_item_desc"))
            if cached and cached.get("official_item_desc") else None
        )
        rows.append({"product": product, "hs6": hs6, "result": cached, "item_desc_ko": item_desc_ko})
    return rows


def _exhibition_month(expo):
    """start_date(YYYYMMDD int) -> 'N월' (없으면 기본값 10월)."""
    s = str(expo.start_date) if expo.start_date else ""
    if len(s) == 8 and s.isdigit():
        return f"{int(s[4:6])}월"
    return "10월"


def _default_trend_specs(expo, product):
    """제품관리(마이페이지)에 등록해둔 목표가/인증/식감 정보를 그대로 쓴다
    (예전엔 이 탭에서 매번 다시 입력받았는데, 어차피 제품 고유 정보라
    마이페이지 제품 등록/수정 폼으로 옮겼다)."""
    return {
        "product_name": product.name,
        "country": expo.country_ko or expo.country or "",
        "brand": product.brand or "",
        "product_form": product.product_form or "",
        "ingredients": product.ingredients or "",
        "target_price": product.target_price or "",
        "certifications": product.certifications or "",
        "strengths": product.strengths or "",
        "exhibition_month": _exhibition_month(expo),
    }


def _build_trend_rows(expo, linked_products):
    """트렌드 조사 탭에 쓸 제품별 시장·트렌드 분석 현황. 네트워크 호출 없이
    캐시만 읽는다 (실제 분석은 "지금 분석하기" 버튼 -> trend_research 라우트가
    담당 - 시장 개요 탭과 동일한 패턴)."""
    rows = []
    for product in linked_products:
        specs = _default_trend_specs(expo, product)
        cached = market_trend.get_cached_analysis(specs)
        rows.append({"product": product, "specs": specs, "result": cached})
    return rows


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
    market_rows = _build_market_rows(expo, linked_products) if has_linked_product else []
    trend_rows = _build_trend_rows(expo, linked_products) if has_linked_product else []
    exchange_info = get_exchange_info(expo.country)
    wto_tariff_info = (
        get_country_tariff_averages(hscode_ctx["country_iso"]) if hscode_ctx else None
    )

    return render_template(
        "exhibition/detail.html",
        expo=expo,
        intro_paragraphs=intro_paragraphs,
        has_linked_product=has_linked_product,
        hscode_ctx=hscode_ctx,
        market_rows=market_rows,
        trend_rows=trend_rows,
        exchange_info=exchange_info,
        wto_tariff_info=wto_tariff_info,
    )


@bp.route("/detail/<int:expo_id>/trend-research/<int:product_id>", methods=["POST"])
@login_required
def trend_research(expo_id, product_id):
    """market_trend_analysis/ 로직(구글 트렌드 + 리드타임 + 경쟁사 + 뉴스)을
    이 제품 + 박람회 국가 기준으로 실행한다 (캐시 있으면 캐시, "새로 분석"
    체크 시 강제 재실행)."""
    expo = Exhibition.query.get_or_404(expo_id)
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()

    specs = _default_trend_specs(expo, product)
    specs["exhibition_month"] = request.form.get("exhibition_month", "").strip() or specs["exhibition_month"]
    force = bool(request.form.get("force"))

    try:
        payload = market_trend.run_analysis(specs, force=force)
        if payload.get("news", {}).get("is_error"):
            flash(
                f"뉴스/트렌드 API 키가 없거나 오류가 있어 분석을 저장하지 못했습니다: "
                f"{payload['news'].get('summary')}",
                "danger",
            )
        else:
            flash(f"{product.name} · {specs['country']} 시장·트렌드 분석을 가져왔습니다.", "success")
    except Exception as e:
        flash(f"시장·트렌드 분석 중 오류가 발생했습니다: {e}", "danger")

    return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#trend")


@bp.route("/detail/<int:expo_id>/market-research/<int:product_id>", methods=["POST"])
@login_required
def market_research(expo_id, product_id):
    """이 제품 HS코드 + 박람회 국가로 UN Comtrade 시장조사를 그 자리에서
    실행한다 (캐시 있으면 캐시, 없거나 "새로고침" 체크 시 실제 API 호출)."""
    expo = Exhibition.query.get_or_404(expo_id)
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    hs6 = _hs6(product.hs_code)

    if not hs6:
        flash(f"'{product.hs_code}'는 UN Comtrade 조회에 필요한 6자리 HS코드로 변환할 수 없습니다.", "danger")
        return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#market")

    force = bool(request.form.get("force"))
    try:
        un_comtrade.get_market_research(hs6, expo.country, force=force)
        flash(f"{product.name}(HS {hs6}) 시장조사를 가져왔습니다.", "success")
    except Exception as e:
        flash(f"UN Comtrade 조사 중 오류가 발생했습니다: {e}", "danger")

    return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#market")


@bp.route("/market-matrix", methods=["GET", "POST"])
@login_required
def market_matrix():
    """세계시장 현황(①②) + 유망시장 매트릭스(③) + 후보국별 상세(④) + AI 분석(⑤)
    을 한 화면에서 보여준다 (un_v6/app.py index()·un_comtrade_dashboard.html
    그대로 이식). 특정 박람회에 종속되지 않고, HS코드 하나로 전세계 후보국을
    비교한다 (마이페이지 "내 제품 관리"의 "상세보기" 버튼이 여기로 연결됨)."""
    ctx = {
        "result": None, "overview": None, "matrix_error": None, "matrix": None,
        "import_line": None, "export_line": None,
        "hscode": re.sub(r"\D", "", request.args.get("hscode", "")),
        "candidates_raw": "", "top_n": 10, "force": False, "item_desc_ko": None,
    }

    # GET + hscode(예: 마이페이지 제품 "상세보기" 버튼)로 들어와도 바로
    # 분석 결과가 보이도록, POST 폼 제출과 동일하게 처리한다.
    should_run = request.method == "POST" or bool(request.args.get("hscode"))
    if should_run:
        values = request.form if request.method == "POST" else request.args
        hscode = re.sub(r"\D", "", values.get("hscode", ""))
        candidates_raw = values.get("candidates", "").strip()
        top_n = max(0, min(int(values.get("top_n") or 10), 20))
        force = bool(values.get("force"))
        candidate_list = [c.strip() for c in re.split(r"[,，;、]", candidates_raw) if c.strip()]
        ctx.update(hscode=hscode, candidates_raw=candidates_raw, top_n=top_n, force=force)

        if not re.fullmatch(r"\d{6}", hscode):
            ctx["matrix_error"] = "HS코드는 6자리 숫자로 입력해주세요 (예: 1905.90)."
            return render_template("exhibition/market_matrix.html", **ctx)

        result = None
        try:
            result = un_comtrade.get_multi_country_comparison(
                hscode, candidate_list or None, top_n=top_n, force=force,
            )
        except ValueError as e:
            ctx["matrix_error"] = str(e)
        except Exception as e:
            ctx["matrix_error"] = f"비교 분석 중 오류가 발생했습니다: {e}"

        ctx["result"] = result
        if result:
            ctx["matrix"] = build_matrix(result["candidates"], result["thresholds"])
            if result.get("official_item_desc"):
                ctx["item_desc_ko"] = un_comtrade.translate_item_desc(result["official_item_desc"])
            try:
                overview = un_comtrade.get_market_overview(hscode, top_n=top_n or 10, force=force)
                ctx["overview"] = overview
                ctx["import_line"] = _svg_line_series(overview["import_share_trend"])
                ctx["export_line"] = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                ctx["overview"] = {"unavailable_reason": str(e)}

    return render_template("exhibition/market_matrix.html", **ctx)


@bp.route("/detail/<int:expo_id>/sync-ntm/<int:product_id>", methods=["POST"])
@login_required
def sync_ntm(expo_id, product_id):
    """이 박람회 국가 + 이 제품(product_id) 조합에 대해 UNCTAD TRAINS Online을
    그 자리에서 호출해 캐시(NtmMeasure)를 채운다. TRAINS API
    (denormalisedRegulations)는 imposingCountries에 ISO3 코드를, products에
    실제 HS코드를 그대로 받기 때문에 이 나라+제품만 콕 집어서 바로 조회한다
    (app/services/trains_client.fetch_regulations_for_country). 이후
    app/services/hscode.py의 get_country_regulations가 이 조합으로 캐시된
    것만 걸러서 보여준다."""
    expo = Exhibition.query.get_or_404(expo_id)
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    country_iso = resolve_country_iso(expo.country)

    if not country_iso:
        flash(
            f"'{expo.country}' 국가명을 인식하지 못했습니다. "
            f"pip install pycountry 설치 여부를 확인해주세요.",
            "danger",
        )
        return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

    try:
        regulations = fetch_regulations_for_country(country_iso, product.hs_code)
        top6 = top_relevant_regulations(regulations, product.hs_code, product_name=product.name, limit=6)
        rows = to_ntm_measure_rows(country_iso, product.hs_code, top6, summarize=True)
        NtmMeasure.query.filter_by(reporter=country_iso, product=product.hs_code).delete()
        if rows:
            for row in rows:
                db.session.add(NtmMeasure(**row))
        else:
            # 관련 규정이 진짜 0건이어도 "조회는 했다"는 걸 표시해둬야, 다음에
            # 페이지 들어왔을 때 "아직 한 번도 안 조회함"으로 착각해서 정적
            # 예시 데이터로 잘못 폴백하지 않는다.
            db.session.add(NtmMeasure(**no_match_row(country_iso, product.hs_code)))
        db.session.commit()
        flash(f"'{product.name}' 관련 식품·농산물 수입규정 참고자료 {len(rows)}건을 한국어 요약으로 가져왔습니다.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"TRAINS 조회 중 오류가 발생했습니다: {e}", "danger")

    return redirect(url_for("exhibition.detail", expo_id=expo_id) + "#hscode")

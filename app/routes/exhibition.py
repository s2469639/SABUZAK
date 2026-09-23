import math
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Exhibition, NtmMeasure, Product
from app.routes.dashboard import CONTINENT_DB_VALUES
from app.services.hscode import build_hscode_context, resolve_country_iso
from app.services import un_comtrade
from app.services.exchange import get_exchange_info
from app.services import market_trend
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


def _with_scatter_positions(candidates, thresholds):
    """매트릭스 산점도 화면에 찍을 x/y 좌표(0~100%)를 계산한다
    (un_v6/app.py 그대로 이식)."""
    if not candidates:
        return [], 50, 50
    cagrs = [c["cagr_pct"] for c in candidates]
    shares = [c["korea_share_pct"] for c in candidates]
    x_min, x_max = min(cagrs + [thresholds["avg_cagr_pct"]]), max(cagrs + [thresholds["avg_cagr_pct"]])
    y_min, y_max = min(shares + [thresholds["avg_korea_share_pct"]]), max(shares + [thresholds["avg_korea_share_pct"]])
    x_pad = (x_max - x_min) * 0.15 or 1
    y_pad = (y_max - y_min) * 0.15 or 1
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    out = []
    for c in candidates:
        x_pct = (c["cagr_pct"] - x_min) / (x_max - x_min) * 100
        y_pct = (c["korea_share_pct"] - y_min) / (y_max - y_min) * 100
        out.append({**c, "x_pct": round(x_pct, 1), "y_pct": round(100 - y_pct, 1)})
    threshold_x_pct = (thresholds["avg_cagr_pct"] - x_min) / (x_max - x_min) * 100
    threshold_y_pct = 100 - (thresholds["avg_korea_share_pct"] - y_min) / (y_max - y_min) * 100
    return out, round(threshold_x_pct, 1), round(threshold_y_pct, 1)


def _with_bubble_positions(candidates, min_radius=11, max_radius=38):
    """"유망시장 순위" 버블차트 좌표 (un_v6/app.py 그대로 이식). 버블 크기는
    넓이가 값에 비례하도록 제곱근(sqrt)으로 스케일링한다."""
    eligible = [
        c for c in candidates
        if c.get("total_import_usd") and c.get("supplier_country_count") is not None and c.get("import_rank")
    ]
    if not eligible:
        return []

    values = [c["total_import_usd"] for c in eligible]
    counts = [c["supplier_country_count"] for c in eligible]
    ranks = [c["import_rank"] for c in eligible]
    v_min, v_max = min(values), max(values)
    y_min, y_max = min(counts), max(counts)
    x_min, x_max = min(ranks), max(ranks)
    y_pad = (y_max - y_min) * 0.15 or 1
    y_min, y_max = y_min - y_pad, y_max + y_pad

    out = []
    for c in eligible:
        if v_max > v_min:
            t = math.sqrt(c["total_import_usd"] - v_min) / math.sqrt(v_max - v_min)
        else:
            t = 1.0
        radius = round(min_radius + (max_radius - min_radius) * t, 1)
        x_pct = ((c["import_rank"] - x_min) / (x_max - x_min) * 100) if x_max > x_min else 50.0
        y_pct = 100 - ((c["supplier_country_count"] - y_min) / (y_max - y_min) * 100)
        out.append({**c, "bubble_radius": radius, "x_pct": round(x_pct, 1), "y_pct": round(y_pct, 1)})
    return out


_LINE_COLORS = ["#1a73e8", "#e8710a", "#188038", "#d01884", "#7c3aed", "#00838f"]


def _svg_line_series(share_trend, width=560, height=180, pad_l=44, pad_r=16, pad_t=16, pad_b=26):
    """주요국 세계시장 점유율 추이 SVG 좌표 계산 (un_v6/app.py 그대로 이식)."""
    years = share_trend.get("years", [])
    series = share_trend.get("series", {})
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(years)
    if not years or not series or n < 1:
        return {"years": years, "lines": [], "width": width, "height": height,
                "plot_w": plot_w, "plot_h": plot_h, "pad_l": pad_l, "pad_t": pad_t,
                "pad_b": pad_b, "x_labels": [], "y_max": 1}

    all_vals = [p["share_pct"] for pts in series.values() for p in pts if p["share_pct"] is not None]
    y_max = (max(all_vals) * 1.15) if all_vals else 1
    y_max = y_max or 1

    lines = []
    for i, (label, pts) in enumerate(series.items()):
        coords = []
        for j, p in enumerate(pts):
            if p["share_pct"] is None:
                continue
            x = pad_l + (plot_w * j / (n - 1) if n > 1 else plot_w / 2)
            y = pad_t + plot_h - (p["share_pct"] / y_max * plot_h)
            coords.append({"x": round(x, 1), "y": round(y, 1), "year": years[j], "share_pct": p["share_pct"]})
        points_str = " ".join(f"{pt['x']},{pt['y']}" for pt in coords)
        lines.append({"label": label, "color": _LINE_COLORS[i % len(_LINE_COLORS)], "points": points_str, "coords": coords})

    x_labels = [
        {"x": round(pad_l + (plot_w * j / (n - 1) if n > 1 else plot_w / 2), 1), "year": y}
        for j, y in enumerate(years)
    ]
    return {
        "years": years, "lines": lines, "width": width, "height": height,
        "plot_w": plot_w, "plot_h": plot_h, "pad_l": pad_l, "pad_t": pad_t, "pad_b": pad_b,
        "x_labels": x_labels, "y_max": round(y_max, 1),
    }


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


def _build_market_rows(expo, linked_products):
    """시장 개요 탭에 쓸 제품별 UN Comtrade 조사 현황. 네트워크 호출 없이
    캐시만 읽는다 (실제 조회는 "조사하기" 버튼 -> market_research 라우트가
    담당 - UNCTAD TRAINS 탭과 동일한 패턴으로, 페이지 열 때마다 외부 API를
    부르면 느리고 API 한도도 금방 닳기 때문)."""
    rows = []
    for product in linked_products:
        hs6 = _hs6(product.hs_code)
        cached = un_comtrade.get_cached_market_research(hs6, expo.country) if hs6 else None
        rows.append({"product": product, "hs6": hs6, "result": cached})
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

    return render_template(
        "exhibition/detail.html",
        expo=expo,
        intro_paragraphs=intro_paragraphs,
        has_linked_product=has_linked_product,
        hscode_ctx=hscode_ctx,
        market_rows=market_rows,
        trend_rows=trend_rows,
        exchange_info=exchange_info,
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
        market_trend.run_analysis(specs, force=force)
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
    """여러 후보국을 "성장률 x 한국 점유율" 매트릭스로 비교하는 화면
    (un_v6/app.py의 /matrix 화면을 그대로 이식). 특정 박람회에 종속되지
    않고, HS코드 하나로 전세계 후보국을 비교한다."""
    result = None
    overview = None
    error = None
    hscode = request.values.get("hscode", "").strip()
    candidates_raw = ""
    top_n = 10
    scatter = []
    bubbles = []
    import_line = export_line = None
    threshold_x_pct = threshold_y_pct = 50
    force = False

    if request.method == "POST":
        hscode = re.sub(r"\D", "", request.form.get("hscode", ""))
        candidates_raw = request.form.get("candidates", "").strip()
        top_n = int(request.form.get("top_n") or 10)
        force = bool(request.form.get("force"))
        candidate_list = [c.strip() for c in candidates_raw.split(",") if c.strip()] or None
        try:
            result = un_comtrade.get_multi_country_comparison(hscode, candidate_list, top_n=top_n, force=force)
            scatter, threshold_x_pct, threshold_y_pct = _with_scatter_positions(
                result["candidates"], result["thresholds"]
            )
            bubbles = _with_bubble_positions(result["candidates"])
        except ValueError as e:
            error = str(e)
        except Exception as e:
            error = f"조사 중 오류가 발생했습니다: {e}"

        if result:
            try:
                overview = un_comtrade.get_market_overview(hscode, top_n=top_n, force=force)
                import_line = _svg_line_series(overview["import_share_trend"])
                export_line = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                overview = {"unavailable_reason": str(e)}

    return render_template(
        "exhibition/market_matrix.html",
        result=result, overview=overview, error=error,
        scatter=scatter, bubbles=bubbles,
        import_line=import_line, export_line=export_line,
        threshold_x_pct=threshold_x_pct, threshold_y_pct=threshold_y_pct,
        hscode=hscode, candidates_raw=candidates_raw, top_n=top_n, force=force,
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

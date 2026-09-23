#!/usr/bin/env python3
"""독립 실행형 Flask 웹앱. HS코드+국가 입력 -> UN Comtrade 시장조사.

사전 준비:
    pip install -r requirements.txt
    .env 파일에 OPENAI_API_KEY, UN_COMTRADE_SUBSCRIPTION_KEY 설정
    (없으면 실행 시 터미널에서 물어봄)

실행:
    python app.py
    -> 브라우저에서 http://127.0.0.1:5070 접속
"""

import math

from flask import Flask, render_template, request

import customs_trade_stats
from env_setup import ensure_required_keys
from un_comtrade import (
    KOREAN_NAME_TO_ISO3,
    get_market_overview,
    get_market_research,
    get_multi_country_comparison,
)

app = Flask(__name__)


def _country_name_candidates(raw_country, iso3):
    """관세청 API에 넘길 국가명 후보 목록을 만든다.
    1) 사용자가 원래 입력한 문자열(대개 한글/영문 국가명이라 그대로 매칭될 가능성이 높음)
    2) 그 나라의 ISO3와 같은 값을 가리키는 KOREAN_NAME_TO_ISO3의 한글 별칭들
       (사용자가 "VNM"처럼 ISO3 코드로 입력해서 1)이 매칭 안 될 때의 보조 수단)"""
    candidates = [raw_country]
    for name, code in KOREAN_NAME_TO_ISO3.items():
        if code == iso3 and any("가" <= ch <= "힣" for ch in name):
            candidates.append(name)
    return candidates


def _fetch_customs_context(hscode, raw_country, iso3, force=False):
    """관세청 공식 자료는 완전히 선택 기능이다 - 키가 없거나 API 호출이 실패해도
    UN Comtrade 핵심 결과 화면은 그대로 보여줘야 하므로 예외를 여기서 다 삼킨다."""
    try:
        candidates = _country_name_candidates(raw_country, iso3)
        return customs_trade_stats.get_customs_context(hscode, candidates, force=force)
    except Exception as e:
        return {"unavailable_reason": str(e)}


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    # GET 쿼리스트링으로 들어오면(예: 매트릭스 화면 버블에서 "이 국가 상세보기"
    # 클릭) 입력칸만 미리 채워두고, 실제 조사는 사용자가 직접 버튼을 눌러야
    # 실행된다 - 링크 클릭만으로 유료/제한된 API 호출이 바로 나가지 않게 함.
    hscode = request.args.get("hscode", "").strip()
    country = request.args.get("country", "").strip()
    customs = None
    force = False

    if request.method == "POST":
        hscode = request.form.get("hscode", "").strip()
        country = request.form.get("country", "").strip()
        # "새로고침(캐시 무시)" 체크박스 - 예전에 한 번 조사했다가 "데이터
        # 없음"이 나온 조합을 30일 캐시가 그대로 물고 있는 경우가 있어서
        # (실제로 이 문제로 사용자가 헷갈린 적이 있음), 웹 화면에서도 캐시를
        # 무시하고 다시 조사할 수 있게 했다.
        force = bool(request.form.get("force"))
        try:
            result = get_market_research(hscode, country, force=force)
            customs = _fetch_customs_context(hscode, country, result["target_country"], force=force)
        except ValueError as e:
            error = str(e)
        except Exception as e:
            error = f"조사 중 오류가 발생했습니다: {e}"

    return render_template(
        "un_comtrade.html",
        result=result, error=error, customs=customs,
        hscode=hscode, country=country, force=force,
    )


def _with_scatter_positions(candidates, thresholds):
    """산점도 화면에 찍을 x/y 좌표(0~100%)를 계산한다. 값의 최소/최대 범위에
    10% 여백을 둬서 점이 그래프 가장자리에 딱 붙지 않게 한다."""
    if not candidates:
        return []
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
    """트라이빅 "유망시장 순위" 버블차트 좌표를 계산한다.
    X축 = 수입금액 순위(import_rank), Y축 = 공급국 다양성(supplier_country_count),
    버블 크기 = 수입금액(total_import_usd).

    버블 크기는 반지름이 아니라 "넓이"가 값에 비례하도록 제곱근(sqrt)으로
    스케일링한다 - 반지름을 값에 그대로 비례시키면 원의 넓이는 반지름의
    제곱이라 큰 값이 실제 비율보다 훨씬 커 보이는 착시가 생긴다.
    예) 수입액이 4배 차이나면: 반지름 비례라면 4배 차이로 보이지만(착시),
        넓이 비례(sqrt)로 하면 반지름은 2배 차이로만 보여서 실제 크기
        차이를 더 정확하게 눈으로 비교할 수 있다."""
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
    """주요국 세계시장 점유율 추이를 그릴 SVG 좌표(폴리라인 points 문자열)를
    미리 계산해서 템플릿에 넘긴다. 데이터가 없는(None) 연도는 그 점만 건너뛴다."""
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


@app.route("/matrix", methods=["GET", "POST"])
def matrix():
    """여러 후보국을 한 번에 비교하는 종합 화면 (트라이빅 "품목별 유망시장"에 대응):
    세계시장 교역순위, 주요국 점유율 추이, 한국 수출신고 추이, 유망시장
    순위(버블차트), 성장률x한국점유율 매트릭스를 한 페이지에 모은다."""
    result = None
    overview = None
    customs = None
    error = None
    hscode = ""
    candidates_raw = ""
    top_n = 10
    scatter = []
    bubbles = []
    import_line = export_line = None
    annual_customs = []
    threshold_x_pct = threshold_y_pct = 50
    force = False

    if request.method == "POST":
        hscode = request.form.get("hscode", "").strip()
        candidates_raw = request.form.get("candidates", "").strip()
        top_n = int(request.form.get("top_n") or 10)
        force = bool(request.form.get("force"))  # 캐시 무시하고 새로 조사 (단일국가 화면과 동일한 이유)
        candidate_list = [c.strip() for c in candidates_raw.split(",") if c.strip()] or None
        try:
            result = get_multi_country_comparison(hscode, candidate_list, top_n=top_n, force=force)
            scatter, threshold_x_pct, threshold_y_pct = _with_scatter_positions(
                result["candidates"], result["thresholds"]
            )
            bubbles = _with_bubble_positions(result["candidates"])
        except ValueError as e:
            error = str(e)
        except Exception as e:
            error = f"조사 중 오류가 발생했습니다: {e}"

        if result:
            # 세계시장 교역순위/점유율 추이는 완전히 선택 기능이다 - 실패해도
            # 위 매트릭스 결과 화면은 그대로 보여준다 (soft-fail).
            try:
                overview = get_market_overview(hscode, top_n=top_n, force=force)
                import_line = _svg_line_series(overview["import_share_trend"])
                export_line = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                overview = {"unavailable_reason": str(e)}

            # 한국 수출신고 연도별 추이도 마찬가지로 선택 기능 (관세청 키 없어도 무방)
            try:
                customs = customs_trade_stats.get_customs_context(hscode, None, months=60, force=force)
                annual_customs = customs.get("annual_totals", [])
            except Exception as e:
                customs = {"unavailable_reason": str(e)}

    return render_template(
        "un_comtrade_matrix.html",
        result=result, overview=overview, customs=customs, error=error,
        scatter=scatter, bubbles=bubbles, annual_customs=annual_customs,
        import_line=import_line, export_line=export_line,
        threshold_x_pct=threshold_x_pct, threshold_y_pct=threshold_y_pct,
        hscode=hscode, candidates_raw=candidates_raw, top_n=top_n, force=force,
    )


if __name__ == "__main__":
    ensure_required_keys()
    app.run(debug=True, port=5070)

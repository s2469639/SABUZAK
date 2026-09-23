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
import re

from flask import Flask, render_template, request

from env_setup import ensure_required_keys
from un_comtrade import (
    get_market_overview,
    get_market_research,
    get_multi_country_comparison,
)

app = Flask(__name__)


<<<<<<< Updated upstream:un_v6/app.py
def _clean_hscode(raw: str) -> str:
    """입력창에 "1905.90"처럼 4자리 뒤에 구분자가 찍혀 보여도, 실제 조회에는
    숫자만 필요하다(UN Comtrade는 순수 6자리 숫자 코드를 씀). 화면 표시용
    구분자(., 공백 등 숫자가 아닌 문자)는 여기서 전부 제거하고 숫자만 남긴다."""
    return re.sub(r"\D", "", raw or "")
=======
def _country_name_candidates(raw_country, iso3):
    """관세청 API에 넘길 국가명 후보 목록을 만든다."""
    candidates = [raw_country]
    for name, code in KOREAN_NAME_TO_ISO3.items():
        if code == iso3 and any("가" <= ch <= "힣" for ch in name):
            candidates.append(name)
    return candidates


def _fetch_customs_context(hscode, raw_country, iso3, force=False):
    """관세청 공식 자료 연동 (선택 기능)"""
    try:
        candidates = _country_name_candidates(raw_country, iso3)
        return customs_trade_stats.get_customs_context(hscode, candidates, force=force)
    except Exception as e:
        return {"unavailable_reason": str(e)}
>>>>>>> Stashed changes:UN3/app.py


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    hscode = request.args.get("hscode", "").strip()
    country = request.args.get("country", "").strip()
    force = False

    if request.method == "POST":
        hscode = _clean_hscode(request.form.get("hscode", ""))
        country = request.form.get("country", "").strip()
        force = bool(request.form.get("force"))
        try:
            result = get_market_research(hscode, country, force=force)
        except ValueError as e:
            error = str(e)
        except Exception as e:
            error = f"조사 중 오류가 발생했습니다: {e}"

    return render_template(
        "un_comtrade.html",
        result=result, error=error,
        hscode=hscode, country=country, force=force,
    )


def _with_bubble_matrix_positions(candidates, thresholds, min_radius=12, max_radius=40):
    """성장률(X) x 한국 점유율(Y) 매트릭스에 수입액 비례 버블 크기를 결합한 좌표 계산.
    - X축: 수입시장 성장률 (cagr_pct)
    - Y축: 한국 점유율 (korea_share_pct)
    - 버블 크기: 총 수입금액 (total_import_usd, 넓이 비례 sqrt 스케일링)
    """
    if not candidates:
        return [], 50, 50

    cagrs = [c.get("cagr_pct", 0) for c in candidates]
    shares = [c.get("korea_share_pct", 0) for c in candidates]
    values = [c.get("total_import_usd", 0) or 0 for c in candidates]

    x_min, x_max = min(cagrs + [thresholds["avg_cagr_pct"]]), max(cagrs + [thresholds["avg_cagr_pct"]])
    y_min, y_max = min(shares + [thresholds["avg_korea_share_pct"]]), max(shares + [thresholds["avg_korea_share_pct"]])

    # 축 여백 (15%)
    x_pad = (x_max - x_min) * 0.15 or 1
    y_pad = (y_max - y_min) * 0.15 or 1
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    v_min, v_max = min(values), max(values)

    out = []
    for c in candidates:
        # X / Y 좌표 정규화
        x_pct = ((c.get("cagr_pct", 0) - x_min) / (x_max - x_min)) * 100
        y_pct = ((c.get("korea_share_pct", 0) - y_min) / (y_max - y_min)) * 100

        # 버블 크기 (넓이 비례 sqrt)
        import_val = c.get("total_import_usd", 0) or 0
        if v_max > v_min and import_val >= v_min:
            t = math.sqrt(import_val - v_min) / math.sqrt(v_max - v_min)
        else:
            t = 0.5
        radius = round(min_radius + (max_radius - min_radius) * t, 1)

        out.append({
            **c,
            "bubble_radius": radius,
            "x_pct": round(x_pct, 1),
            "y_pct": round(100 - y_pct, 1)  # CSS top 기준 (위쪽이 점유율 높음)
        })

    threshold_x_pct = ((thresholds["avg_cagr_pct"] - x_min) / (x_max - x_min)) * 100
    threshold_y_pct = 100 - ((thresholds["avg_korea_share_pct"] - y_min) / (y_max - y_min)) * 100

    return out, round(threshold_x_pct, 1), round(threshold_y_pct, 1)


_LINE_COLORS = ["#1a73e8", "#e8710a", "#188038", "#d01884", "#7c3aed", "#00838f"]


def _svg_line_series(share_trend, width=560, height=180, pad_l=44, pad_r=16, pad_t=16, pad_b=26):
    """주요국 세계시장 점유율 추이 SVG 좌표 계산"""
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
<<<<<<< Updated upstream:un_v6/app.py
    """여러 후보국을 한 번에 비교하는 종합 화면 (트라이빅 "품목별 유망시장"에 대응):
    세계시장 교역순위, 주요국 점유율 추이, 유망시장 순위(버블차트),
    성장률x한국점유율 매트릭스를 한 페이지에 모은다."""
=======
    """여러 후보국 비교 종합 화면:
    세계시장 교역순위, 점유율 추이, 관세청 수출신고 추이, 통합 버블 매트릭스
    """
>>>>>>> Stashed changes:UN3/app.py
    result = None
    overview = None
    error = None
    hscode = ""
    candidates_raw = ""
    top_n = 10
    bubble_matrix = []
    import_line = export_line = None
    threshold_x_pct = threshold_y_pct = 50
    force = False

    if request.method == "POST":
        hscode = _clean_hscode(request.form.get("hscode", ""))
        candidates_raw = request.form.get("candidates", "").strip()
        top_n = int(request.form.get("top_n") or 10)
        force = bool(request.form.get("force"))
        candidate_list = [c.strip() for c in candidates_raw.split(",") if c.strip()] or None
        try:
            result = get_multi_country_comparison(hscode, candidate_list, top_n=top_n, force=force)
            # 산점도와 버블 차트를 합친 통합 버블 매트릭스 계산
            bubble_matrix, threshold_x_pct, threshold_y_pct = _with_bubble_matrix_positions(
                result["candidates"], result["thresholds"]
            )
        except ValueError as e:
            error = str(e)
        except Exception as e:
            error = f"조사 중 오류가 발생했습니다: {e}"

        if result:
            try:
                overview = get_market_overview(hscode, top_n=top_n, force=force)
                import_line = _svg_line_series(overview["import_share_trend"])
                export_line = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                overview = {"unavailable_reason": str(e)}

<<<<<<< Updated upstream:un_v6/app.py
    return render_template(
        "un_comtrade_matrix.html",
        result=result, overview=overview, error=error,
        scatter=scatter, bubbles=bubbles,
=======
            try:
                customs = customs_trade_stats.get_customs_context(hscode, None, months=60, force=force)
                annual_customs = customs.get("annual_totals", [])
            except Exception as e:
                customs = {"unavailable_reason": str(e)}

    return render_template(
        "un_comtrade_matrix.html",
        result=result, overview=overview, customs=customs, error=error,
        bubble_matrix=bubble_matrix, annual_customs=annual_customs,
>>>>>>> Stashed changes:UN3/app.py
        import_line=import_line, export_line=export_line,
        threshold_x_pct=threshold_x_pct, threshold_y_pct=threshold_y_pct,
        hscode=hscode, candidates_raw=candidates_raw, top_n=top_n, force=force,
    )


if __name__ == "__main__":
    ensure_required_keys()
    app.run(debug=True, port=5070)
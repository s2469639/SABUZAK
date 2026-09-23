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


def _clean_hscode(raw: str) -> str:
    """입력창에 "1905.90"처럼 4자리 뒤에 구분자가 찍혀 보여도, 실제 조회에는
    숫자만 필요하다(UN Comtrade는 순수 6자리 숫자 코드를 씀). 화면 표시용
    구분자(., 공백 등 숫자가 아닌 문자)는 여기서 전부 제거하고 숫자만 남긴다."""
    return re.sub(r"\D", "", raw or "")


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


def _with_scatter_positions(candidates, thresholds):
    """산점도 화면에 찍을 x/y 좌표(0~100%)를 계산한다."""
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
    """유망시장 순위 버블차트 좌표 및 X축 눈금(x_ticks)의 정확한 퍼센트 위치를 함께 계산한다."""
    eligible = [
        c for c in candidates
        if c.get("total_import_usd") and c.get("supplier_country_count") is not None and c.get("import_rank")
    ]
    if not eligible:
        return [], []

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
        
        if x_max > x_min:
            raw_x = (c["import_rank"] - x_min) / (x_max - x_min)
            x_pct = 5.0 + raw_x * 90.0
        else:
            x_pct = 50.0

        if y_max > y_min:
            raw_y = (c["supplier_country_count"] - y_min) / (y_max - y_min)
            y_pct = 95.0 - (raw_y * 90.0)
        else:
            y_pct = 50.0

        out.append({**c, "bubble_radius": radius, "x_pct": round(x_pct, 1), "y_pct": round(y_pct, 1)})

    # X축 순위별 정확한 눈금 위치 계산
    x_ticks = []
    if x_max > x_min:
        for r in range(int(x_min), int(x_max) + 1):
            pct = 5.0 + ((r - x_min) / (x_max - x_min)) * 90.0
            x_ticks.append({"rank": r, "pct": round(pct, 1)})
    else:
        x_ticks = [{"rank": int(x_min), "pct": 50.0}]

    return out, x_ticks


_LINE_COLORS = ["#1a73e8", "#e8710a", "#188038", "#d01884", "#7c3aed", "#00838f"]


def _svg_line_series(share_trend, width=850, height=240, pad_l=60, pad_r=20, pad_t=20, pad_b=30):
    """주요국 세계시장 점유율 추이를 그릴 SVG 좌표를 미리 계산한다."""
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
    result = None
    overview = None
    error = None
    hscode = ""
    candidates_raw = ""
    top_n = 10
    scatter = []
    bubbles = []
    x_ticks = []
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
            scatter, threshold_x_pct, threshold_y_pct = _with_scatter_positions(
                result["candidates"], result["thresholds"]
            )
            bubbles, x_ticks = _with_bubble_positions(result["candidates"])
        except Exception as e:
            if "403" in str(e) or "quota" in str(e).lower():
                try:
                    result = get_multi_country_comparison(hscode, candidate_list, top_n=top_n, force=False)
                    scatter, threshold_x_pct, threshold_y_pct = _with_scatter_positions(
                        result["candidates"], result["thresholds"]
                    )
                    bubbles, x_ticks = _with_bubble_positions(result["candidates"])
                    error = "⚠️ API 일일 호출 한도(Quota)를 초과하여, 기존에 저장된 캐시 데이터를 불러왔습니다."
                except Exception:
                    error = "⚠️ UN Comtrade API 일일 호출 한도(Quota)를 초과했습니다. 잠시 후 다시 시도해 주세요."
            else:
                error = f"조사 중 오류가 발생했습니다: {e}"

        if result:
            try:
                overview = get_market_overview(hscode, top_n=top_n, force=False)
                import_line = _svg_line_series(overview["import_share_trend"])
                export_line = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                overview = {"unavailable_reason": "API 한도 초과로 교역 현황 추이를 불러오지 못했습니다."}

    return render_template(
        "un_comtrade_matrix.html",
        result=result, overview=overview, error=error,
        scatter=scatter, bubbles=bubbles, x_ticks=x_ticks,
        import_line=import_line, export_line=export_line,
        threshold_x_pct=threshold_x_pct, threshold_y_pct=threshold_y_pct,
        hscode=hscode, candidates_raw=candidates_raw, top_n=top_n, force=force,
    )


if __name__ == "__main__":
    ensure_required_keys()
    app.run(debug=True, port=5070)
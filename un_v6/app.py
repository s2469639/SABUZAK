#!/usr/bin/env python3
"""독립 실행형 Flask 웹앱. HS코드 입력 -> UN Comtrade 시장조사 (통합 화면).

매트릭스 비교(여러 후보국)와 단일 국가 상세 조사를 한 화면에서 보여준다.

사전 준비:
    pip install -r requirements.txt
    .env 파일에 OPENAI_API_KEY, UN_COMTRADE_SUBSCRIPTION_KEY 설정
    (없으면 실행 시 터미널에서 물어봄)

실행:
    python app.py
    -> 브라우저에서 http://127.0.0.1:5070 접속 (/matrix 로 들어와도 같은 화면)
"""

import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, render_template, request

from env_setup import ensure_required_keys
from un_comtrade import (
    get_market_overview,
    get_market_research,
    get_multi_country_comparison,
)

app = Flask(__name__)


@app.template_filter("usd_short")
def usd_short(value):
    """차트 눈금/막대 위에 쓸 짧은 금액 표기 (예: 7,829,826,046 -> $7.8B)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    a = abs(v)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"${v / div:,.1f}{suffix}"
    return f"${v:,.0f}"


@app.template_filter("pct")
def pct(value):
    """점유율 표시. 1% 미만은 소수점을 더 보여주고, 아주 작으면 '<0.01%'로 표시해
    "0.0%(없음)"와 "조금 있음"이 구분되게 한다."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if v == 0:
        return "0%"
    a = abs(v)
    if a < 0.01:
        return "<0.01%"
    if a < 1:
        return f"{v:.2f}%"
    return f"{v:.1f}%"


@app.template_filter("kst")
def kst(value):
    """ISO 시각(UTC) -> '2026-09-23 20:36 (한국시간)'."""
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M (한국시간)")


def _clean_hscode(raw: str) -> str:
    """화면 표시용 구분자(., 공백 등)를 제거하고 숫자만 남긴다 (예: 1905.90 -> 190590)."""
    return re.sub(r"\D", "", raw or "")


def _centered_axis(values, center, floor=None, pad_ratio=0.15, edge=8.0):
    """평균(center)이 항상 축의 정중앙(50%)에 오도록 하는 축을 만든다.
    평균보다 작은 쪽은 0~50%, 큰 쪽은 50~100% 구간에 각각 따로 맞춰 그리므로
    네 사분면의 면적이 항상 똑같다. (대신 평균 위/아래의 눈금 간격은 다를 수 있어서
    축 눈금에 실제 값을 표시한다.)
    돌려주는 값: (값 -> 0~100% 변환 함수, 눈금 목록 [(pct, value), ...])"""
    low_span = max([center - v for v in values] + [0])
    high_span = max([v - center for v in values] + [0])
    fallback = max(low_span, high_span) or abs(center) * 0.5 or 1
    low_span = (low_span or fallback) * (1 + pad_ratio)
    high_span = (high_span or fallback) * (1 + pad_ratio)

    low = center - low_span
    if floor is not None and low < floor <= center:
        low = floor  # 예: 점유율은 0% 아래로 내려갈 수 없음
    high = center + high_span

    # 가장자리 edge% 만큼은 비워서 버블이 테두리/사분면 이름표에 붙지 않게 한다
    # (위아래/좌우 똑같이 비우므로 중앙 50%와 사분면 크기는 그대로)
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
    """산점도 좌표(0~100%)를 계산한다. 평균 기준선은 항상 정중앙(50%, 50%)이라
    사분면 네 칸의 크기가 같다.
    항상 (점 목록, 기준선 x%, 기준선 y%, x눈금, y눈금) 5개 값을 돌려준다."""
    if not candidates:
        return [], 50, 50, [], []

    avg_cagr = thresholds["avg_cagr_pct"]
    avg_share = thresholds["avg_korea_share_pct"]
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
    """사분면 라벨을 un_comtrade.py가 실제로 매긴 사분면(c["quadrant"])에 맞춘다.
    각 위치(오른쪽 위 등)에 있는 후보국들의 사분면 이름을 다수결로 정하고,
    후보국이 없는 위치는 기본 이름 중 아직 안 쓴 이름으로 채운다."""
    avg_cagr = thresholds["avg_cagr_pct"]
    avg_share = thresholds["avg_korea_share_pct"]
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
    # 두 위치가 같은 이름으로 뽑히면(기준선 계산 방식 차이 등) 헷갈리니 기본 배치를 쓴다
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


def _build_matrix(candidates, thresholds, min_radius=10, max_radius=34):
    """③ 유망시장 매트릭스(통합 버블차트) 데이터를 만든다.
    X축 = 수입시장 성장률(CAGR), Y축 = 한국 점유율,
    버블 크기 = 수입금액 (넓이가 금액에 비례하도록 sqrt 스케일).
    평균 기준선이 정중앙에 와서 네 사분면의 크기가 같다."""
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
        quadrants.append({
            "pos": pos,
            "label": name,
            "css": _QUADRANT_CSS.get(name, "q-low"),
        })

    return {
        "points": points,
        "threshold_x_pct": tx,
        "threshold_y_pct": ty,
        "x_ticks": x_ticks,
        "y_ticks": y_ticks,
        "quadrants": quadrants,
    }


# 품목 설명 한국어 번역 캐시 (같은 HS코드를 다시 조회할 때 OpenAI를 또 부르지 않도록 파일에 저장)
_DESC_CACHE_FILE = Path(__file__).with_name("item_desc_ko_cache.json")


def _load_desc_cache():
    try:
        return json.loads(_DESC_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_desc_cache(cache):
    try:
        _DESC_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass  # 캐시 저장 실패는 화면 표시에 영향 없음


def _translate_item_desc(text):
    """UN Comtrade 영문 품목 설명을 한국어로 번역한다 (OpenAI 사용).
    실패하면 None을 돌려주고, 화면에는 영문 원문이 그대로 나온다."""
    if not text:
        return None
    cache = _load_desc_cache()
    if text in cache:
        return cache[text]

    try:
        from openai import OpenAI

        client = OpenAI(timeout=20)
        model = os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o-mini")
        prompt = (
            "다음은 HS코드 품목 분류 설명(영문)입니다. 무역 실무에서 쓰는 자연스러운 "
            "한국어로 번역하세요. 'heading no. 1605'처럼 호 번호가 나오면 '제1605호'로 "
            "쓰고, 'n.e.c.'는 '달리 분류되지 않은'으로 옮기세요. "
            "번역문만 한 문단으로 출력하세요.\n\n" + text
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        ko = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[품목 설명 번역 실패 - 영문으로 표시] {e}")
        return None

    if ko:
        cache[text] = ko
        _save_desc_cache(cache)
    return ko or None


_LINE_COLORS = ["#1a8cff", "#e8710a", "#7c3aed", "#d01884", "#00838f", "#8d6e63", "#f9ab00", "#5c6bc0"]
_KOREA_COLOR = "#20b26b"  # 한국은 트라이빅처럼 항상 초록색 (다른 나라와 색이 겹치지 않게)


def _is_korea(label):
    text = str(label).lower()
    return "korea" in text or text in ("kor", "한국", "대한민국")


def _svg_line_series(share_trend, width=560, height=180,
                     pad_l=44, pad_r=16, pad_t=16, pad_b=26):
    """② 주요국 점유율 추이 SVG 좌표를 계산한다. 값이 없는(None) 연도는 건너뛴다."""
    years = share_trend.get("years", [])
    series = share_trend.get("series", {})
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(years)

    base = {
        "years": years, "width": width, "height": height,
        "plot_w": plot_w, "plot_h": plot_h,
        "pad_l": pad_l, "pad_t": pad_t, "pad_b": pad_b,
    }
    if not years or not series:
        base.update({"lines": [], "x_labels": [], "y_max": 1})
        return base

    def x_at(j):
        if n > 1:
            return pad_l + plot_w * j / (n - 1)
        return pad_l + plot_w / 2

    all_vals = []
    for pts in series.values():
        for p in pts:
            if p["share_pct"] is not None:
                all_vals.append(p["share_pct"])
    y_max = (max(all_vals) * 1.15) if all_vals else 1
    y_max = y_max or 1

    lines = []
    color_idx = 0
    for label, pts in series.items():
        if _is_korea(label):
            color = _KOREA_COLOR
        else:
            color = _LINE_COLORS[color_idx % len(_LINE_COLORS)]
            color_idx += 1
        coords = []
        for j, p in enumerate(pts):
            share = p["share_pct"]
            if share is None:
                continue
            x = x_at(j)
            y = pad_t + plot_h - (share / y_max * plot_h)
            coords.append({
                "x": round(x, 1),
                "y": round(y, 1),
                "year": years[j],
                "share_pct": share,
            })
        points_str = " ".join(f"{pt['x']},{pt['y']}" for pt in coords)
        lines.append({
            "label": label,
            "color": color,
            "is_korea": _is_korea(label),
            "points": points_str,
            "coords": coords,
        })

    x_labels = [{"x": round(x_at(j), 1), "year": y} for j, y in enumerate(years)]
    base.update({"lines": lines, "x_labels": x_labels, "y_max": round(y_max, 1)})
    return base


@app.route("/", methods=["GET", "POST"])
@app.route("/matrix", methods=["GET", "POST"])
def index():
    """통합 화면: 매트릭스 비교(①~⑤) + 선택한 국가 상세 조사(⑥).
    두 조사는 독립적이라 한쪽이 실패해도 다른 쪽 결과는 그대로 보여준다.
    GET 링크(/?hscode=...&country=...)로 들어오면 입력칸만 채우고 조사는 하지 않는다."""
    ctx = {
        "result": None,
        "overview": None,
        "matrix_error": None,
        "detail": None,
        "detail_error": None,
        "matrix": None,
        "import_line": None,
        "export_line": None,
        "hscode": _clean_hscode(request.args.get("hscode", "")),
        "candidates_raw": "",
        "top_n": 10,
        "country": request.args.get("country", "").strip(),
        "force": False,
        "item_desc_ko": None,
    }

    if request.method == "POST":
        hscode = _clean_hscode(request.form.get("hscode", ""))
        candidates_raw = request.form.get("candidates", "").strip()
        try:
            top_n = int(request.form.get("top_n") or 10)
        except ValueError:
            top_n = 10
        top_n = max(2, min(top_n, 20))
        country = request.form.get("country", "").strip()
        force = bool(request.form.get("force"))  # 캐시 무시하고 새로 조사

        ctx["hscode"] = hscode
        ctx["candidates_raw"] = candidates_raw
        ctx["top_n"] = top_n
        ctx["country"] = country
        ctx["force"] = force

        # 1) 매트릭스 비교 (여러 후보국)
        candidate_list = [c.strip() for c in candidates_raw.split(",") if c.strip()]
        candidate_list = candidate_list or None
        try:
            result = get_multi_country_comparison(
                hscode, candidate_list, top_n=top_n, force=force
            )
            ctx["result"] = result
            ctx["matrix"] = _build_matrix(
                result["candidates"], result["thresholds"]
            )
        except ValueError as e:
            ctx["matrix_error"] = str(e)
        except Exception as e:
            ctx["matrix_error"] = f"매트릭스 조사 중 오류가 발생했습니다: {e}"

        # 2) 세계시장 교역순위/점유율 추이 (선택 기능 - 실패해도 나머지는 그대로)
        if ctx["result"]:
            try:
                overview = get_market_overview(hscode, top_n=top_n, force=force)
                ctx["overview"] = overview
                ctx["import_line"] = _svg_line_series(overview["import_share_trend"])
                ctx["export_line"] = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                ctx["overview"] = {"unavailable_reason": str(e)}

        # 3) 단일 국가 상세 조사 (상세 조사 국가를 입력하거나 클릭했을 때만)
        if country:
            # 매트릭스 후보국을 클릭한 경우 UN Comtrade 숫자 국가코드로 바로 조회한다
            # (자동 후보 이름이 "Austria"처럼 국가명 매핑표에 없어도 조회되도록)
            reporter_code = None
            if ctx["result"]:
                for c in ctx["result"].get("candidates", []):
                    if c.get("label") == country and c.get("reporter_code"):
                        reporter_code = c["reporter_code"]
                        break
            try:
                ctx["detail"] = get_market_research(
                    hscode, country, force=force, reporter_code=reporter_code
                )
            except ValueError as e:
                ctx["detail_error"] = str(e)
            except Exception as e:
                ctx["detail_error"] = f"국가 상세 조사 중 오류가 발생했습니다: {e}"

        # 4) 품목 설명 한국어 번역 (실패해도 영문 원문으로 표시)
        desc = None
        if ctx["result"]:
            desc = ctx["result"].get("official_item_desc")
        if not desc and ctx["detail"]:
            desc = ctx["detail"].get("official_item_desc")
        ctx["item_desc_ko"] = _translate_item_desc(desc)

    return render_template("un_comtrade_dashboard.html", **ctx)


if __name__ == "__main__":
    ensure_required_keys()
    app.run(debug=True, port=5070)
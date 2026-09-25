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
from markupsafe import escape

from env_setup import ensure_required_keys
from un_comtrade import (
    get_market_overview,
    get_market_research,
    get_multi_country_comparison,
    has_detailed_ai,
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
    """사분면 라벨을 un_comtrade.py가 실제로 매긴 사분면(c["quadrant"])에 맞춘다.
    각 위치(오른쪽 위 등)에 있는 후보국들의 사분면 이름을 다수결로 정하고,
    후보국이 없는 위치는 기본 이름 중 아직 안 쓴 이름으로 채운다."""
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


def _parse_form(form):
    """폼 입력을 정리한다. 대시보드 첫 화면, ⑥ 부분 갱신, AI 요청이 모두 같은 규칙을 쓴다."""
    hscode = _clean_hscode(form.get("hscode", ""))
    candidates_raw = (form.get("candidates") or "").strip()
    raw_top_n = (form.get("top_n") or "").strip()
    try:
        top_n = int(raw_top_n) if raw_top_n != "" else 10
    except ValueError:
        top_n = 10
    top_n = max(0, min(top_n, 20))  # 0 = 관심 국가만 비교
    # 쉼표뿐 아니라 한글 쉼표/세미콜론으로 구분해도 받아준다
    candidate_list = [c.strip() for c in re.split(r"[,，;、]", candidates_raw) if c.strip()]
    return {
        "hscode": hscode,
        "candidates_raw": candidates_raw,
        "candidate_list": candidate_list,
        "top_n": top_n,
        "country": (form.get("country") or "").strip(),
        "force": bool(form.get("force")),
    }


def _load_comparison(f, include_ai=False, retry_customs=False):
    """③④⑤ 비교 분석. 결과 전체가 캐시되므로 두 번째부터는 즉시 돌아온다."""
    if f["top_n"] == 0 and not f["candidate_list"]:
        return None, "비교 국가 수가 0이면 관심 국가를 1개 이상 입력해주세요."
    try:
        result = get_multi_country_comparison(
            f["hscode"], f["candidate_list"] or None, top_n=f["top_n"],
            force=f["force"], include_ai=include_ai, retry_customs=retry_customs,
        )
        return result, None
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"비교 분석 중 오류가 발생했습니다: {e}"


def _pick_detail_country(result, candidate_list):
    """⑥에 먼저 보여줄 나라: 관심 국가(입력 순서) -> 비교 국가 중 수입 1위."""
    candidates = (result or {}).get("candidates", [])
    by_rank = sorted(candidates, key=lambda c: c.get("import_rank") or 999)
    focus = sorted(
        (c for c in by_rank if c.get("is_focus")),
        key=lambda c: c.get("focus_order") if c.get("focus_order") is not None else 999,
    )
    if focus:
        return focus[0]["label"], "관심 국가"
    if by_rank:
        return by_rank[0]["label"], "비교 국가 중 수입 1위"
    if candidate_list:
        return candidate_list[0], "관심 국가"  # 비교 분석이 실패해도 관심 국가 상세는 시도
    return "", None


def _load_detail(f, result, country, include_ai=False):
    """⑥ 국가 상세. 비교 국가를 고른 경우 UN Comtrade 숫자 국가코드로 바로 조회한다
    (자동 후보 이름이 "Austria"처럼 국가명 매핑표에 없어도 조회되도록)."""
    reporter_code = None
    iso3_hint = None
    for c in (result or {}).get("candidates", []):
        if c.get("label") == country:
            reporter_code = c.get("reporter_code")
            iso3_hint = c.get("iso3")
            break
    try:
        detail = get_market_research(
            f["hscode"], country, force=f["force"],
            reporter_code=reporter_code, iso3_hint=iso3_hint, include_ai=include_ai,
        )
        return detail, None
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"국가 상세 조사 중 오류가 발생했습니다: {e}"


def _detail_ai_pending(detail):
    return bool(detail) and not has_detailed_ai(detail.get("ai_insight"))


@app.route("/", methods=["GET", "POST"])
@app.route("/matrix", methods=["GET", "POST"])
def index():
    """통합 화면. 입력값이 어느 섹션에 쓰이는지:
        - HS코드: 모든 섹션
        - 비교 국가 수(N): ①② 세계시장 순위/점유율 추이의 표시 개수 + ③④⑤ 비교 대상(수입 상위 N개국)
        - 관심 국가: ③④⑤ 비교 대상에 추가(상위 N개국과 합집합) + ⑥ 상세 조사를 자동으로 열 국가
        - ⑥ 국가 상세: 탭/버블/표에서 고른 한 나라. 아무것도 고르지 않았으면
          관심 국가(첫 번째) -> 없으면 수입 1위 국가를 자동으로 보여준다.
    속도: 숫자 화면을 먼저 보여주고, 시간이 오래 걸리는 AI 해석(⑤, ⑥)은 화면이
    /ai/matrix, /ai/detail로 따로 불러온다. 탭을 누르면 /detail로 ⑥만 바꾼다.
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
        "detail_auto_reason": None,  # ⑥을 자동으로 연 이유 (화면 안내용)
        "matrix_ai_pending": False,
        "detail_ai_pending": False,
    }

    if request.method == "POST":
        f = _parse_form(request.form)
        ctx.update(hscode=f["hscode"], candidates_raw=f["candidates_raw"], top_n=f["top_n"],
                   country=f["country"], force=f["force"])

        if not re.fullmatch(r"\d{6}", f["hscode"]):
            ctx["matrix_error"] = "HS코드는 6자리 숫자로 입력해주세요 (예: 1905.90)."
            return render_template("un_comtrade_dashboard.html", **ctx)

        # 1) 비교 분석 (AI 해석은 나중에 따로)
        # 관세청 조회가 일시적으로 실패했던 나라는 "통합분석"을 누를 때만 다시 시도한다
        # (탭 전환 때마다 재시도하면 관세청 장애 중에 탭이 느려지므로)
        result, err = _load_comparison(f, include_ai=False, retry_customs=True)
        ctx["result"], ctx["matrix_error"] = result, err
        if result:
            ctx["matrix"] = _build_matrix(result["candidates"], result["thresholds"])
            ctx["matrix_ai_pending"] = not result.get("ai_summary")

            # 2) 세계시장 교역순위/점유율 추이 (선택 기능 - 실패해도 나머지는 그대로)
            try:
                # 세계 순위 그래프는 비교 국가 수가 0이어도 상위 10개국은 보여준다
                overview = get_market_overview(f["hscode"], top_n=f["top_n"] or 10, force=f["force"])
                ctx["overview"] = overview
                ctx["import_line"] = _svg_line_series(overview["import_share_trend"])
                ctx["export_line"] = _svg_line_series(overview["export_share_trend"])
            except Exception as e:
                ctx["overview"] = {"unavailable_reason": str(e)}

        # 3) 국가 상세 (⑥). 고른 나라가 없으면 자동으로 고른다.
        country = f["country"]
        if not country:
            country, ctx["detail_auto_reason"] = _pick_detail_country(result, f["candidate_list"])
            ctx["country"] = country
        if country:
            ctx["detail"], ctx["detail_error"] = _load_detail(f, result, country, include_ai=False)
            ctx["detail_ai_pending"] = _detail_ai_pending(ctx["detail"])

        # 4) 품목 설명 한국어 번역 (실패해도 영문 원문으로 표시)
        desc = (result or {}).get("official_item_desc") or (ctx["detail"] or {}).get("official_item_desc")
        ctx["item_desc_ko"] = _translate_item_desc(desc)

    return render_template("un_comtrade_dashboard.html", **ctx)


@app.route("/detail", methods=["POST"])
def detail_partial():
    """국가 탭/버블/표를 눌렀을 때 ⑥ 부분만 HTML 조각으로 돌려준다.
    비교 결과는 캐시에서 바로 읽고(탭 목록·국가코드용), 국가 데이터도 한 번 조회한 나라는
    캐시에서 읽으므로 보통 1초 안에 끝난다. AI 해석은 화면이 /ai/detail로 따로 요청한다."""
    f = _parse_form(request.form)
    f["force"] = False  # 탭 전환은 항상 캐시를 쓴다
    result, _ = _load_comparison(f, include_ai=False)
    country = f["country"]
    detail, detail_error = _load_detail(f, result, country, include_ai=False) if country else (None, None)
    desc = (result or {}).get("official_item_desc") or (detail or {}).get("official_item_desc")
    return render_template(
        "_country_detail.html",
        result=result, detail=detail, detail_error=detail_error, country=country,
        detail_auto_reason=None, item_desc_ko=_translate_item_desc(desc) if not result else None,
        detail_ai_pending=_detail_ai_pending(detail),
    )


@app.route("/ai/matrix", methods=["POST"])
def ai_matrix_partial():
    """⑤ 비교 분석 AI 해석만 만들어 HTML 조각으로 돌려준다 (결과는 캐시에 저장)."""
    f = _parse_form(request.form)
    f["force"] = False
    result, err = _load_comparison(f, include_ai=True)
    if not result:
        return f'<div class="ai-box empty">AI 해석을 만들 수 없습니다: {escape(err or "")}</div>'
    return render_template("_ai_matrix.html", result=result, matrix_ai_pending=False)


@app.route("/ai/detail", methods=["POST"])
def ai_detail_partial():
    """⑥ 국가 상세 AI 해석만 만들어 HTML 조각으로 돌려준다 (결과는 캐시에 저장)."""
    f = _parse_form(request.form)
    f["force"] = False
    result, _ = _load_comparison(f, include_ai=False)
    detail, err = _load_detail(f, result, f["country"], include_ai=True) if f["country"] else (None, "국가가 없습니다.")
    if not detail:
        return f'<div class="ai-box empty">AI 해석을 만들 수 없습니다: {escape(err or "")}</div>'
    return render_template("_ai_detail.html", detail=detail, detail_ai_pending=False)


if __name__ == "__main__":
    ensure_required_keys()
    app.run(debug=True, port=5070)
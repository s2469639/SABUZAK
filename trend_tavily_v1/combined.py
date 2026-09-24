"""trend_usp_v1(검색 트렌드) + tavily_v5(웹 자료) 결합 실험.

두 폴더의 코드는 수정하지 않고 그대로 불러와서 쓴다.
- trend_usp_v1: Google 트렌드 연관 검색어 → 4단계 분류, 경쟁 제품 검색량, USP, 부스
- tavily_v5:    Tavily 웹 검색 → 원문 대조를 마친 발췌(출처 URL) 기반 소비자·경쟁·바이어·박람회 카드

결합 방식 (추가 API 호출 없이 코드로만 연결)
1. 두 파이프라인을 동시에 실행한다. 한쪽이 실패해도 다른 쪽 결과는 보여준다.
2. 경쟁 제품 교차 확인: trend가 찾은 경쟁 제품 이름이 Tavily 발췌 원문에 등장하면
   "웹 출처" 근거로 붙인다. 발췌에 가격 표현이 있으면 "웹 출처 가격"으로 따로 표시한다.
3. 바이어 체크포인트: Tavily Q3(바이어·유통) 카드에 근거 있는 포인트가 있으면 그것을 우선 쓰고,
   없을 때만 trend의 AI 참고 체크포인트를 쓴다.
4. 소비자(Q1)·경쟁 제품(Q2)·박람회(Q4) 카드와 Tavily 부스 포인트는 관련 섹션 옆에 붙인다.
"""

import functools
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREND_DIR = os.path.join(ROOT_DIR, "trend_usp_v1")
TAVILY_DIR = os.path.join(ROOT_DIR, "tavily_v5")


def _load_modules():
    """두 폴더의 모듈을 불러온다.

    tavily_v5/research.py는 `from env_setup import ...`로 자기 폴더의 env_setup을 쓰므로 먼저 불러온다.
    trend_usp_v1/trend_usp.py는 env_setup을 쓰지 않고 constants·http_compat만 쓴다."""
    sys.path.insert(0, TAVILY_DIR)
    try:
        import env_setup as tavily_env  # noqa: E402  (tavily_v5/env_setup.py)
        import research as tavily_research  # noqa: E402
    finally:
        sys.path.remove(TAVILY_DIR)
    # 앞에 넣으면 trend_usp_v1/app.py·cli.py가 이 폴더의 app.py·cli.py를 가리므로 뒤에 붙인다
    if TREND_DIR not in sys.path:
        sys.path.append(TREND_DIR)
    import trend_usp  # noqa: E402
    from http_compat import SAFE_HEADERS  # noqa: E402

    # tavily_v5는 OpenAI를 기본 설정으로 만든다. 예전 brotli가 깔린 PC에서 실패하지 않도록
    # trend_usp와 같은 방식(br 압축 요청 안 함)으로 감싼다. 원본 파일은 수정하지 않는다.
    if not isinstance(tavily_research.OpenAI, functools.partial):
        tavily_research.OpenAI = functools.partial(tavily_research.OpenAI, default_headers=SAFE_HEADERS)
    return tavily_env, tavily_research, trend_usp


tavily_env, tavily_research, trend_usp = _load_modules()

PRICE_PATTERN = re.compile(r"([$€£¥₩]\s?\d)|(\d[\d.,]*\s?(usd|eur|gbp|jpy|krw|dollars?|euros?|달러|유로|엔|원)\b)",
                           re.IGNORECASE)
MAX_WEB_QUOTES_PER_COMPETITOR = 2
COMPANY_PROFILE_MAP = {"strengths": "strengths", "ingredients": "ingredients",
                       "certifications": "certifications", "price_range": "price"}


def english_country_name(profile: dict, fallback: str) -> str:
    """tavily_v5는 영문 국가명(United States 등)을 기준으로 국가·권역을 판정한다.
    trend 국가 프로필의 별칭 중 tavily_v5 국가표에 있는 가장 긴 이름을 쓴다."""
    known = [a for a in profile.get("aliases", []) if a in tavily_research.COUNTRIES]
    if known:
        return max(known, key=len).title().replace("Uae", "UAE").replace("Uk", "UK").replace("Usa", "USA")
    return fallback


def _run_trend(product: dict, country: str, force: bool):
    return trend_usp.run_trend_usp(product, country, use_cache=not force)


def _run_tavily(product: dict, country_en: str, exhibition_name: str, exhibition_website: str, force: bool):
    profile = {k: product.get(v, "") for k, v in COMPANY_PROFILE_MAP.items()}
    return tavily_research.run_research(product["name"], country_en, exhibition_name=exhibition_name or None,
                                        exhibition_website=exhibition_website or None,
                                        company_profile=profile, force=force)


def _error_text(e: Exception) -> str:
    return str(e) or e.__class__.__name__


def run_combined(product: dict, country: str, exhibition_name: str = "", exhibition_website: str = "",
                 force: bool = False) -> dict:
    """두 파이프라인을 동시에 실행하고 결과를 교차 연결한다."""
    product = {k: (product.get(k) or "").strip() for k in trend_usp.PRODUCT_FIELDS}
    if not product["name"]:
        raise trend_usp.PipelineError("제품명을 입력해 주세요.")
    profile = trend_usp.resolve_country_profile(country)
    country_en = english_country_name(profile, country)

    with ThreadPoolExecutor(max_workers=2) as pool:
        trend_future = pool.submit(_run_trend, product, country, force)
        tavily_future = pool.submit(_run_tavily, product, country_en, exhibition_name, exhibition_website, force)
        trend, trend_error = _collect(trend_future)
        tavily, tavily_error = _collect(tavily_future)

    if trend is None and tavily is None:
        raise trend_usp.PipelineError(f"두 분석이 모두 실패했습니다. 트렌드: {trend_error} / 웹 자료: {tavily_error}")

    return {
        "trend": trend,
        "tavily": tavily,
        "trend_error": trend_error,
        "tavily_error": tavily_error,
        "country_en": country_en,
        "links": link_results(trend, tavily),
    }


def _collect(future):
    try:
        return future.result(), None
    except Exception as e:  # 한쪽 실패는 결과 화면에 경고로 보여준다
        return None, _error_text(e)


# ---------------------------------------------------------------------------
# 교차 연결 (코드로만)
# ---------------------------------------------------------------------------

def _web_quote(q: dict, sources_by_id: dict) -> dict:
    src = sources_by_id.get((q.get("source_ids") or [None])[0], {})
    return {
        "id": q["id"], "question": q.get("question"), "quote": q.get("quote", ""),
        "translation_ko": q.get("translation_ko", ""), "market_label": q.get("market_label", ""),
        "year": q.get("year"), "is_stale": q.get("is_stale", False),
        "url": src.get("url", ""), "domain": src.get("domain", ""), "title": src.get("title", ""),
    }


def _mentions(text: str, names: list) -> bool:
    text_cf = (text or "").casefold()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(n.casefold()) + r"(?![a-z0-9])", text_cf)
               for n in names if len(n) >= 4)


AMOUNT_PATTERN = re.compile(
    r"[$€£¥₩]\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:usd|eur|gbp|jpy|krw|dollars?|euros?|달러|유로|엔|원)",
    re.IGNORECASE)


def price_amounts(text: str) -> set:
    """통화 기호·단위가 붙은 금액만 뽑는다 ("$8.99 / 12oz" → {"8.99"}, 중량 12는 제외)."""
    return {(a or b).replace(",", "") for a, b in AMOUNT_PATTERN.findall(text or "")}


def match_competitors(trend: dict, tavily: dict) -> dict:
    """경쟁 제품 이름(name, search_term)이 Tavily 발췌 원문에 나오면 웹 출처로 연결한다.

    반환: {competitor_id: {"quotes": [...], "price_quotes": [...]}}"""
    sources_by_id = {s["id"]: s for s in tavily.get("sources") or []}
    quotes = tavily.get("quotes") or []
    matches = {}
    for comp in trend.get("competitors") or []:
        names = list(dict.fromkeys([comp["name"], comp.get("search_term", "")]))
        hits = [q for q in quotes if _mentions(q.get("quote", ""), names)]
        # 경쟁 제품 질문(Q2) 발췌, 대상 국가 발췌, 최신 자료 순으로
        hits.sort(key=lambda q: (q.get("question") != "Q2", q.get("market") != "country", q.get("is_stale", False)))
        if not hits:
            continue
        web = [_web_quote(q, sources_by_id) for q in hits]
        price_quotes = [w for w in web if PRICE_PATTERN.search(w["quote"])][:1]
        # AI가 추정한 가격 금액이 웹 발췌 원문의 가격 금액과 겹치면 "웹 출처와 일치"
        ai_amounts = price_amounts(comp.get("price_local", ""))
        matches[comp["id"]] = {
            "quotes": web[:MAX_WEB_QUOTES_PER_COMPETITOR],
            "price_quotes": price_quotes,
            "price_confirmed": bool(price_quotes and ai_amounts & price_amounts(price_quotes[0]["quote"])),
        }
    return matches


def _card(tavily: dict, qid: str):
    for card in (tavily or {}).get("cards") or []:
        if card.get("qid") == qid:
            return card
    return None


def _resolved_points(card, tavily: dict) -> list:
    """카드 포인트에 근거 발췌의 출처 링크를 붙인다."""
    if not card:
        return []
    quotes_by_id = {q["id"]: q for q in tavily.get("quotes") or []}
    sources_by_id = {s["id"]: s for s in tavily.get("sources") or []}
    out = []
    for p in card.get("points") or []:
        refs = [_web_quote(quotes_by_id[i], sources_by_id) for i in p.get("quote_ids") or [] if i in quotes_by_id]
        out.append({"text": p["text"], "refs": refs})
    return out


def link_results(trend, tavily) -> dict:
    links = {"competitors": {}, "consumer": [], "competition": [], "buyer": [], "exhibition": [],
             "tavily_booth": None, "checkpoint_source": "ai", "summary": {}}
    if tavily:
        links["consumer"] = _resolved_points(_card(tavily, "Q1"), tavily)
        links["competition"] = _resolved_points(_card(tavily, "Q2"), tavily)
        links["buyer"] = _resolved_points(_card(tavily, "Q3"), tavily)
        links["exhibition"] = _resolved_points(_card(tavily, "Q4"), tavily)
        booth = tavily.get("booth")
        if booth and (booth.get("reasons") or booth.get("ideas")):
            quotes_by_id = {q["id"]: q for q in tavily.get("quotes") or []}
            sources_by_id = {s["id"]: s for s in tavily.get("sources") or []}

            def refs(ids):
                return [_web_quote(quotes_by_id[i], sources_by_id) for i in ids or [] if i in quotes_by_id]

            links["tavily_booth"] = {
                "key_message": booth.get("key_message"),
                "reasons": [{"text": r["text"], "refs": refs(r.get("quote_ids"))} for r in booth.get("reasons") or []],
                "ideas": [{"text": i["text"], "refs": refs(i.get("quote_ids"))} for i in booth.get("ideas") or []],
            }
        if links["buyer"]:
            links["checkpoint_source"] = "web"
    if trend and tavily:
        links["competitors"] = match_competitors(trend, tavily)

    stats = (tavily or {}).get("stats") or {}
    usp_ids = [r["competitor_id"] for r in (trend or {}).get("usp_matrix") or []]
    links["summary"] = {
        "usp_rows": len(usp_ids),
        "usp_rows_web_confirmed": sum(1 for cid in usp_ids if cid in links["competitors"]),
        "competitors": len((trend or {}).get("competitors") or []),
        "competitors_web_confirmed": len(links["competitors"]),
        "web_quotes": stats.get("quotes_used", 0),
        "web_country_quotes": stats.get("country_quotes", 0),
        "web_sources": stats.get("sources_found", 0),
        "web_cards_with_points": sum(1 for k in ("consumer", "competition", "buyer", "exhibition") if links[k]),
    }
    return links

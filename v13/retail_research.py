"""섹션 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석 (j_test/retail_research.py 기반, v12).

v12 변경점
- 클라이언트를 처음 쓸 때 만든다(.env는 최상위 SABUZAK/.env). OpenAI는 model_upgrade로 감싸 상위 모델 사용.
- 경쟁 제품 가격을 3단계로 찾는다:
    ① Tavily로 현지 유통몰에서 실제 판매가 검색
    ② 못 찾으면 OpenAI 웹 검색으로 판매가 + 출처 URL (실제 검색 인용에 있는 URL만 인정)
    ③ 그래도 못 찾으면 입력 가격대 ±15% "타깃 세그먼트 추정가"
- 부스 제안(booth_solution)은 만들지 않는다 (부스 컨셉은 섹션 4 담당).
"""

import os
import re
import json

from openai import OpenAI
from tavily import TavilyClient

import model_upgrade
from env_setup import load_env
from http_compat import SAFE_HEADERS

RETAIL_STEPS = 4   # 진행률 표시용: 경쟁 제품 분석, Tavily 가격, OpenAI 웹 검색 가격, 정리
_clients = {}


def get_clients():
    if not _clients:
        load_env()
        _clients["openai"] = model_upgrade.wrap(
            OpenAI(api_key=os.getenv("OPENAI_API_KEY"), default_headers=SAFE_HEADERS, timeout=180))
        _clients["tavily"] = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _clients["openai"], _clients["tavily"]

# 국가별 통화 및 USD 기준 환율 테이블
COUNTRY_CURRENCY_MAP = {
    "말레이시아": "MYR", "미국": "USD", "일본": "JPY", "독일": "EUR",
    "프랑스": "EUR", "영국": "GBP", "호주": "AUD", "캐나다": "CAD",
    "폴란드": "PLN", "베트남": "VND", "인도네시아": "IDR", "태국": "THB"
}
RATES_TO_USD = {
    "USD": 1.0, "AUD": 0.65, "EUR": 1.08, "PLN": 0.25,
    "JPY": 0.0067, "GBP": 1.28, "CAD": 0.74, "KRW": 0.00075,
    "MYR": 0.23, "VND": 0.00004, "THB": 0.028
}
USD_TO_KRW = 1350

# 한자 오염 방지 텍스트 정제 함수
def sanitize_korean_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    hanja_map = {
        "便利": "편리", "快適": "쾌적", "迅速": "신속", "安心": "안심",
        "安全": "안전", "健康": "건강", "新鮮": "신선", "品質": "품질",
        "価格": "가격", "満足": "만족", "簡単": "간편", "手軽": "간편"
    }
    for hj, ko in hanja_map.items():
        text = text.replace(hj, ko)
    # 한글 문장 사이에 뜬금없이 들어간 단독 한자들을 최대한 자연스럽게 치환
    text = text.replace("便利성", "편의성").replace("便利함", "편리함")
    return text

def sanitize_dict_recursively(obj):
    if isinstance(obj, dict):
        return {k: sanitize_dict_recursively(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_dict_recursively(elem) for elem in obj]
    elif isinstance(obj, str):
        return sanitize_korean_text(obj)
    return obj

def _citations(response):
    """Responses API 답변에서 실제 웹 검색 인용 URL을 모은다."""
    urls = {}
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            for ann in getattr(content, "annotations", None) or []:
                if getattr(ann, "type", "") == "url_citation" and getattr(ann, "url", ""):
                    urls[ann.url] = getattr(ann, "title", "") or ""
    return urls


def _json_from_text(text):
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON을 찾지 못함")
    return json.loads(text[start:end + 1])


def openai_web_price(openai_client, product, country, currency, retail_domains):
    """② OpenAI 웹 검색으로 경쟁 제품의 현지 판매가를 찾는다. 출처가 실제 검색 인용에 있을 때만 인정.
    반환: {"price_range", "sources": [{"url", "title"}]} 또는 None"""
    prompt = f"""웹 검색으로 {country}에서 판매 중인 '{product}'의 실제 소매 판매가를 찾으세요.
참고할 현지 유통몰: {", ".join(retail_domains) or "(없음 - 현지 주요 온라인몰·마트)"}
- 실제 상품 페이지나 가격이 적힌 페이지에서 확인한 가격만 쓰세요. 추정하지 마세요.
- 용량과 통화를 함께 적으세요 (가능하면 {currency}). 여러 곳이면 범위로.
- 찾지 못했으면 found를 false로.
JSON만 답하세요: {{"found": true, "price_range": "예: 4.50 ~ 6.90 {currency} (400g)", "source_urls": ["실제로 본 페이지 URL"]}}"""
    response = openai_client.responses.create(model=model_upgrade.TASK_MODEL, tools=[{"type": "web_search"}],
                                              input=prompt)
    data = _json_from_text(getattr(response, "output_text", ""))
    cited = _citations(response)
    if not data.get("found") or not str(data.get("price_range") or "").strip():
        return None
    sources = []
    for url in data.get("source_urls") or []:
        url = str(url).strip()
        match = next((c for c in cited if c.rstrip("/") == url.rstrip("/")), None)
        if match:
            sources.append({"url": match, "title": cited[match]})
    if not sources:   # 모델이 적은 URL이 실제 검색 인용에 없으면 믿지 않는다
        return None
    return {"price_range": str(data["price_range"]).strip(), "sources": sources}


CURRENCY_MARKS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "円": "JPY", "RM": "MYR", "zł": "PLN", "₫": "VND", "฿": "THB"}


def convert_price_text(price_text, currency):
    """'4.50 ~ 6.90 MYR' 같은 가격 문구의 숫자를 USD·원화로 환산한다. 통화가 확실하지 않으면 빈 문자열."""
    text = str(price_text or "")
    found = {code for code in RATES_TO_USD if re.search(rf"\b{code}\b", text)}
    found |= {code for mark, code in CURRENCY_MARKS.items() if mark in text}
    if len(found) > 1 or (found and currency not in found):
        currency = next(iter(found)) if len(found) == 1 else None
    if not currency or currency not in RATES_TO_USD:
        return "", ""
    # 용량 괄호(400g 등)는 빼고 가격 숫자만
    body = re.sub(r"\([^)]*\)", "", text)
    body = re.sub(r"(\d),(\d{1,2})(?!\d)", r"\1.\2", body)   # 유럽식 소수점 8,99 → 8.99 (1,280은 그대로)
    numbers = [float(m.group(1).replace(",", ""))
               for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)(?!\d)(?!\s*(?:kg|g|ml|l|oz|lb|개|입|pcs|pack|인분)(?![a-z]))", body,
                                    re.IGNORECASE)]
    numbers = [x for x in numbers if x > 0][:2]
    if not numbers:
        return "", ""
    low, high = min(numbers), max(numbers)
    rate = RATES_TO_USD[currency]
    usd_low, usd_high = round(low * rate, 1), round(high * rate, 1)
    usd = f"${usd_low:g} USD" if low == high else f"${usd_low:g} ~ ${usd_high:g} USD"
    krw_low, krw_high = int(low * rate * USD_TO_KRW), int(high * rate * USD_TO_KRW)
    krw = f"약 {krw_low:,}원" if low == high else f"약 {krw_low:,} ~ {krw_high:,}원"
    return usd, krw


def analyze_retail_market(product_name: str, country: str, strengths: str, raw_materials: str, target_price_str: str,
                          progress=None) -> dict:
    step = progress or (lambda label: None)
    openai_client, tavily_client = get_clients()
    target_currency = COUNTRY_CURRENCY_MAP.get(country, "USD")
    step("경쟁 제품·유통 채널 분석")

    step1_prompt = f"""
    당신은 글로벌 1위 식료품 유통망의 시니어 카테고리 바이어(MD)입니다.
    추상적인 교과서 문구(예: "매력적인 디자인", "새로운 기회 창출", "Elevate")를 엄격히 금지하며, 반드시 [우리 제품 원료]와 [현지 구체적 식문화]가 직접 명시된 실무 기획서를 작성하세요.

    [입력 데이터]
    - 대상 국가: {country} (공식 통화: {target_currency})
    - 우리 제품명: {product_name}
    - 제품 강점: {strengths}
    - 주요 원료: {raw_materials}
    - 목표 가격대: "{target_price_str}"

    [필수 분석 지침 - 엄격 준수]
    1. 언어 출력 원칙 (★한자 혼용 절대 금지):
       - 한국어 문장 내에 '便利', '快適', '迅速' 같은 한자를 절대 섞어 쓰지 마십시오. 무조건 100% 순수 한글('편리', '쾌적', '신속')로만 작성하세요.
    2. 제형 및 국물/조리 방식 완벽 일치:
       - '맑은 국물 생면 밀키트(칼국수)'에 유탕 볶음 라면(예: 미고랭, 야키소바)이나 자극적인 매운 라면을 매칭하지 마십시오.
       - 반드시 {country} 현지에서 동일하게 '맑고 담백한 해물/멸치/닭 육수 생면(예: 말레이시아의 경우 전통 멸치 생면인 Pan Mee/板面 밀키트, 또는 냉장 우동/라멘 키트)'을 1위 경쟁재로 지정하세요.
    3. 바이어 피칭 & Q&A (제품 고유 팩트 기반):
       - "소비자 니즈 충족" 같은 모호한 문구 금지.
       - 원료와 대체 가치를 명시하여 바이어 매대의 객단가를 확장하는 논리로 작성하세요.
    4. retail_domains:
       - {country} 현지 대형마트 2개 (예: 말레이시아면 jaya-grocer.com, villagegrocer.com.my, lotus.com.my 등).

    반환 규격 (JSON):
    {{
      "primary_category": "식품 대분류",
      "kw1": "현지어 직관 검색어",
      "kw2": "상위 카테고리",
      "kw3": "현지 1위 대체재 품목명 (원어)",
      "retail_domains": ["유통몰도메인1", "유통몰도메인2"],
      "category_anchors": "필수 포함 앵커",
      "negative_anchors": "-mi goreng -instant fried noodle -snack",
      "min_price": 5.0,
      "max_price": 7.0,
      "currency_symbol": "{target_currency}",
      "competitor_product": "현지 1위 동급 대체재 품목명 (원어 및 한글)",
      "competitor_specs": "경쟁 제품 실제 규격, 면 제형(생면/건면), 육수 베이스",
      "consumer_complaints": "{country} 현지 소비자가 기존 국물 면제품에서 느끼는 구체적 불만",
      "shelf_location": "현지 마트 내 정확한 매대 명칭 (예: Chilled Fresh Asian Noodle Zone)",
      "value_pitch": "구체적 원료와 조리 편의성을 담은 바이어 입점 피칭"
    }}
    반드시 순수 JSON만 반환하세요.
    """

    response = openai_client.chat.completions.create(
        model=model_upgrade.TASK_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": step1_prompt}]
    )
    raw_analysis = json.loads(response.choices[0].message.content)
    
    # 1차 한자 정제 적용
    analysis = sanitize_dict_recursively(raw_analysis)
    analysis.pop("booth_solution", None)   # 부스 제안은 섹션 4 담당

    primary_category = analysis.get("primary_category", "식료품")
    kw3 = analysis.get("kw3", product_name)
    retail_domains = analysis.get("retail_domains", [])
    category_anchors = analysis.get("category_anchors", "")
    negative_anchors = analysis.get("negative_anchors", "")
    min_price = float(analysis.get("min_price", 0.0))
    max_price = float(analysis.get("max_price", min_price))
    currency = analysis.get("currency_symbol", target_currency).upper().strip()

    # ① Tavily 실측 검색
    step("현지 유통몰 판매가 검색 (Tavily)")
    search_query = f'"{kw3}" ({category_anchors}) {negative_anchors}'.strip()
    search_success = False
    parsed_price_info = None

    try:
        search_res = tavily_client.search(
            query=search_query,
            include_domains=retail_domains,
            max_results=3,
            search_depth="basic"
        )
        results = search_res.get("results", [])
        if results:
            combined = "\n".join([r.get("content", "") for r in results])
            parse_prompt = f"""
            아래 검색 텍스트에서 '{kw3}' 상품의 실제 판매 가격을 찾아 JSON으로 요약하세요.
            [검색 결과]
            {combined}
            규격: {{"is_valid": true/false, "price_range": "실측 가격대 (통화 표기 포함)"}}
            """
            parse_res = openai_client.chat.completions.create(
                model=model_upgrade.TASK_MODEL,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": parse_prompt}]
            )
            parsed_data = json.loads(parse_res.choices[0].message.content)
            if parsed_data.get("is_valid") and parsed_data.get("price_range"):
                parsed_price_info = {**parsed_data, "sources": [{"url": r.get("url", ""), "title": r.get("title", "")}
                                                                for r in results if r.get("url")]}
                search_success = True
    except Exception:
        search_success = False

    # ② Tavily로 못 찾으면 OpenAI 웹 검색
    web_price = None
    if search_success:
        step("가격 확인됨 · 추가 검색 생략")
    else:
        step("OpenAI 웹 검색으로 판매가 확인")
        try:
            web_price = openai_web_price(openai_client, analysis.get("competitor_product") or kw3, country,
                                         currency, retail_domains)
        except Exception:
            web_price = None
    step("가격 정리·환산")

    # 가격 결정 및 다중 통화 환산
    rate_to_usd = RATES_TO_USD.get(currency, 1.0)

    price_sources, price_method = [], "estimate"
    if search_success and parsed_price_info:
        badge = "실측가 (Tavily)"
        badge_desc = "현지 주요 유통몰에서 Tavily 검색으로 수집한 실제 판매 가격입니다."
        price_display = parsed_price_info["price_range"]
        usd_converted, krw_converted = convert_price_text(price_display, currency)
        price_sources, price_method = parsed_price_info["sources"], "tavily"
    elif web_price:
        badge = "AI 웹 검색가"
        badge_desc = "Tavily로 찾지 못해 OpenAI 웹 검색으로 확인한 판매 가격입니다. 출처 링크에서 원문을 확인하세요."
        price_display = web_price["price_range"]
        usd_converted, krw_converted = convert_price_text(price_display, currency)
        price_sources, price_method = web_price["sources"], "openai_web"
    else:
        badge = "타깃 세그먼트 추정가"
        badge_desc = f"현지 매장 웹 차단이나 비정상 단가 노이즈를 방지하기 위해, 입력하신 목표 가격대를 기준으로 현지 동급 세그먼트의 시장 유효 진입 범위(±15%)를 역산한 가격입니다."
        if min_price > 0 and max_price > 0:
            est_low = round(min_price * 0.85, 1)
            est_high = round(max_price * 1.15, 1)
            price_display = f"{est_low:g} ~ {est_high:g} {currency}"
            
            usd_low = round(est_low * rate_to_usd, 1)
            usd_high = round(est_high * rate_to_usd, 1)
            krw_low = int(usd_low * USD_TO_KRW)
            krw_high = int(usd_high * USD_TO_KRW)
            
            usd_converted = f"${usd_low:g} ~ ${usd_high:g} USD"
            krw_converted = f"약 {krw_low:,} ~ {krw_high:,}원"
        else:
            price_display = f"{target_price_str} ±15%"
            usd_converted = ""
            krw_converted = ""

    final_result = {
        "kw_seed": analysis,
        "target_product": {
            "title": analysis.get("competitor_product", kw3),
            "specs": analysis.get("competitor_specs", "현지 표준 규격 및 원료"),
            "complaints": analysis.get("consumer_complaints", "대체재 대비 차별화 포인트 부재")
        },
        "retail_price": {
            "price": price_display,
            "usd_price": usd_converted,
            "krw_price": krw_converted,
            "badge": badge,
            "badge_desc": badge_desc,
            "unit_price": f"규격 단가 환산 ({currency})",
            "method": price_method,
            "sources": price_sources[:3],
        },
        "sales_channels": {
            "channels": retail_domains,
            "shelf": analysis.get("shelf_location", f"{primary_category} 전용 매대")
        },
        "price_strategy": {
            "pitch": analysis.get("value_pitch", ""),
            "positioning": "현지 물가 대비 프리미엄/기능성 타깃 포지셔닝"
        },
    }

    # 최종 안전망: 출력되는 모든 데이터 재귀 정제
    return sanitize_dict_recursively(final_result)
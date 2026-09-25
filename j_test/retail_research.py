import os
import re
import json
from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

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

def analyze_retail_market(product_name: str, country: str, strengths: str, raw_materials: str, target_price_str: str) -> dict:
    target_currency = COUNTRY_CURRENCY_MAP.get(country, "USD")

    step1_prompt = f"""
    당신은 글로벌 1위 식료품 유통망의 시니어 카테고리 바이어(MD)이자 B2B 박람회 총괄 디렉터입니다.
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
    3. 슬로건 금지어 (★절대 금지):
       - "Elevate", "Discover", "Unleash", "Experience", "Taste the difference" 등 뻔한 AI 단어 절대 금지.
       - 제품의 구체적 원료(멸치, 생면, 채소 등)와 식사 상황을 담아 직관적인 세일즈 카피를 작성하세요.
    4. 패키징 가이드의 구체성 강제:
       - "매력적인 패키지", "눈에 띄는 디자인" 같은 추상적 텍스트 금지.
       - 실제 디자이너/인쇄소에 넘길 수준의 구체적 스펙(반투명 윈도우, 소스 파우치 분리 포장, 인증 마크 위치, 픽토그램 등)을 제시하세요.
    5. 페어링 시식 연출 (실제 현지 식문화 결합):
       - {country} 현지 소비자가 국물 면 요리에 실제로 곁들이는 토핑/반찬과의 결합 연출(말레이시아 예: 바삭한 멸치 튀김 Ikan Bilis, 칠리 파디 간장 등)을 기획하세요.
    6. 바이어 피칭 & Q&A (제품 고유 팩트 기반):
       - "소비자 니즈 충족" 같은 모호한 문구 금지.
       - 원료와 대체 가치를 명시하여 바이어 매대의 객단가를 확장하는 논리로 작성하세요.
    7. retail_domains:
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
      "value_pitch": "구체적 원료와 조리 편의성을 담은 바이어 입점 피칭",
      "booth_solution": {{
        "main_slogan": "Elevate를 절대 쓰지 않은 직관적인 B2B 슬로건",
        "sub_copy": "원료와 섭취 가치를 담은 서브 카피",
        "visual_guide": "부스 벽면 라이프스타일 컷 디스플레이 지침",
        "pairing_title": "시그니처 페어링 존 명칭",
        "serving_protocol": "현지 식문화 토핑/가니쉬를 결합한 구체적 시연 서빙",
        "closing_pitch": "시식 직후 바이어에게 던질 구체적 클로징 멘트",
        "packaging_tip": "반투명 윈도우, 소스 분리 등 실물 패키징 디테일 지침",
        "shelf_position": "마트 매대 골든존 진열 가이드",
        "buyer_qa": {{
          "question": "바이어의 구체적 압박 질문",
          "answer": "원료 차별성과 프리미엄 매대 확장 논리를 담은 구체적 방어 스크립트"
        }}
      }}
    }}
    반드시 순수 JSON만 반환하세요.
    """

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": step1_prompt}]
    )
    raw_analysis = json.loads(response.choices[0].message.content)
    
    # 1차 한자 정제 적용
    analysis = sanitize_dict_recursively(raw_analysis)

    primary_category = analysis.get("primary_category", "식료품")
    kw3 = analysis.get("kw3", product_name)
    retail_domains = analysis.get("retail_domains", [])
    category_anchors = analysis.get("category_anchors", "")
    negative_anchors = analysis.get("negative_anchors", "")
    min_price = float(analysis.get("min_price", 0.0))
    max_price = float(analysis.get("max_price", min_price))
    currency = analysis.get("currency_symbol", target_currency).upper().strip()

    # Tavily 실측 검색
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
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": parse_prompt}]
            )
            parsed_data = json.loads(parse_res.choices[0].message.content)
            if parsed_data.get("is_valid") and parsed_data.get("price_range"):
                parsed_price_info = parsed_data
                search_success = True
    except Exception:
        search_success = False

    # 가격 결정 및 다중 통화 환산
    rate_to_usd = RATES_TO_USD.get(currency, 1.0)

    if search_success and parsed_price_info:
        badge = "현지 유통 실측가"
        badge_desc = "현지 주요 리테일 채널에서 Tavily API를 통해 실시간 수집된 실제 판매 가격입니다."
        price_display = parsed_price_info["price_range"]
        usd_converted = ""
        krw_converted = ""
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
            "unit_price": f"규격 단가 환산 ({currency})"
        },
        "sales_channels": {
            "channels": retail_domains,
            "shelf": analysis.get("shelf_location", f"{primary_category} 전용 매대")
        },
        "price_strategy": {
            "pitch": analysis.get("value_pitch", ""),
            "positioning": "현지 물가 대비 프리미엄/기능성 타깃 포지셔닝"
        },
        "booth_solution": analysis.get("booth_solution", {})
    }

    # 최종 안전망: 출력되는 모든 데이터 재귀 정제
    return sanitize_dict_recursively(final_result)
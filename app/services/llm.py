"""
부스 컨셉 자동 생성 서비스.

.env에 LLM_API_KEY(OpenAI)가 있으면 gpt-4o-mini로 생성하고,
없으면 등록 제품/박람회 정보를 바탕으로 한 규칙 기반 생성기로 대체한다
(README에 있던 "anthropic (또는 openai)" 패키지 자리를 채우는 부분).
"""

import json
import os

OPENAI_MODEL = "gpt-4o-mini"

CONCEPT_JSON_SCHEMA_HINT = """다음 JSON 형식으로만 답하세요 (설명 문장 없이 JSON만):
{
  "theme": "부스 테마 한 줄",
  "slogan": "슬로건 한 줄",
  "description": "테마에 대한 부연 설명 1~2문장",
  "selling_points": [
    {"level": "핵심", "title": "...", "desc": "..."},
    {"level": "핵심", "title": "...", "desc": "..."},
    {"level": "보조", "title": "...", "desc": "..."},
    {"level": "보조", "title": "...", "desc": "..."}
  ],
  "events": [
    {"tag": "시식·경품 이벤트", "title": "...", "desc": "...", "timing": "전일 운영"},
    {"tag": "SNS 마케팅", "title": "...", "desc": "...", "timing": "상시"},
    {"tag": "인플루언서 마케팅", "title": "...", "desc": "...", "timing": "1~2회"},
    {"tag": "B2B 상담", "title": "...", "desc": "...", "timing": "예약제"}
  ],
  "target_buyers": ["...", "...", "...", "..."]
}"""


def _build_prompt(expo, products):
    product_names = ", ".join(p.name for p in products)
    return (
        f"당신은 K-전통스낵 수출기업 '사부작'의 해외 박람회 부스 기획 담당자입니다.\n"
        f"아래 박람회에 참가하는 부스의 컨셉을 기획해주세요.\n\n"
        f"박람회명: {expo.name}\n"
        f"국가/도시: {expo.country_ko or expo.country} / {expo.city}\n"
        f"카테고리: {expo.category}\n"
        f"참가 제품: {product_names}\n\n"
        f"{CONCEPT_JSON_SCHEMA_HINT}"
    )


def _call_openai(expo, products):
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import openai
    except ImportError:
        return None

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=1500,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": _build_prompt(expo, products)}],
    )
    text = response.choices[0].message.content.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _fallback_generate(expo, products):
    """API 키가 없거나 호출 실패 시 쓰는 규칙 기반 생성기.
    실제 LLM 출력만큼 정교하진 않지만 화면이 비지 않도록 그럴듯한 값을 채운다."""
    product_names = [p.name for p in products]
    names_joined = ", ".join(product_names) or "사부작 제품"
    country = expo.country_ko or expo.country or "해당 시장"

    theme = f"{names_joined} × K-컬처 — {country}을(를) 사로잡는 일상 간식"
    slogan = f"한국의 전통 과자 — 마음을 잇는 맛"
    description = (
        f"{country} 현지 감성과 한국 전통 미감의 조화. 현지 음료와 어울리는 "
        f"따뜻한 색감의 부스 인테리어와 단정한 패턴 그래픽 요소를 포인트로 활용합니다."
    )

    selling_points = [
        {"level": "핵심", "title": "K-드라마·K-팝 연계",
         "desc": f"{product_names[0] if product_names else '제품'}이 등장하는 K-콘텐츠 장면·클립을 부스 디스플레이로 활용. 현지 팬덤 소비 유도."},
        {"level": "핵심", "title": "인스타그래머블 패키지",
         "desc": "현지 SNS 트렌드에 맞는 비주얼 포장. 자발적 포토 마케팅 유도."},
        {"level": "보조", "title": "현지 음료 페어링",
         "desc": "현지 대표 음료와의 페어링 제안으로 소비 접점 확대."},
        {"level": "보조", "title": "버라이어티 팩 라인업",
         "desc": "참가 제품 전체를 한 번에 경험하는 샘플러 팩. 온라인 진입 SKU로 최적."},
    ]

    events = [
        {"tag": "시식·경품 이벤트", "title": "시식 + 사부작 키링 증정",
         "desc": "시식 후 사부작 브랜드 키링 증정. 부스 방문 동선 유도에 효과적.", "timing": "전일 운영"},
        {"tag": "SNS 마케팅", "title": "K-스낵 챌린지 포토존",
         "desc": "릴스·틱톡 포맷에 맞는 배경 설치. 해시태그 이벤트 병행.", "timing": "상시"},
        {"tag": "인플루언서 마케팅", "title": "현지 인플루언서 초청",
         "desc": "현지 푸드 인플루언서 부스 초청. 라이브 방송 협의로 SNS 바이럴.", "timing": "1~2회"},
        {"tag": "B2B 상담", "title": "도매 바이어 상담",
         "desc": "현지 도매상 대상 MOQ·납기·가격 협의 집중 상담.", "timing": "예약제"},
    ]

    target_buyers = [
        f"{country} 프리미엄 식품 수입업체",
        f"{country} 아시아 식품 전문 에이전트",
        "온라인 식품 플랫폼 MD",
        "편의점/마트 바이어",
    ]

    return {
        "theme": theme,
        "slogan": slogan,
        "description": description,
        "selling_points": selling_points,
        "events": events,
        "target_buyers": target_buyers,
    }


def generate_booth_concept(expo, products):
    """expo(Exhibition), products(list[Product]) -> dict (스키마는 위 참고).
    LLM_API_KEY 있고 openai 패키지 설치돼 있으면 gpt-4o-mini로 실제 생성, 아니면 규칙 기반 폴백."""
    result = _call_openai(expo, products)
    if result:
        return result
    return _fallback_generate(expo, products)

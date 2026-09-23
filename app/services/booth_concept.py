"""부스 컨셉 자동 생성 서비스.

sabuzak.db(Exhibition) + 등록 제품(Product) + 구글 트렌드(pytrends) 데이터를
모아 app.prompts.booth_concept의 프롬프트로 LLM을 호출하고, 응답을
app.schemas.booth_concept.BoothConcept로 검증한다. OPENAI_API_KEY가 없거나
호출/검증에 실패하면 규칙 기반 폴백으로 대체해 화면이 비지 않게 한다.
"""

import json
import os

import pycountry
from pydantic import ValidationError

from app.prompts.booth_concept import NEGATIVE_PROMPT, SYSTEM_PROMPT, build_user_prompt
from app.schemas.booth_concept import BoothConcept
from app.services.hscode import resolve_country_iso
from app.services.openai_client import get_client

OPENAI_MODEL = "gpt-4o"


def _format_date(value):
    s = str(value or "")
    if len(s) != 8 or not s.isdigit():
        return s
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}"


def _build_expo_text(expo):
    country = expo.country_ko or expo.country or "-"
    intro = (expo.intro_ko or expo.intro or "-").strip()
    if len(intro) > 400:
        intro = intro[:400] + "..."
    return (
        f"박람회명: {expo.name}\n"
        f"개최 국가/도시: {country} / {expo.city or '-'}\n"
        f"일정: {_format_date(expo.start_date)} ~ {_format_date(expo.end_date)}\n"
        f"카테고리: {expo.category or '-'}\n"
        f"테마/소개: {intro}"
    )


def _build_product_text(products):
    if not products:
        return "등록된 제품 없음"
    blocks = []
    for p in products:
        blocks.append(
            f"- 제품명: {p.name}\n"
            f"  원재료 특징: {p.ingredients or '-'}\n"
            f"  보유 인증: {p.certifications or '-'}\n"
            f"  핵심 강점: {p.strengths or '-'}\n"
            f"  목표 가격대/단위중량: {p.target_price or '-'}"
        )
    return "\n".join(blocks)


def _build_trends_text(trends_data):
    top = (trends_data or {}).get("top_queries") or []
    rising = (trends_data or {}).get("rising_queries") or []
    if not top and not rising:
        return "트렌드 데이터 없음 (참고하지 말고 박람회·제품 정보로만 기획할 것)"
    return (
        f"상위 검색어(Top Queries): {', '.join(top) or '-'}\n"
        f"급상승 검색어(Rising Queries): {', '.join(rising) or '-'}"
    )


def _resolve_geo(country_name):
    iso3 = resolve_country_iso(country_name)
    if not iso3:
        return None
    country = pycountry.countries.get(alpha_3=iso3)
    return country.alpha_2 if country else None


def fetch_trends_data(expo, products, max_keywords=5, max_results=8):
    """개최국 기준 pytrends 관련 검색어(top/rising)를 모은다.
    pytrends는 스크레이핑 기반이라 자주 실패/차단되므로, 실패 시 그냥 빈 데이터로
    돌아간다(프롬프트가 빈 트렌드 데이터를 무시하도록 이미 지침되어 있음)."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return {"top_queries": [], "rising_queries": []}

    country = expo.country_ko or expo.country
    geo = _resolve_geo(country) or ""
    keywords = list(dict.fromkeys([p.name for p in products if p.name]))[:max_keywords]
    if not keywords:
        return {"top_queries": [], "rising_queries": []}

    top_queries, rising_queries = [], []
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(5, 10))
        pytrends.build_payload(keywords, geo=geo, timeframe="today 12-m")
        related = pytrends.related_queries()
        for kw_result in (related or {}).values():
            top_df = (kw_result or {}).get("top")
            if top_df is not None and not top_df.empty:
                top_queries.extend(top_df["query"].tolist())
            rising_df = (kw_result or {}).get("rising")
            if rising_df is not None and not rising_df.empty:
                rising_queries.extend(rising_df["query"].tolist())
    except Exception:
        return {"top_queries": [], "rising_queries": []}

    dedup = lambda items: list(dict.fromkeys(items))[:max_results]
    return {"top_queries": dedup(top_queries), "rising_queries": dedup(rising_queries)}


def _call_llm(expo_text, product_text, trends_text):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    user_prompt = build_user_prompt(expo_text, product_text, trends_text)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    client = get_client()
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=OPENAI_MODEL,
                max_tokens=2000,
                response_format={"type": "json_object"},
                messages=messages,
            )
            text = response.choices[0].message.content.strip()
            data = json.loads(text)
            return BoothConcept.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            if attempt == 0:
                messages.append({"role": "assistant", "content": text})
                messages.append({
                    "role": "user",
                    "content": f"응답이 스키마와 맞지 않습니다 ({e}). 설명 없이 스키마에 맞는 JSON만 다시 반환하세요.",
                })
                continue
            return None
        except Exception:
            return None
    return None


def _fallback_generate(expo, products):
    """API 키가 없거나 호출/검증에 실패했을 때 쓰는 규칙 기반 생성기."""
    product_names = [p.name for p in products] or ["사부작 제품"]
    names_joined = ", ".join(product_names)
    country = expo.country_ko or expo.country or "해당 시장"

    return BoothConcept.model_validate({
        "booth_theme": {
            "title": f"{names_joined} × K-컬처 — {country}을(를) 사로잡는 일상 간식",
            "slogan": "한국의 전통 맛 — 마음을 잇는 한 입",
            "description": (
                f"{country} 현지 감성과 한국 전통 미감의 조화. 따뜻한 색감의 부스 인테리어와 "
                f"단정한 패턴 그래픽 요소를 포인트로 활용합니다."
            ),
        },
        "selling_points": [
            {"badge": "핵심", "title": "K-콘텐츠 연계 비주얼",
             "description": f"{product_names[0]}이(가) 등장하는 K-콘텐츠 장면을 부스 디스플레이로 활용, 현지 팬덤 소비 유도."},
            {"badge": "핵심", "title": "인스타그래머블 패키지",
             "description": "현지 SNS 트렌드에 맞는 비주얼 포장으로 자발적 포토 마케팅 유도."},
            {"badge": "보조", "title": "현지 음료 페어링",
             "description": "현지 대표 음료와의 페어링 제안으로 소비 접점 확대."},
        ],
        "event_plans": [
            {"id": "01", "title": "시식 + 선호도 스티커 투표", "tag": "시식·리서치",
             "schedule": "전일 운영", "description": "현지 입맛 대상 시식 후 스티커 투표로 시장 반응 조사."},
            {"id": "02", "title": "SNS 인증샷 포토존", "tag": "SNS·체험",
             "schedule": "상시", "description": "포토존에서 사진 촬영 후 해시태그 인증 시 소정의 경품 추첨."},
            {"id": "03", "title": "현장 번들 샘플 팩 증정", "tag": "현장 혜택",
             "schedule": "수량 소진 시", "description": "바이어 대상 수출용 샘플 팩 현장 한정 배포."},
            {"id": "04", "title": "도매 바이어 상담", "tag": "B2B 상담",
             "schedule": "예약제", "description": "현지 도매상 대상 MOQ·납기·가격 협의 집중 상담."},
        ],
        "target_buyers": [
            f"{country} 프리미엄 식품 수입업체",
            f"{country} 아시아 식품 전문 에이전트",
            "온라인 식품 플랫폼 MD",
            "편의점/마트 바이어",
        ],
        "image_generation": {
            "prompt": (
                f"A realistic 3D architectural rendering of a food exhibition booth for "
                f"{product_names[0]} at {expo.name}, photorealistic, 8k, octane render, "
                f"wide angle view, warm wood accents, illuminated backwall signage, front "
                f"tasting counter"
            ),
            "negative_prompt": NEGATIVE_PROMPT,
        },
    })


def generate_booth_concept(expo, products, trends_data=None) -> dict:
    """expo(Exhibition), products(list[Product]) -> dict (app.schemas.booth_concept.BoothConcept 형태).
    trends_data를 안 주면 pytrends로 직접 조회를 시도한다."""
    if trends_data is None:
        trends_data = fetch_trends_data(expo, products)

    expo_text = _build_expo_text(expo)
    product_text = _build_product_text(products)
    trends_text = _build_trends_text(trends_data)

    result = _call_llm(expo_text, product_text, trends_text)
    if result is None:
        result = _fallback_generate(expo, products)

    return result.model_dump()

"""부스 컨셉 자동 생성 서비스.

sabuzak.db(Exhibition) + 등록 제품(Product) + v15 트렌드 분석 결과(또는 pytrends) 데이터를
모아 app.prompts.booth_concept의 프롬프트로 LLM을 호출하고, 응답을
app.schemas.booth_concept.BoothConcept로 검증한다. OPENAI_API_KEY가 없거나
호출/검증에 실패하면 규칙 기반 폴백으로 대체해 화면이 비지 않게 한다.
"""

import base64
import json
import os

import pycountry
from pydantic import ValidationError

from app.prompts.booth_concept import NEGATIVE_PROMPT, SYSTEM_PROMPT, build_user_prompt
from app.schemas.booth_concept import BoothConcept
from app.services.hscode import resolve_country_iso
from app.services.openai_client import get_client

# 환경 변수에 지정된 모델이 있으면 우선 사용하고, 없으면 기본 모델 사용
OPENAI_MODEL = os.getenv("V12_BOOTH_MODEL", "gpt-4o")
IMAGE_MODEL = os.getenv("V12_IMAGE_MODEL", "gpt-image-1")


def _format_date(value):
    s = str(value or "")
    if len(s) != 8 or not s.isdigit():
        return s
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}"


def _company_name(company, products):
    """부스 간판에 쓸 이름: 기업명 > 제품 브랜드명 > 첫 제품명."""
    name = (company or "").strip()
    if not name:
        name = next((p.brand.strip() for p in products if p.brand and p.brand.strip()), "")
    if not name:
        name = next((p.name.strip() for p in products if p.name and p.name.strip()), "")
    return name


SIGN_SUFFIX = (
    'The fascia sign and main backwall read exactly "{name}" in bold clean sans-serif lettering, '
    "no other readable text, no gibberish text"
)


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


def _build_product_text(products, company=""):
    if not products:
        return "등록된 제품 없음"
    blocks = [f"[출품 기업명] {_company_name(company, products) or '-'}"]
    for p in products:
        blocks.append(
            f"- 제품명: {p.name}\n"
            f"  브랜드명: {p.brand or '-'}\n"
            f"  제품 형태: {p.product_form or '-'}\n"
            f"  원재료 특징: {p.ingredients or '-'}\n"
            f"  보유 인증: {p.certifications or '-'}\n"
            f"  핵심 강점: {p.strengths or '-'}\n"
            f"  목표 가격대/단위중량: {p.target_price or '-'}"
        )
    return "\n".join(blocks)


def _build_trends_text(trends_data):
    """v15 트렌드 분석 결과(1~3번) 또는 기본 pytrends 데이터를 교차 분석용 텍스트로 가공한다."""
    if not trends_data:
        return "트렌드 데이터 없음 (참고하지 말고 박람회·제품 정보로만 기획할 것)"

    # v15의 트렌드 분석 전체 데이터가 넘어왔을 경우 (1~3번 심층 데이터 파싱)
    if any(k in trends_data for k in ("section1", "section2", "research")):
        lines = []
        
        # 1. 연관 검색어 클러스터링
        s1 = trends_data.get("section1") or {}
        if s1.get("clusters"):
            kw_list = []
            for c in s1["clusters"]:
                for k in c.get("keywords", []):
                    kw_name = k.get("keyword")
                    if kw_name:
                        if k.get("is_breakout"):
                            kw_list.append(f"{kw_name}(급등)")
                        else:
                            kw_list.append(kw_name)
            if kw_list:
                lines.append(f"① [검색 트렌드 & 급등 키워드]: {', '.join(kw_list[:15])}")

        # 2. 리테일 벤치마킹 & 가격 USP
        s2 = trends_data.get("section2") or {}
        rp = s2.get("retail_price") or {}
        tp = s2.get("target_product") or {}
        strat = s2.get("price_strategy") or {}
        sc = s2.get("sales_channels") or {}
        
        retail_parts = []
        if rp.get("price"):
            retail_parts.append(f"현지 타깃가 {rp.get('price')}")
        if strat.get("positioning"):
            retail_parts.append(f"포지셔닝: {strat.get('positioning')}")
        if tp.get("complaints"):
            retail_parts.append(f"현지 소비자 페인포인트: {tp.get('complaints')}")
        if sc.get("channels"):
            retail_parts.append(f"주요 유통 채널: {', '.join(sc.get('channels')[:3])}")
        
        if retail_parts:
            lines.append(f"② [리테일 & 경쟁 전략]: {' | '.join(retail_parts)}")

        # 3. 현지 시장 트렌드 기사 분석
        r = trends_data.get("research") or {}
        cards = r.get("cards") or []
        research_parts = []
        for c in cards:
            title = c.get("title")
            conc = (c.get("conclusion") or {}).get("text")
            if title and conc:
                research_parts.append(f"{title}: {conc[:100]}")
        if research_parts:
            lines.append(f"③ [현지 시장 트렌드 인사이트]: {' / '.join(research_parts[:3])}")

        if lines:
            return "\n".join(lines)

    # 기존 pytrends 형태(top_queries, rising_queries)인 경우 폴백
    top = trends_data.get("top_queries") or []
    rising = trends_data.get("rising_queries") or []
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
    """개최국 기준 pytrends 관련 검색어(top/rising)를 모은다."""
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
                max_tokens=4000,
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


def _fallback_generate(expo, products, company=""):
    """API 키가 없거나 호출/검증에 실패했을 때 쓰는 규칙 기반 생성기."""
    product_names = [p.name for p in products] or ["FairMate 제품"]
    names_joined = ", ".join(product_names)
    country = expo.country_ko or expo.country or "해당 시장"
    sign_name = _company_name(company, products) or product_names[0]

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
        ],
        "target_buyers": [
            f"{country} 프리미엄 식품 수입업체",
            f"{country} 아시아 식품 전문 에이전트",
            "온라인 식품 플랫폼 MD",
            "편의점/마트 바이어",
        ],
        "visitor_journey": {
            "sec3": {
                "headline": f"시선을 멈추는 {product_names[0]}의 시그니처 비주얼",
                "goal": "지나가는 바이어 시선 확보 및 호기심 유발",
                "message": f"K-프리미엄의 새로운 기준, {product_names[0]}을(를) 만나보세요.",
                "visitor_actions": ["상단 헤더 간판 및 대형 백월 확인", "걸음을 멈추고 부스 내부 응시"]
            },
            "sec30": {
                "headline": "직접 맛보고 경험하는 1:1 테이스팅",
                "goal": "시식 경험을 통한 제품 USP 즉각 전달",
                "message": "현지 음료와 가장 잘 어울리는 맛입니다. 시식 한번 해보시겠어요?",
                "visitor_actions": ["시식대 앞 접근", "샘플 시식 및 패키지 실물 확인"]
            },
            "min3": {
                "headline": "B2B 공급 단가 및 유통 파트너십 제안",
                "goal": "상담석 착석 및 구체적 계약 조건 협의",
                "message": f"{country} 시장 론칭 특전 프로모션과 MOQ 조건을 설명해 드리겠습니다.",
                "visitor_actions": ["상담석 착석", "브로슈어 검토 및 명함 교환"]
            }
        },
        "booth_3d": {
            "main_visual": {
                "concept_ko": f"따뜻한 우드톤과 화이트가 어우러진 모던 K-디저트 부스",
                "concept_en": f"Modern K-dessert exhibition booth with warm wood accents",
                "key_structure": "LED 백라이트 상단 간판 및 인쇄 그래픽 패널"
            },
            "merchandising": {
                "zones": [
                    {"name": "메인 쇼케이스 존", "purpose": "실물 패키지 집중 조명 진열"},
                    {"name": "카탈로그 거치대", "purpose": "방문 바이어용 리플렛 비치"}
                ],
                "display_flow": "입구 브로슈어 배포 후 중앙 시식대로 자연스러운 유도"
            },
            "demonstration": {
                "title": "유리 스니즈가드가 있는 아일랜드 시식 카운터",
                "scenario": "위생적인 개별 시식 플레이트 제공"
            }
        },
        "image_generation": {
            "prompt": (
                f"A realistic photograph-style 3D rendering of a buildable trade show booth for {product_names[0]} at {expo.name}, "
                f"inside a bright, well-lit exhibition hall with ceiling trusses, grey hall carpet and neighboring booth walls softly visible, "
                f"eye-level wide-angle view from the aisle, evenly lit, natural soft shadows, "
                f"realistic materials (MDF panels, aluminum frame, printed fabric graphics, LED lightbox), standard 6x3 meter booth, "
                f"{SIGN_SUFFIX.format(name=sign_name)}, no people, empty booth, "
                f"a brochure/pamphlet display stand with printed catalogs, a tasting counter with glass sneeze guard and sample plates, "
                f"a product display shelf showcasing the actual product packaging, a small meeting table with chairs, warm wood accents"
            ),
            "negative_prompt": NEGATIVE_PROMPT,
        },
    })


def generate_booth_concept(expo, products, trends_data=None, company="") -> dict:
    """expo(Exhibition), products(list[Product]) -> dict (app.schemas.booth_concept.BoothConcept 형태)."""
    if trends_data is None:
        trends_data = fetch_trends_data(expo, products)

    expo_text = _build_expo_text(expo)
    product_text = _build_product_text(products, company)
    trends_text = _build_trends_text(trends_data)

    result = _call_llm(expo_text, product_text, trends_text)
    if result is None:
        result = _fallback_generate(expo, products, company)

    data = result.model_dump()

    # LLM이 회사명을 빠뜨렸을 때를 대비해 간판 문구를 프롬프트에 보장한다.
    sign_name = _company_name(company, products)
    image_gen = data.get("image_generation") or {}
    prompt = image_gen.get("prompt") or ""
    if sign_name and prompt and sign_name not in prompt:
        image_gen["prompt"] = f"{prompt.rstrip('. ')}. {SIGN_SUFFIX.format(name=sign_name)}."
        data["image_generation"] = image_gen

    return data


def generate_booth_image(prompt: str, negative_prompt: str = NEGATIVE_PROMPT) -> bytes:
    """image_generation.prompt로 실제 부스 렌더링 이미지를 생성해 PNG 바이트로 반환한다."""
    client = get_client()
    full_prompt = f"{prompt}\n\nAvoid: {negative_prompt}."
    response = client.images.generate(
        model=IMAGE_MODEL,
        prompt=full_prompt,
        size="1536x1024",
        quality="medium",
        n=1,
    )
    image = response.data[0]
    if image.b64_json:
        return base64.b64decode(image.b64_json)
    import requests
    return requests.get(image.url, timeout=30).content
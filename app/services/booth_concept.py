"""부스 컨셉 서비스.

기획은 v15 부스 기획(research.plan_booth_independent, 모델은 v15/model_upgrade의
V12_BOOTH_MODEL)이 하고, 여기서는 그 결과를 concept 화면 항목으로 옮기고
부스 이미지를 그린다.
"""

import base64
import os
import re

from app.services.openai_client import get_client

IMAGE_MODEL = os.getenv("V12_IMAGE_MODEL", "gpt-image-1")

NEGATIVE_PROMPT = (
    "people, staff, person, crowd, cluttered, messy, dark background, dim lighting, moody, "
    "dramatic shadows, cinematic, black void background, spotlight glow, cartoon, 3d glitch, "
    "low quality, blurry, distorted, cheap plastic, unrealistic sci-fi architecture, studio backdrop, "
    "oversized booth, floating objects, misspelled text, gibberish text, garbled letters, extra logos, watermark"
)

MAX_ZONES = 5
MAX_EVENTS = 3
MAX_TARGET_BUYERS = 4
ZONE_NUMBER = re.compile(r"^[0-9]+[.)]\s*")
RANKED_BUYER = re.compile(r"[0-9]+순위[는은]\s*([^,.]+?)(?:로|이며|이고|다)?[,.]")


def company_name(company, products):
    """부스 간판에 쓸 이름: 기업명 > 제품 브랜드명 > 첫 제품명."""
    name = (company or "").strip()
    if not name:
        name = next((p.brand.strip() for p in products if p.brand and p.brand.strip()), "")
    if not name:
        name = next((p.name.strip() for p in products if p.name and p.name.strip()), "")
    return name


def v15_form(expo, product):
    """v15 INPUT_FIELDS에 맞춘 입력값 (app.routes.exhibition._trend_v2_prefill과 같은 매핑)."""
    return {
        "name": product.name,
        "country": expo.country_ko or expo.country or "",
        "exhibition_name": expo.name or "",
        "exhibition_website": expo.website or "",
        "strengths": product.strengths or "",
        "ingredients": product.ingredients or "",
        "certifications": product.certifications or "",
        "price": product.target_price or "",
    }


def _text(value):
    return str(value or "").strip()


def _first_sentence(text, limit=40):
    first = re.split(r"(?<=[.!?。])\s+", _text(text), maxsplit=1)[0]
    return first if len(first) <= limit else first[:limit].rstrip() + "…"


def _target_buyers(text):
    """'1순위는 A로, … 2순위는 B다.' 형태에서 바이어 이름만 뽑는다. 형태가 다르면 첫 문장."""
    text = _text(text)
    ranked = [m.strip() for m in RANKED_BUYER.findall(text + ".") if m.strip()]
    if ranked:
        return ranked[:MAX_TARGET_BUYERS]
    return [_first_sentence(text, 80)] if text else []


def _visitor_journey(flow):
    flow = flow if isinstance(flow, dict) else {}
    journey = {}
    for src, dst in (("3s", "sec3"), ("30s", "sec30"), ("3min", "min3")):
        stage = flow.get(src)
        if isinstance(stage, dict):
            journey[dst] = {k: _text(stage.get(k)) for k in ("headline", "goal", "message")}
    return journey or None


def image_prompt(booth, product_name, expo_name, sign_name):
    """v15 메인 비주얼·슬로건·진열 존(이름+위치)으로 제품마다 다른 부스 이미지 설명을 만든다."""
    sections = booth.get("sections") or {}
    main_visual = sections.get("main_visual") or {}
    headline = _text((sections.get("slogan") or {}).get("main_en"))
    zones = [z for z in (sections.get("merchandising") or {}).get("zones") or [] if isinstance(z, dict)]

    parts = [
        f"A realistic photograph-style 3D rendering of a buildable trade show booth for {product_name} at {expo_name}, "
        "inside a bright, well-lit exhibition hall with ceiling trusses, grey hall carpet and neighboring booth walls "
        "softly visible, eye-level wide-angle view from the aisle, evenly lit, natural soft shadows, realistic materials "
        "(MDF panels, aluminum frame, printed fabric graphics, LED lightbox), no people, empty booth."
    ]
    concept = _text(main_visual.get("concept_en"))
    if concept:
        parts.append(f"Visual concept: {concept}.")
    if zones:
        layout = "; ".join(
            f"{ZONE_NUMBER.sub('', _text(z.get('name')))} at {_text(z.get('position'))[:160]}"
            for z in zones[:MAX_ZONES]
        )
        parts.append(f"Booth layout by zone (zone names are for placement only, do not print them): {layout}.")
    sign = f'The fascia sign reads exactly "{sign_name}"' if sign_name else "The fascia sign shows the brand name"
    if headline:
        sign += f' and the main backwall headline reads exactly "{headline}"'
    parts.append(f"{sign} in bold clean sans-serif lettering, no other readable text, no gibberish text.")
    return " ".join(parts)


def draft_fields(booth, product_name, expo_name, sign_name):
    """v15 부스 기획 결과 → ConceptDraft 항목 + 방문객 여정."""
    sections = booth.get("sections") or {}
    positioning = booth.get("positioning") or {}
    short = booth.get("short") or {}
    main_visual = sections.get("main_visual") or {}
    slogan = sections.get("slogan") or {}
    pairing = sections.get("signature_pairing") or {}
    demo_bullets = [b for b in (sections.get("demonstration") or {}).get("bullets") or [] if isinstance(b, dict)]

    slogan_text = _text(slogan.get("main_ko"))
    if _text(slogan.get("main_en")):
        slogan_text = f"{slogan_text} ({_text(slogan.get('main_en'))})" if slogan_text else _text(slogan.get("main_en"))

    selling_points = []
    if _text(positioning.get("core_message")):
        selling_points.append({"badge": "핵심", "title": short.get("core_message") or "핵심 메시지",
                               "description": _text(positioning.get("core_message"))})
    if _text(main_visual.get("key_message")):
        selling_points.append({"badge": "핵심", "title": "메인 비주얼 전략",
                               "description": _text(main_visual.get("key_message"))})
    if _text(pairing.get("item")):
        desc = _text(pairing.get("item"))
        if _text(pairing.get("intent")):
            desc = f"{desc} — {_text(pairing.get('intent'))}"
        selling_points.append({"badge": "보조", "title": "시그니처 페어링", "description": desc})

    events = [
        {"id": f"{i + 1:02d}", "tag": "시연·시식",
         "title": short.get(f"bullet.demonstration.{i}") or _first_sentence(b.get("text")),
         "schedule": "", "description": _text(b.get("text"))}
        for i, b in enumerate(demo_bullets[:MAX_EVENTS])
    ]

    return {
        "theme": _text(main_visual.get("concept_ko")) or slogan_text or product_name,
        "slogan": slogan_text,
        "description": _text(booth.get("summary")),
        "selling_points": selling_points,
        "events": events,
        "target_buyers": _target_buyers(positioning.get("target_buyer")),
        "visitor_journey": _visitor_journey(booth.get("visitor_flow")),
        "image_prompt": image_prompt(booth, product_name, expo_name, sign_name),
    }


def generate_booth_image(prompt: str, negative_prompt: str = NEGATIVE_PROMPT) -> bytes:
    """image_prompt로 실제 부스 렌더링 이미지를 생성해 PNG 바이트로 반환한다."""
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

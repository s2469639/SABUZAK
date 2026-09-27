"""부스 컨셉 서비스.

기획은 v15 부스 기획(research.plan_booth_independent, 모델은 v15/model_upgrade의
V12_BOOTH_MODEL)이 하고, 여기서는 그 결과를 concept 화면 항목으로 옮긴다.
"""

import re

MAX_EVENTS = 4
MAX_TARGET_BUYERS = 4
RANKED_BUYER = re.compile(r"[0-9]+순위[는은]\s*([^,.]+?)(?:로|이며|이고|다)?[,.]")


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


def draft_fields(booth, product_name):
    """v15 부스 기획 결과 → ConceptDraft 항목 + 바이어 어필 포인트."""
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
        {"id": f"{i + 1:02d}", "title": e["title"], "tag": e["type"], "summary": e["summary"], "why": e["why"],
         "steps": e["steps"], "details": e["details"], "reward": e["reward"], "prep": e["prep"]}
        for i, e in enumerate((booth.get("events") or [])[:MAX_EVENTS])
    ]
    if not events:   # 이벤트 항목이 없는 예전 결과는 시연 문장으로 대체
        events = [
            {"id": f"{i + 1:02d}", "tag": "시연·시식",
             "title": short.get(f"bullet.demonstration.{i}") or _first_sentence(b.get("text")),
             "summary": _text(b.get("text"))}
            for i, b in enumerate(demo_bullets[:MAX_EVENTS])
        ]

    return {
        "theme": _text(main_visual.get("concept_ko")) or slogan_text or product_name,
        "slogan": slogan_text,
        "description": _text(booth.get("summary")),
        "selling_points": selling_points,
        "events": events,
        "target_buyers": _target_buyers(positioning.get("target_buyer")),
        "buyer_appeal": booth.get("buyer_appeal") or [],
    }


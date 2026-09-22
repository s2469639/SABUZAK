"""제품명 -> HS코드 후보 추천."""

import json
import os
import sqlite3

from dotenv import load_dotenv
from openai import OpenAI

from hscode_lookup import find_registered_hscode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = "gpt-4o-mini"
MAX_HSCODE_CANDIDATES = 5


def get_openai_client():
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다 (.env 파일 확인).")
    return OpenAI(api_key=openai_key)


def _llm_recommend_hscodes(client, model, product_name, max_candidates):
    prompt = f"""당신은 무역 및 관세 품목분류 전문가입니다.
아래 제품이 해당할 수 있는 HS코드(6자리, 국제 공통 단위)를 추천해주세요.
- 제품명: {product_name}

각 후보마다 6자리 HS코드, 왜 이 코드에 해당할 수 있는지 이유, 확신도를 포함하고, 확신도가 높은 순서로 정렬하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"candidates": [
    {{"hscode": "123456", "reason": "...", "confidence": "높음"}},
    ...
]}}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)
    return data.get("candidates", [])[:max_candidates]


def recommend_hscodes(client, product_name, conn=None, model=DEFAULT_MODEL, max_candidates=MAX_HSCODE_CANDIDATES):
    registered = find_registered_hscode(product_name)
    candidates = _llm_recommend_hscodes(client, model, product_name, max_candidates)

    for c in candidates:
        c["verified"] = False
        c["official_name"] = None
        hscode = str(c.get("hscode") or "").strip()
        c["hscode"] = hscode
        
        if conn is not None and hscode:
            try:
                # 1차: 정확히 일치하는 코드 조회
                row = conn.execute(
                    "SELECT name_ko FROM hscode_master WHERE hscode=?", (hscode,)
                ).fetchone()
                
                # 2차: 안 맞으면 앞자리(6자리) 유사 코드로 관세청 공식 품명 가져오기
                if not row:
                    prefix_code = hscode[:6] + "%"
                    row = conn.execute(
                        "SELECT name_ko FROM hscode_master WHERE hscode LIKE ? LIMIT 1", (prefix_code,)
                    ).fetchone()

                if row and row[0]:
                    c["verified"] = True
                    c["official_name"] = row[0]
            except sqlite3.OperationalError:
                pass  

    if registered:
        matched = next((c for c in candidates if c["hscode"] == registered["hscode"]), None)
        if matched:
            matched["confidence"] = "확정"
            matched["verified"] = True
            matched["official_name"] = matched["official_name"] or registered["names"]
            matched["reason"] = f"사부작 등록 품목입니다. {matched['reason']}"
        else:
            candidates.insert(
                0,
                {
                    "hscode": registered["hscode"],
                    "reason": f"사부작이 이미 취급 품목으로 등록해둔 코드입니다 ({registered['names']}).",
                    "confidence": "확정",
                    "verified": True,
                    "official_name": registered["names"],
                },
            )
            candidates = candidates[:max_candidates]  
        candidates.sort(key=lambda c: 0 if c["confidence"] == "확정" else 1)

    return candidates
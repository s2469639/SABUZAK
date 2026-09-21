"""제품명 -> HS코드 후보 추천. market_research.py(시장/트렌드 조사)와는
완전히 독립된 기능이라 다른 화면에 이것만 따로 넣고 싶을 때는 이 파일의
recommend_hscodes()만 가져다 쓰면 된다 (Tavily API 키는 필요 없음,
OpenAI 키만 있으면 됨).

사부작이 이미 취급 품목으로 등록해둔 제품(hscode_items.py)이어도, 그 코드
하나로 단정 짓지 않고 LLM에게 다른 가능성도 항상 물어본다 (같은 제품도
분류 기준에 따라 여러 HS코드에 걸칠 수 있어서 — 예: 김부각도 해조류
분류/조제식료품 분류 둘 다 가능할 수 있음). 사부작 등록 코드는 결과에서
"확정"으로 표시해서 다른 AI 추정 후보들과 구분한다.

각 후보는 관세청 공식 데이터(hscode_master 테이블, build_hscode_lookup.py로
채워둔 게 있으면)로 대조해서 실제로 존재하는 코드인지 검증한다 - LLM이
그럴듯하지만 실존하지 않는 코드를 지어내는 걸 그대로 보여주지 않기 위함.

다른 페이지에서 쓰는 법:
    from hscode_recommend import get_openai_client, recommend_hscodes
    client = get_openai_client()
    candidates = recommend_hscodes(client, "gpt-4o-mini", "김부각")
    # candidates: [{"hscode", "reason", "confidence", "verified", "official_name"}, ...]
    # 화면에는 항상 "AI 추정이니 관세사/관세청 사전심사로 재확인하세요" 안내를 같이 보여줄 것

hscode_master 테이블(관세청 공식 데이터)로 검증까지 하려면 sqlite3 커넥션을
conn 인자로 넘기면 된다 (없으면 검증 없이 AI 추정만으로 반환, verified=False).
채우는 법: python build_hscode_lookup.py --file <data.go.kr에서 받은 파일>
"""

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
    """이 기능은 OpenAI 키만 필요하다 (Tavily 키는 시장조사 쪽에만 필요).
    키가 없으면 RuntimeError (Flask 요청 처리 중 sys.exit()을 부르면 서버
    전체가 죽어버리는 문제가 있어서 예외로 처리 — market_research.py의
    get_clients()와 같은 이유)."""
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다 (.env 파일 확인).")
    return OpenAI(api_key=openai_key)


def _llm_recommend_hscodes(client, model, product_name, max_candidates):
    """LLM 호출부. 제품명만 보고 HS코드 후보를 추천받는다."""
    prompt = f"""당신은 무역 및 관세 품목분류 전문가입니다.
아래 제품이 해당할 수 있는 HS코드(6자리, 국제 공통 단위)를 추천해주세요.
같은 제품이라도 원재료 기준으로 볼지, 가공 형태 기준으로 볼지에 따라 서로
다른 HS코드에 해당할 수 있습니다 (예: 해조류 가공식품은 수산물 분류와
조제식료품 분류 둘 다 가능). 가능성이 있는 코드를 최대 {max_candidates}개까지
전부 나열하세요.

- 제품명: {product_name}

각 후보마다 6자리 HS코드, 왜 이 코드에 해당할 수 있는지 이유, 확신도
(높음/중간/낮음)를 포함하고, 확신도가 높은 순서로 정렬하세요.

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
    """공개 인터페이스. 제품명 -> HS코드 후보 추천.

    반환: [{"hscode", "reason", "confidence", "verified", "official_name"}, ...]
    확신도는 "확정"(사부작 등록 품목) / "높음" / "중간" / "낮음" 중 하나.
    """
    registered = find_registered_hscode(product_name)
    candidates = _llm_recommend_hscodes(client, model, product_name, max_candidates)

    for c in candidates:
        c["verified"] = False
        c["official_name"] = None
        hscode = str(c.get("hscode") or "").strip()
        c["hscode"] = hscode
        if conn is not None and hscode:
            try:
                row = conn.execute(
                    "SELECT name_ko FROM hscode_master WHERE hscode=?", (hscode,)
                ).fetchone()
                if row and row[0]:
                    c["verified"] = True
                    c["official_name"] = row[0]
            except sqlite3.OperationalError:
                pass  # hscode_master 테이블이 아직 없음 (build_hscode_lookup.py 실행 전)

    if registered:
        matched = next((c for c in candidates if c["hscode"] == registered["hscode"]), None)
        if matched:
            # LLM도 같은 코드를 후보로 냈으면 그 항목을 "확정"으로 승격
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
            candidates = candidates[:max_candidates]  # 넘치면 AI 추천 중 마지막 것부터 잘림
        # 확정 항목이 맨 위로 오게 정렬(나머지는 LLM이 준 확신도 순서 유지)
        candidates.sort(key=lambda c: 0 if c["confidence"] == "확정" else 1)

    return candidates

"""v10b 대시보드 파이프라인: v10과 같고, OpenAI 모델만 상위 모델로 바꿔 쓴다 (model_upgrade.py).

- 섹션 1: trend_usp_v1 pytrends 연관 검색어 4단계 클러스터링 (trend_adapter.run_section1)
- 섹션 2: j_test 현지 리테일 벤치마킹 & 경쟁 제품 가격 (trend_adapter.run_section2)
- 섹션 3: tavily_v9 조사 결과 (소비자·경쟁 제품·바이어·유통·박람회·부스 요약 카드 + 근거 기사)
- 섹션 4: tavily_v9 부스 컨셉 (Tavily 조사를 쓰지 않고 OpenAI가 입력 정보 + 자체 조사로 기획)

각 폴더의 코드는 수정하지 않고 그대로 불러온다(tavily_v9/research.py의 run_research 한 번 호출로 3·4 섹션 결과가 같이 나옴).
섹션 1, 2, 3·4는 동시에 실행하고, 하나가 실패해도 나머지는 보여준다.
"""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

from country_names import to_english
from trend_adapter import run_section1, run_section2   # 반드시 tavily_v9보다 먼저 (constants 패키지 이름 충돌 정리)
import model_upgrade  # noqa: E402

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAVILY_DIR = os.path.join(ROOT_DIR, "tavily_v9")
RESEARCH_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research_cache.db")

INPUT_FIELDS = ["name", "country", "exhibition_name", "exhibition_website",
                "strengths", "ingredients", "certifications", "price"]


def _load_tavily_v9():
    """tavily_v9 폴더의 research·env_setup 모듈을 불러온다. 이 폴더에는 같은 이름의 모듈을 두지 않는다."""
    if TAVILY_DIR not in sys.path:
        sys.path.insert(0, TAVILY_DIR)
    import env_setup as tavily_env  # noqa: E402  (tavily_v9/env_setup.py)
    import research as tavily_research  # noqa: E402  (tavily_v9/research.py)
    return tavily_env, tavily_research


tavily_env, tavily_research = _load_tavily_v9()


def _upgrade_tavily_v9():
    """tavily_v9의 모델 이름을 바꾸고(저장 키·화면 표시에도 반영), OpenAI 클라이언트를 감싼다."""
    tavily_research.MODEL = model_upgrade.TASK_MODEL
    tavily_research.BOOTH_MODEL = model_upgrade.BOOTH_MODEL
    tavily_research.SELF_RESEARCH_MODEL = model_upgrade.BOOTH_MODEL
    original = tavily_research.get_clients

    def get_clients():
        client, tavily = original()
        return model_upgrade.wrap(client), tavily

    tavily_research.get_clients = get_clients


_upgrade_tavily_v9()


def _guard(fn, *args):
    """섹션 하나의 실패가 다른 섹션을 막지 않도록 결과와 오류를 함께 돌려준다."""
    try:
        return fn(*args), None
    except Exception as e:
        return None, str(e) or e.__class__.__name__


def _run_research(inputs, force):
    return tavily_research.run_research(
        inputs["name"], inputs["country_en"],
        exhibition_name=inputs["exhibition_name"], exhibition_website=inputs["exhibition_website"],
        company_profile={"strengths": inputs["strengths"], "ingredients": inputs["ingredients"],
                         "certifications": inputs["certifications"], "price_range": inputs["price"]},
        db_path=RESEARCH_DB_PATH, force=force)   # v10(gpt-4o) 결과와 캐시를 나눔


def research_view(result):
    """화면용으로 조사 결과를 정리: 질문별 근거 기사(발췌+출처)를 묶는다."""
    if not result:
        return None
    sources = {s["id"]: s for s in result.get("sources") or []}
    quotes = {q["id"]: q for q in result.get("quotes") or []}
    articles = {}
    for card in result.get("cards") or []:
        items = []
        for qid in card.get("quote_ids") or []:
            q = quotes.get(qid)
            if not q:
                continue
            src = sources.get((q.get("source_ids") or [None])[0], {})
            items.append({**q, "url": src.get("url", ""), "domain": src.get("domain", ""),
                          "title": src.get("title", ""), "source_count": len(q.get("source_ids") or [])})
        articles[card["qid"]] = items
    return {"articles": articles}


def run_dashboard(form: dict, force: bool = False) -> dict:
    inputs = {k: (form.get(k) or "").strip() for k in INPUT_FIELDS}
    if not inputs["name"] or not inputs["country"]:
        raise ValueError("제품명과 진출 대상 국가를 입력해 주세요.")
    inputs["country_en"] = to_english(inputs["country"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        s1 = pool.submit(_guard, run_section1, inputs, not force)
        s2 = pool.submit(_guard, run_section2, inputs)
        s34 = pool.submit(_guard, _run_research, inputs, force)
        section1, section1_error = s1.result()
        section2, section2_error = s2.result()
        research, research_error = s34.result()

    return {"inputs": inputs,
            "section1": section1, "section1_error": section1_error,
            "section2": section2, "section2_error": section2_error,
            "research": research, "research_error": research_error,
            "view": research_view(research),
            "models": model_upgrade.models_used()}

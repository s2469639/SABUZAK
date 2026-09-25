"""v13: 트렌드 조사(1~3번)와 부스 컨셉(4번)을 서로 다른 작업으로 실행한다.

트렌드 조사  (사부작 '트렌드 조사' 탭)
  1. 연관 검색어 4단계 클러스터링   pytrends + OpenAI
  2. 리테일 벤치마킹 & 경쟁 제품 가격  OpenAI + Tavily (가격: Tavily → OpenAI 웹 검색 → 추정가)
  3. 현지 시장 트렌드 분석           Tavily + OpenAI
부스 컨셉    (사부작 '부스 컨셉 기획' 버튼 페이지)
  4. 상위 OpenAI 모델 단독 기획 (입력 정보 + OpenAI 자체 웹 검색. 1~3번 결과는 쓰지 않음)
"""

import hashlib
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import jobs
import model_upgrade
import research
import retail_research
from country_names import to_english
from sections import TREND_STEPS, run_section1, run_section2

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DB_PATH = os.path.join(HERE, "cache.db")
BOOTH_CACHE_DAYS = 30

INPUT_FIELDS = ["name", "country", "exhibition_name", "exhibition_website",
                "strengths", "ingredients", "certifications", "price"]

TREND_SECTIONS = [  # (키, 로딩 화면 라벨, 진행률 비중, 단계 수)
    ("trend", "검색 트렌드", 30, TREND_STEPS),
    ("retail", "리테일 가격", 15, retail_research.RETAIL_STEPS),
    ("research", "시장 자료", 55, research.RESEARCH_STEPS),
]
BOOTH_SECTIONS = [("booth", "부스 기획", 100, research.BOOTH_STEPS)]
BOOTH_STAGE_CHIPS = ["자료 수집", "전략 수립", "기획안 작성", "바이어 관점 점검", "최종 확정"]


def trend_progress():
    return jobs.Progress(TREND_SECTIONS)


def booth_progress():
    return jobs.Progress(BOOTH_SECTIONS, stage_chips=BOOTH_STAGE_CHIPS, first_message="부스 기획을 준비하고 있어요")


def clean_inputs(form: dict) -> dict:
    inputs = {k: (form.get(k) or "").strip() for k in INPUT_FIELDS}
    if not inputs["name"] or not inputs["country"]:
        raise ValueError("제품명과 진출 대상 국가를 입력해 주세요.")
    inputs["country_en"] = to_english(inputs["country"])
    return inputs


def _guard(progress, key, fn, *args):
    """섹션 하나의 실패가 다른 섹션을 막지 않도록 결과와 오류를 함께 돌려준다."""
    try:
        result = fn(*args, progress=progress.reporter(key))
        progress.finish(key)
        return result, None
    except Exception as e:
        progress.finish(key, failed=True)
        return None, str(e) or e.__class__.__name__


def _company_profile(inputs):
    return {"strengths": inputs["strengths"], "ingredients": inputs["ingredients"],
            "certifications": inputs["certifications"], "price_range": inputs["price"]}


# ---------------------------------------------------------------------------
# 트렌드 조사 (1~3번)
# ---------------------------------------------------------------------------

def _run_research(inputs, force, progress=None):
    return research.run_research(inputs["name"], inputs["country_en"],
                                 exhibition_name=inputs["exhibition_name"],
                                 exhibition_website=inputs["exhibition_website"],
                                 company_profile=_company_profile(inputs), db_path=CACHE_DB_PATH, force=force,
                                 include_booth=False, progress=progress)


def research_view(result):
    """화면용: 질문별 근거 기사(발췌 + 출처)를 묶는다."""
    if not result:
        return None
    sources = {s["id"]: s for s in result.get("sources") or []}
    quotes = {q["id"]: q for q in result.get("quotes") or []}
    articles = {}
    for card in result.get("cards") or []:
        items = []
        for qid in card.get("quote_ids") or []:
            q = quotes.get(qid)
            if q:
                src = sources.get((q.get("source_ids") or [None])[0], {})
                items.append({**q, "url": src.get("url", ""), "domain": src.get("domain", ""),
                              "title": src.get("title", "")})
        articles[card["qid"]] = items
    return {"articles": articles}


def run_trend(form: dict, force: bool = False, progress=None) -> dict:
    inputs = clean_inputs(form)
    progress = progress or trend_progress()
    with ThreadPoolExecutor(max_workers=3) as pool:
        s1 = pool.submit(_guard, progress, "trend", run_section1, inputs, not force)
        s2 = pool.submit(_guard, progress, "retail", run_section2, inputs)
        s3 = pool.submit(_guard, progress, "research", _run_research, inputs, force)
        section1, section1_error = s1.result()
        section2, section2_error = s2.result()
        research_result, research_error = s3.result()
    return {"inputs": inputs,
            "section1": section1, "section1_error": section1_error,
            "section2": section2, "section2_error": section2_error,
            "research": research_result, "research_error": research_error,
            "view": research_view(research_result),
            "models": model_upgrade.models_used(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


# ---------------------------------------------------------------------------
# 부스 컨셉 (4번)
# ---------------------------------------------------------------------------

def _booth_cache_key(inputs, profile):
    skill = research.load_skill(research.BOOTH_SKILL)
    return hashlib.sha256(json.dumps({
        "v": research.VERSION, "m": model_upgrade.BOOTH_MODEL, "e": model_upgrade.BOOTH_EFFORT,
        "sk": skill["fingerprint"], "rv": research.BOOTH_REVIEW, "rb": research.REVISE_BELOW, "p": profile,
        "i": [inputs["name"], inputs["country_en"], inputs["exhibition_name"], inputs["exhibition_website"]],
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _plan_booth(inputs, force, progress=None):
    profile = {research.PROFILE_LABELS[k]: v[:300] for k, v in _company_profile(inputs).items() if v}
    key = _booth_cache_key(inputs, profile)
    conn = sqlite3.connect(CACHE_DB_PATH)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS booth_cache (k TEXT PRIMARY KEY, v TEXT, at REAL)")
        if not force:
            row = conn.execute("SELECT v, at FROM booth_cache WHERE k=?", (key,)).fetchone()
            if row and time.time() - row[1] < BOOTH_CACHE_DAYS * 86400:
                return {**json.loads(row[0]), "from_cache": True}
        client, _ = research.get_clients()
        booth = research.plan_booth_independent(client, inputs["name"], inputs["country_en"],
                                                inputs["exhibition_name"] or None,
                                                inputs["exhibition_website"] or None, profile, progress=progress)
        if booth is None:
            raise RuntimeError("부스 기획안을 만들지 못했습니다.")
        booth["from_cache"] = False
        conn.execute("INSERT OR REPLACE INTO booth_cache VALUES (?, ?, ?)",
                     (key, json.dumps(booth, ensure_ascii=False), time.time()))
        conn.commit()
        return booth
    finally:
        conn.close()


def run_booth(form: dict, force: bool = False, progress=None) -> dict:
    inputs = clean_inputs(form)
    progress = progress or booth_progress()
    booth, booth_error = _guard(progress, "booth", _plan_booth, inputs, force)
    return {"inputs": inputs, "booth": booth, "booth_error": booth_error,
            "models": model_upgrade.models_used(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


# ---------------------------------------------------------------------------
# 백그라운드 작업
# ---------------------------------------------------------------------------

def start_booth_job(form: dict, force: bool = False) -> str:
    clean_inputs(form)   # 입력 오류는 작업을 만들기 전에 바로 알린다
    return jobs.start("booth", run_booth, form, force, booth_progress())


def start_trend_job(form: dict, force: bool = False) -> dict:
    """트렌드 조사를 시작하면서 부스 기획도 뒤에서 함께 시작해 둔다 (버튼을 누를 때 기다리지 않도록)."""
    clean_inputs(form)
    trend_id = jobs.start("trend", run_trend, form, force, trend_progress())
    booth_id = jobs.start("booth", run_booth, form, force, booth_progress())
    jobs.get(trend_id)["links"]["booth_job_id"] = booth_id
    return {"job_id": trend_id, "booth_job_id": booth_id}

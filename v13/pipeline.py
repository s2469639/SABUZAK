"""v12 대시보드 파이프라인: 네 섹션을 동시에 실행하고 진행률을 기록한다.

- 섹션 1: 연관 검색어 4단계 클러스터링 (pytrends + OpenAI)
- 섹션 2: 리테일 벤치마킹 & 경쟁 제품 가격 (OpenAI + Tavily, 가격은 Tavily → OpenAI 웹 검색 → 추정가)
- 섹션 3: 현지 시장 트렌드 분석 (Tavily + OpenAI)
- 섹션 4: 부스 컨셉 (상위 OpenAI 모델 단독: 입력 정보 + OpenAI 자체 웹 검색. pytrends·Tavily 결과는 쓰지 않음)
하나가 실패해도 나머지는 보여준다.
"""

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

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

SECTIONS = {  # 키: (화면 이름, 진행률 비중, 단계 수)
    "trend": ("검색어 트렌드", 20, TREND_STEPS),
    "retail": ("리테일 가격", 10, retail_research.RETAIL_STEPS),
    "research": ("현지 시장 트렌드", 45, research.RESEARCH_STEPS),
    "booth": ("부스 컨셉", 25, research.BOOTH_STEPS),
}


# ---------------------------------------------------------------------------
# 진행률
# ---------------------------------------------------------------------------

class Progress:
    """섹션별로 '시작한 단계 수'를 세어 전체 %를 계산한다. 단계는 시작할 때 보고되므로 끝난 단계 = 시작 - 1."""

    def __init__(self):
        self._lock = threading.Lock()
        self.sections = {k: {"name": v[0], "weight": v[1], "total": v[2], "started": 0, "done": False,
                             "failed": False, "label": "대기 중"} for k, v in SECTIONS.items()}
        self.message = "분석을 준비하고 있습니다"

    def reporter(self, key):
        def report(label):
            with self._lock:
                s = self.sections[key]
                s["started"] += 1
                s["label"] = label
                self.message = f"{s['name']} · {label}"
        return report

    def finish(self, key, failed=False):
        with self._lock:
            s = self.sections[key]
            s["done"], s["failed"] = True, failed
            s["label"] = "실패" if failed else "완료"

    def percent(self):
        with self._lock:
            total = 0.0
            for s in self.sections.values():
                ratio = 1.0 if s["done"] else min(max(s["started"] - 1, 0), s["total"] - 1) / s["total"]
                total += s["weight"] * ratio
            return int(total)

    def snapshot(self):
        pct = self.percent()
        with self._lock:
            return {"percent": pct, "message": self.message,
                    "sections": [{"key": k, "name": s["name"], "label": s["label"], "done": s["done"],
                                  "failed": s["failed"]} for k, s in self.sections.items()]}


# ---------------------------------------------------------------------------
# 섹션 실행
# ---------------------------------------------------------------------------

def _guard(progress, key, fn, *args):
    """섹션 하나의 실패가 다른 섹션을 막지 않도록 결과와 오류를 함께 돌려준다."""
    try:
        result = fn(*args, progress=progress.reporter(key))
        progress.finish(key)
        return result, None
    except Exception as e:
        progress.finish(key, failed=True)
        return None, str(e) or e.__class__.__name__


def _profile(inputs):
    raw = {"strengths": inputs["strengths"], "ingredients": inputs["ingredients"],
           "certifications": inputs["certifications"], "price_range": inputs["price"]}
    return {research.PROFILE_LABELS[k]: v[:300] for k, v in raw.items() if v}


def _run_research(inputs, force, progress=None):
    """섹션 3: Tavily 조사만 (부스 기획은 섹션 4가 따로)."""
    raw = {"strengths": inputs["strengths"], "ingredients": inputs["ingredients"],
           "certifications": inputs["certifications"], "price_range": inputs["price"]}
    return research.run_research(inputs["name"], inputs["country_en"],
                                 exhibition_name=inputs["exhibition_name"],
                                 exhibition_website=inputs["exhibition_website"],
                                 company_profile=raw, db_path=CACHE_DB_PATH, force=force,
                                 include_booth=False, progress=progress)


def _booth_cache_key(inputs, profile):
    skill = research.load_skill(research.BOOTH_SKILL)
    return hashlib.sha256(json.dumps({
        "v": research.VERSION, "m": model_upgrade.BOOTH_MODEL, "e": model_upgrade.BOOTH_EFFORT,
        "sk": skill["fingerprint"], "rv": research.BOOTH_REVIEW, "rb": research.REVISE_BELOW, "p": profile,
        "i": [inputs["name"], inputs["country_en"], inputs["exhibition_name"], inputs["exhibition_website"]],
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _run_booth(inputs, force, progress=None):
    """섹션 4: 상위 OpenAI 모델 단독 부스 기획. 결과는 30일간 저장."""
    profile = _profile(inputs)
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
                          "title": src.get("title", "")})
        articles[card["qid"]] = items
    return {"articles": articles}


def clean_inputs(form: dict) -> dict:
    inputs = {k: (form.get(k) or "").strip() for k in INPUT_FIELDS}
    if not inputs["name"] or not inputs["country"]:
        raise ValueError("제품명과 진출 대상 국가를 입력해 주세요.")
    inputs["country_en"] = to_english(inputs["country"])
    return inputs


def run_dashboard(form: dict, force: bool = False, progress: Progress = None) -> dict:
    inputs = clean_inputs(form)
    progress = progress or Progress()
    with ThreadPoolExecutor(max_workers=4) as pool:
        s1 = pool.submit(_guard, progress, "trend", run_section1, inputs, not force)
        s2 = pool.submit(_guard, progress, "retail", run_section2, inputs)
        s3 = pool.submit(_guard, progress, "research", _run_research, inputs, force)
        s4 = pool.submit(_guard, progress, "booth", _run_booth, inputs, force)
        section1, section1_error = s1.result()
        section2, section2_error = s2.result()
        research_result, research_error = s3.result()
        booth, booth_error = s4.result()

    return {"inputs": inputs,
            "section1": section1, "section1_error": section1_error,
            "section2": section2, "section2_error": section2_error,
            "research": research_result, "research_error": research_error,
            "booth": booth, "booth_error": booth_error,
            "view": research_view(research_result),
            "models": model_upgrade.models_used(),
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


# ---------------------------------------------------------------------------
# 백그라운드 작업 (로딩 화면이 진행률을 물어봄)
# ---------------------------------------------------------------------------

JOB_TTL_SEC = 2 * 3600
_jobs = {}
_jobs_lock = threading.Lock()


def start_job(form: dict, force: bool = False) -> str:
    clean_inputs(form)   # 입력 오류는 작업을 만들기 전에 바로 알려준다
    job_id = uuid.uuid4().hex
    job = {"progress": Progress(), "status": "running", "result": None, "error": None, "created": time.time(),
           "form": form, "force": force}
    with _jobs_lock:
        for k in [k for k, j in _jobs.items() if time.time() - j["created"] > JOB_TTL_SEC]:
            del _jobs[k]
        _jobs[job_id] = job

    def work():
        try:
            job["result"] = run_dashboard(form, force=force, progress=job["progress"])
            job["status"] = "done"
        except Exception as e:
            job["error"] = str(e) or e.__class__.__name__
            job["status"] = "error"

    threading.Thread(target=work, daemon=True).start()
    return job_id


def get_job(job_id: str):
    with _jobs_lock:
        return _jobs.get(job_id)

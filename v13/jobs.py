"""백그라운드 작업과 진행률.

- Progress: 섹션별로 '시작한 단계 수'를 세어 전체 %를 계산하고, 로딩 화면에 보여줄 쉬운 문구를 만든다.
  내부 단계 이름(도구 이름이 들어 있음)은 로그용이고, 화면에는 FRIENDLY 문구만 보인다.
- 작업은 서버 메모리에 2시간 보관하고, 끝난 결과는 results/ 폴더에 JSON으로 저장한다(화면에는 표시하지 않음).
"""

import json
import logging
import os
import threading
import time
import uuid

logger = logging.getLogger("sabuzak.v13.jobs")

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")
JOB_TTL_SEC = 2 * 3600

# 내부 단계 이름 → 로딩 화면 문구
FRIENDLY = {
    # 검색 트렌드
    "국가 프로필 확인": "진출 국가 정보를 확인하고 있어요",
    "현지어 시드 검색어 생성": "현지 검색어를 준비하고 있어요",
    "Google 트렌드 연관 검색어 수집": "현지 검색 트렌드를 살펴보고 있어요",
    "검색어 4단계 분류": "검색어를 소비 단계별로 분류하고 있어요",
    "검색량·전년 대비 증감 측정": "검색량 변화를 계산하고 있어요",
    "클러스터 정리": "검색 트렌드를 정리하고 있어요",
    # 리테일 가격
    "경쟁 제품·유통 채널 분석": "경쟁 제품과 유통 채널을 분석하고 있어요",
    "현지 유통몰 판매가 검색 (Tavily)": "현지 판매 가격을 찾고 있어요",
    "가격 확인됨 · 추가 검색 생략": "판매 가격을 확인했어요",
    "OpenAI 웹 검색으로 판매가 확인": "경쟁 제품 가격을 한 번 더 확인하고 있어요",
    "가격 정리·환산": "가격을 원화로 환산하고 있어요",
    # 시장 자료
    "현지 검색어 준비": "조사 키워드를 준비하고 있어요",
    "국가별 주요 사이트 확인": "신뢰할 수 있는 현지 사이트를 고르고 있어요",
    "조사 기준 설정": "조사 기준을 세우고 있어요",
    "주요 사이트 검색 (Tavily)": "현지 시장 자료를 찾고 있어요",
    "원문 발췌": "핵심 내용을 발췌하고 있어요",
    "자료 충분성 판정": "자료가 충분한지 점검하고 있어요",
    "부족한 질문 일반 웹 보강": "부족한 자료를 보강하고 있어요",
    "보강 검색 생략 (자료 충분)": "필요한 자료를 모두 모았어요",
    "원문 대조 검증": "자료의 정확도를 확인하고 있어요",
    "질문별 요약 작성": "시장 인사이트를 요약하고 있어요",
    "정리 완료": "분석을 마무리하고 있어요",
    # 부스 기획
    "부스용 자체 웹 조사 (OpenAI)": "부스 기획을 위한 자료를 모으고 있어요",
    "전략 뼈대 (인사이트·빅 아이디어)": "핵심 전략을 세우고 있어요",
    "부스 기획안 초안 작성": "부스 기획안을 작성하고 있어요",
    "바이어 페르소나 채점": "기획안을 바이어 관점에서 점검하고 있어요",
    "채점 반영 수정": "기획안을 다듬고 있어요",
    "기준 통과 · 수정 생략": "기획안을 확정하고 있어요",
}


class Progress:
    """sections: [(키, 화면 이름, 비중, 단계 수)].
    단계는 시작할 때 보고되므로 끝난 단계 = 시작한 단계 - 1. finish()를 부르면 그 섹션은 100%.
    stage_chips를 주면(섹션이 하나인 작업) 로딩 화면 라벨을 섹션 대신 단계 이름으로 보여준다."""

    def __init__(self, sections, stage_chips=None, first_message="분석을 준비하고 있어요"):
        self._lock = threading.Lock()
        self.sections = {k: {"name": name, "weight": w, "total": n, "started": 0, "done": False, "failed": False}
                         for k, name, w, n in sections}
        self.stage_chips = stage_chips
        self.message = first_message

    def reporter(self, key):
        def report(label):
            with self._lock:
                self.sections[key]["started"] += 1
                self.message = FRIENDLY.get(label, self.message)
            logger.info("[%s] %s", key, label)
        return report

    def finish(self, key, failed=False):
        with self._lock:
            self.sections[key]["done"] = True
            self.sections[key]["failed"] = failed

    def percent(self):
        with self._lock:
            total, weights = 0.0, sum(s["weight"] for s in self.sections.values())
            for s in self.sections.values():
                ratio = 1.0 if s["done"] else min(max(s["started"] - 1, 0), s["total"] - 1) / s["total"]
                total += s["weight"] * ratio
            return int(total * 100 / weights)

    def snapshot(self):
        pct = self.percent()
        with self._lock:
            if self.stage_chips:
                s = next(iter(self.sections.values()))
                current = s["total"] if s["done"] else max(s["started"] - 1, 0)
                chips = [{"name": name, "done": i < current, "active": i == current and not s["done"],
                          "failed": s["failed"] and i == current} for i, name in enumerate(self.stage_chips)]
            else:
                chips = [{"name": s["name"], "done": s["done"] and not s["failed"], "active": not s["done"],
                          "failed": s["failed"]} for s in self.sections.values()]
            return {"percent": pct, "message": self.message, "chips": chips}


_jobs = {}
_lock = threading.Lock()


def save_result(kind, job_id, data):
    """전체 결과(채점·검토 의견 등 화면에 없는 정보 포함)를 results/<종류>_<작업 id>.json으로 저장."""
    try:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"{kind}_{job_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        return path
    except OSError as e:
        logger.warning("결과 파일 저장 실패: %s", e)
        return None


def start(kind, fn, form, force, progress):
    """fn(form, force, progress)를 백그라운드로 실행하고 작업 id를 돌려준다."""
    job_id = uuid.uuid4().hex
    job = {"kind": kind, "progress": progress, "status": "running", "result": None, "error": None,
           "created": time.time(), "form": form, "force": force, "links": {}}
    with _lock:
        for k in [k for k, j in _jobs.items() if time.time() - j["created"] > JOB_TTL_SEC]:
            del _jobs[k]
        _jobs[job_id] = job

    def work():
        try:
            job["result"] = fn(form, force=force, progress=progress)
            job["status"] = "done"
            save_result(kind, job_id, {"inputs": form, **job["result"]})
        except Exception as e:
            logger.exception("%s 작업 실패", kind)
            job["error"] = str(e) or e.__class__.__name__
            job["status"] = "error"

    threading.Thread(target=work, daemon=True).start()
    return job_id


def get(job_id, kind=None):
    with _lock:
        job = _jobs.get(job_id)
    if job and kind and job["kind"] != kind:
        return None
    return job

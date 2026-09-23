"""Bounded, single-process jobs for the local application."""
import hashlib
import json
import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .research_service import research

pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="research")
lock = threading.Lock()
jobs, active = {}, {}
MAX_PENDING = 8


def key_for(specs):
    return hashlib.sha256(json.dumps(specs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def public_error(exc):
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if any(x in name + message for x in ("authentication", "unauthorized", "api key", "api_key", "401", "설정되어")):
        return "API 키가 없거나 유효하지 않습니다. 프로젝트의 .env 설정을 확인해주세요."
    if any(x in name + message for x in ("ratelimit", "429", "quota", "credit")):
        return "서비스 사용 한도에 도달했습니다. 한도를 확인한 뒤 다시 시도해주세요."
    if any(x in name for x in ("timeout", "connection")):
        return "외부 서비스 응답이 지연되었습니다. 잠시 후 다시 시도해주세요."
    return "조사를 완료하지 못했습니다. 잠시 후 다시 시도해주세요."


def start(specs, force=False):
    key = key_for(specs)
    with lock:
        now = time.monotonic()
        for jid in list(jobs):
            if jobs[jid]["state"] != "running" and now - jobs[jid]["created"] > 3600:
                del jobs[jid]
        if key in active:
            return active[key]
        if len(active) >= MAX_PENDING:
            raise RuntimeError("조사 요청이 많습니다. 잠시 후 다시 시도해주세요.")
        if len(jobs) >= 100:
            for jid in list(jobs):
                if jobs[jid]["state"] != "running":
                    del jobs[jid]
                    break
        jid = secrets.token_urlsafe(24)
        jobs[jid] = {"state": "running", "created": now}
        active[key] = jid
    pool.submit(_work, jid, key, specs, force)
    return jid


def _work(jid, key, specs, force):
    try:
        result = research(specs, force)
        outcome = {"state": "done", "result": result}
    except Exception as exc:
        logging.getLogger(__name__).warning("Research failed: %s", type(exc).__name__)
        outcome = {"state": "error", "message": public_error(exc)}
    with lock:
        jobs[jid].update(outcome)
        active.pop(key, None)


def snapshot(jid):
    with lock:
        job = jobs.get(jid)
        return {k: v for k, v in job.items() if k != "created"} if job else None

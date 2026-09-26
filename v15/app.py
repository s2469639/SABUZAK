#!/usr/bin/env python3
"""페어메이트 박람회 준비 — 트렌드 조사 탭 & 부스 컨셉 기획 (v13/v15).

화면
  /                 트렌드 조사 (1. 검색 트렌드 · 2. 리테일 가격 · 3. 현지 시장 트렌드)
  /trend/<id>       트렌드 조사 결과 (오른쪽 위 '부스 컨셉 기획 →' 버튼)
  /booth, /booth/<id>   부스 컨셉 기획 (4번) — 따로 실행하거나, 트렌드 조사와 함께 미리 실행된 결과를 봄
JSON (메인 웹 연동용)
  POST /api/trend/start → {job_id, booth_job_id}   GET /api/trend/<id>/progress · /api/trend/<id>
  POST /api/booth/start → {job_id}                 GET /api/booth/<id>/progress · /api/booth/<id>

실행: python app.py  ->  http://127.0.0.1:5069
"""

import logging
import os
import re
from urllib.parse import urlencode

from flask import Flask, jsonify, redirect, render_template, request

import env_setup
import jobs
import model_upgrade
from services import INPUT_FIELDS, run_booth, run_trend, start_booth_job, start_trend_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sabuzak.v13")

PORT = int(os.getenv("V13_PORT", "5069"))
QUESTION_LABELS = {"Q1": "CONSUMER", "Q2": "COMPETITION", "Q3": "BUYER & CHANNEL", "Q4": "TRADE SHOW & BOOTH"}

app = Flask(__name__)


@app.template_filter("split_points")
def split_points(text, limit=4):
    """리테일 분석의 긴 문장을 불릿용으로 나눈다 (문장 끝·쉼표 기준, 너무 짧게 쪼개지면 원문 그대로)."""
    text = str(text or "").strip()
    if not text:
        return []
    parts = [p.strip(" .·-") for p in re.split(r"(?<=[.!?。])\s+|(?<=다)\.\s*|\s*[;·•]\s*|\n+", text)]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        parts = [p.strip() for p in text.split(", ") if p.strip()]
    if len(parts) <= 1 or any(len(p) < 4 for p in parts):
        return [text]
    return parts[:limit]


@app.template_filter("chips")
def chips(text, limit=6):
    """'400g, 밀키트, 멸치 육수와 생면 포함' → 칩 목록."""
    parts = [p.strip() for p in re.split(r"[,/·]|\s+\+\s+", str(text or "")) if p.strip()]
    return parts[:limit]


def _form_from(source):
    return {f: (source.get(f) or "").strip() for f in INPUT_FIELDS}


def _empty_form():
    return {f: "" for f in INPUT_FIELDS}


def _booth_link(form, booth_job_id=None):
    if booth_job_id:
        return f"/booth/{booth_job_id}"
    return "/booth?" + urlencode({k: v for k, v in form.items() if v})


# 수정 포인트 1: job_id 파라미터 추가 전달 (뒤로가기 및 상태 보존용)
def _trend_page(form, data=None, error=None, force=False, booth_job_id=None, job_id=None):
    return render_template("trend.html", form=form, data=data, error=error, force=force,
                           question_labels=QUESTION_LABELS, 
                           booth_link=_booth_link(form, booth_job_id),
                           job_id=job_id)


def _booth_page(form, data=None, error=None, force=False, job_id=None, running=False):
    return render_template("booth.html", form=form, data=data, error=error, force=force,
                           job_id=job_id, running=running)


# ---------------------------------------------------------------------------
# 트렌드 조사
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def trend_index():
    """GET: 입력 화면. POST: 자바스크립트가 꺼진 브라우저용 (진행률 없이 끝날 때까지 기다림)."""
    if request.method == "GET":
        return _trend_page(_empty_form())
    form, force = _form_from(request.form), bool(request.form.get("force"))
    try:
        return _trend_page(form, run_trend(form, force=force), force=force)
    except ValueError as e:
        return _trend_page(form, error=str(e), force=force)
    except Exception as e:
        logger.exception("트렌드 조사 실패")
        return _trend_page(form, error=f"분석 중 오류가 발생했습니다: {e}", force=force)


# 수정 포인트 2: booth_job_id와 job_id를 템플릿에 안전하게 전달하도록 보완
@app.get("/trend/<job_id>")
def trend_result(job_id):
    job = jobs.get(job_id, "trend")
    if not job or job["status"] == "running":
        return redirect("/")
    booth_job_id = job.get("links", {}).get("booth_job_id")
    return _trend_page(job["form"], job["result"], job["error"], job["force"], 
                       booth_job_id=booth_job_id, job_id=job_id)


# ---------------------------------------------------------------------------
# 부스 컨셉
# ---------------------------------------------------------------------------

@app.route("/booth", methods=["GET", "POST"])
def booth_index():
    """GET: 부스 컨셉만 따로 실행하는 화면 (쿼리 문자열로 입력값을 미리 채울 수 있음).
    POST: 자바스크립트가 꺼진 브라우저용 (끝날 때까지 기다린 뒤 결과)."""
    if request.method == "GET":
        return _booth_page(_form_from(request.args))
    form, force = _form_from(request.form), bool(request.form.get("force"))
    try:
        return _booth_page(form, run_booth(form, force=force), force=force)
    except ValueError as e:
        return _booth_page(form, error=str(e), force=force)


@app.get("/booth/<job_id>")
def booth_result(job_id):
    job = jobs.get(job_id, "booth")
    if not job:
        return _booth_page(_empty_form(), error="부스 기획 작업을 찾지 못했습니다. 서버가 다시 시작되었을 수 있어요. 다시 실행해 주세요.")
    if job["status"] == "running":   # 트렌드 조사와 함께 시작된 작업이 아직 도는 중 → 로딩 화면에서 이어서 기다림
        return _booth_page(job["form"], job_id=job_id, running=True)
    return _booth_page(job["form"], job["result"], job["error"], job["force"], job_id=job_id)


# ---------------------------------------------------------------------------
# JSON API (로딩 화면 + 메인 웹 연동)
# ---------------------------------------------------------------------------

def _progress_json(job):
    snap = job["progress"].snapshot()
    if job["status"] == "done":
        snap["percent"] = 100
    return {**snap, "status": job["status"], "error": job["error"], **job["links"]}


@app.post("/api/trend/start")
def api_trend_start():
    try:
        ids = start_trend_job(_form_from(request.form or request.get_json(silent=True) or {}),
                              force=bool(request.values.get("force")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(ids)


@app.post("/api/booth/start")
def api_booth_start():
    try:
        job_id = start_booth_job(_form_from(request.form or request.get_json(silent=True) or {}),
                                 force=bool(request.values.get("force")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"job_id": job_id})


@app.get("/api/<kind>/<job_id>/progress")
def api_progress(kind, job_id):
    job = jobs.get(job_id, kind)
    if not job:
        return jsonify({"status": "missing", "error": "작업을 찾지 못했어요. 서버가 다시 시작되었을 수 있어요."}), 404
    return jsonify(_progress_json(job))


@app.get("/api/<kind>/<job_id>")
def api_result(kind, job_id):
    job = jobs.get(job_id, kind)
    if not job:
        return jsonify({"status": "missing"}), 404
    return jsonify({"status": job["status"], "error": job["error"], "result": job["result"], **job["links"]})


if __name__ == "__main__":
    env_setup.ensure_required_keys()   # OPENAI_API_KEY, TAVILY_API_KEY (최상위 SABUZAK/.env)
    try:
        from openai import OpenAI
        from http_compat import SAFE_HEADERS
        model_upgrade.check_models(OpenAI(api_key=os.getenv("OPENAI_API_KEY"), default_headers=SAFE_HEADERS))
    except Exception as e:
        print(f"모델 확인 건너뜀: {e}")
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=PORT, threaded=True)
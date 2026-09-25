#!/usr/bin/env python3
"""페어메이트 해외 박람회 준비 통합 대시보드 (v12).

한 화면에:
  1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링   (pytrends + OpenAI)
  2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석      (OpenAI + Tavily)
  3. 현지 시장 트렌드 분석 + 근거 기사 사이드바       (Tavily + OpenAI)
  4. 부스 컨셉 기획                                  (상위 OpenAI 모델 단독)

실행: python app.py  ->  http://127.0.0.1:5068
분석은 백그라운드에서 돌고, 화면은 /progress로 진행률을 받아 로딩 링을 채운다.
"""

import json
import logging
import os

from flask import Flask, abort, jsonify, redirect, render_template, request

import env_setup
import model_upgrade
from pipeline import INPUT_FIELDS, get_job, run_dashboard, start_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sabuzak.v12")

PORT = int(os.getenv("V12_PORT", "5068"))
QUESTION_LABELS = {"Q1": "CONSUMER", "Q2": "COMPETITION", "Q3": "BUYER & CHANNEL", "Q4": "TRADE SHOW & BOOTH"}

app = Flask(__name__)


def _form_from(source):
    return {f: (source.get(f) or "").strip() for f in INPUT_FIELDS}


def _page(form, data=None, error=None, force=False):
    return render_template("dashboard.html", form=form, data=data, error=error, force=force,
                           question_labels=QUESTION_LABELS,
                           raw_json=json.dumps(data, ensure_ascii=False, indent=2, default=str) if data else "")


@app.route("/", methods=["GET", "POST"])
def index():
    """GET: 입력 화면. POST: 자바스크립트가 꺼진 브라우저용 (진행률 없이 끝날 때까지 기다린 뒤 결과 화면)."""
    form = {f: "" for f in INPUT_FIELDS}
    data, error, force = None, None, False
    if request.method == "POST":
        form = _form_from(request.form)
        force = bool(request.form.get("force"))
        try:
            data = run_dashboard(form, force=force)
        except ValueError as e:
            error = str(e)
        except Exception as e:
            logger.exception("대시보드 분석 실패")
            error = f"분석 중 오류가 발생했습니다: {e}"
    return _page(form, data, error, force)


@app.post("/start")
def start():
    form = _form_from(request.form)
    try:
        job_id = start_job(form, force=bool(request.form.get("force")))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"job_id": job_id})


@app.get("/progress/<job_id>")
def progress(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"status": "missing", "error": "작업을 찾지 못했습니다 (서버가 다시 시작되었을 수 있습니다)."}), 404
    snap = job["progress"].snapshot()
    if job["status"] == "done":
        snap["percent"] = 100
    return jsonify({**snap, "status": job["status"], "error": job["error"]})


@app.get("/result/<job_id>")
def result(job_id):
    job = get_job(job_id)
    if not job:
        abort(404)
    if job["status"] == "running":
        return redirect("/")
    return _page(job["form"], job["result"], job["error"], job["force"])


if __name__ == "__main__":
    env_setup.ensure_required_keys()   # OPENAI_API_KEY, TAVILY_API_KEY (최상위 SABUZAK/.env를 읽고 없으면 물어봄)
    try:
        from openai import OpenAI
        from http_compat import SAFE_HEADERS
        model_upgrade.check_models(OpenAI(api_key=os.getenv("OPENAI_API_KEY"), default_headers=SAFE_HEADERS))
    except Exception as e:
        print(f"모델 확인 건너뜀: {e}")
    # threaded: 분석이 도는 동안에도 진행률 요청에 답하기 위해
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=PORT, threaded=True)

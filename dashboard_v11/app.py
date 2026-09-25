#!/usr/bin/env python3
"""해외 박람회 준비 통합 대시보드 (v11).

한 화면에:
  1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링   (trend_usp_v1 · pytrends)
  2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석      (j_test)
  3. 현지 웹 자료 조사 요약 + 근거 기사 사이드바      (tavily_v9 · Tavily)
  4. 부스 컨셉 기획                                  (Claude 마케팅 에이전트 · 경쟁 브리프 → 기획 → 채점 → 수정)

실행: python app.py  ->  http://127.0.0.1:5066
(5060·5061은 크롬 계열 브라우저가 SIP 전화용 포트라 차단(ERR_UNSAFE_PORT)하므로 쓰지 않음)
"""

import json
import logging
import os

from flask import Flask, render_template, request

from pipeline import INPUT_FIELDS, run_dashboard, tavily_env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sabuzak.dashboard_v11")

PORT = int(os.getenv("DASHBOARD_V11_PORT", "5066"))
QUESTION_LABELS = {"Q1": "CONSUMER", "Q2": "COMPETITION", "Q3": "BUYER & CHANNEL", "Q4": "TRADE SHOW & BOOTH"}

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    form = {f: "" for f in INPUT_FIELDS}
    data, error, force = None, None, False
    if request.method == "POST":
        form = {f: request.form.get(f, "").strip() for f in INPUT_FIELDS}
        force = bool(request.form.get("force"))
        try:
            data = run_dashboard(form, force=force)
        except ValueError as e:
            error = str(e)
        except Exception as e:
            logger.exception("대시보드 분석 실패")
            error = f"분석 중 오류가 발생했습니다: {e}"
    return render_template("dashboard.html", form=form, data=data, error=error, force=force,
                           question_labels=QUESTION_LABELS,
                           raw_json=json.dumps(data, ensure_ascii=False, indent=2, default=str) if data else "")


if __name__ == "__main__":
    tavily_env.ensure_required_keys()   # OPENAI_API_KEY, TAVILY_API_KEY, ANTHROPIC_API_KEY (.env를 읽고 없으면 물어봄)
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=PORT)

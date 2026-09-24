#!/usr/bin/env python3
"""검색 트렌드(trend_usp_v1) + 웹 자료(tavily_v5) 결합 진단 Flask 웹앱.

실행:
    pip install -r requirements.txt
    python app.py
    -> 브라우저에서 http://127.0.0.1:5090 접속
"""

import json
import logging
import os

from flask import Flask, render_template, request

from combined import run_combined, tavily_env, trend_usp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sabuzak.trend_tavily.app")

app = Flask(__name__)

FORM_FIELDS = trend_usp.PRODUCT_FIELDS + ["country", "exhibition_name", "exhibition_website"]


@app.route("/", methods=["GET", "POST"])
def index():
    combo = None
    error = None
    form = {field: "" for field in FORM_FIELDS}
    force = False

    if request.method == "POST":
        form = {field: request.form.get(field, "").strip() for field in FORM_FIELDS}
        force = bool(request.form.get("force"))
        try:
            combo = run_combined(form, form["country"], form["exhibition_name"], form["exhibition_website"],
                                 force=force)
        except (trend_usp.PipelineError, ValueError) as e:
            error = str(e)
        except Exception as e:
            logger.exception("결합 분석 실패")
            error = f"분석 중 오류가 발생했습니다: {e}"

    result = combo["trend"] if combo else None
    return render_template(
        "combined.html",
        result=result,
        combo=combo,
        result_json=json.dumps(combo, ensure_ascii=False, indent=2, default=str) if combo else "",
        error=error,
        form=form,
        force=force,
        cluster_keys=trend_usp.CLUSTER_KEYS,
        cluster_meta=trend_usp.CLUSTER_META,
        funnel_stages=trend_usp.FUNNEL_STAGES_KO,
        evidence_labels=trend_usp.EVIDENCE_LABELS_KO,
    )


if __name__ == "__main__":
    tavily_env.ensure_required_keys()  # OPENAI_API_KEY, TAVILY_API_KEY
    port = int(os.getenv("TREND_TAVILY_PORT", "5090"))
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=port)

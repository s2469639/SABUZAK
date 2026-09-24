#!/usr/bin/env python3
"""독립 실행형 Flask 웹앱. 제품 스펙 + 대상 국가 → 연관 검색어 4단계 분석, USP 매트릭스, 부스 컨셉.

실행:
    pip install -r requirements.txt
    python app.py
    -> 브라우저에서 http://127.0.0.1:5080 접속
"""

import json
import logging
import os

from flask import Flask, render_template, request

from env_setup import ensure_required_keys
from trend_usp import (
    CLUSTER_KEYS,
    CLUSTER_META,
    EVIDENCE_LABELS_KO,
    FUNNEL_STAGES_KO,
    PRODUCT_FIELDS,
    PipelineError,
    run_trend_usp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sabuzak.trend_usp.app")

app = Flask(__name__)

FORM_FIELDS = PRODUCT_FIELDS + ["country"]


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    form = {field: "" for field in FORM_FIELDS}
    force = False

    if request.method == "POST":
        form = {field: request.form.get(field, "").strip() for field in FORM_FIELDS}
        force = bool(request.form.get("force"))
        try:
            result = run_trend_usp(form, form["country"], use_cache=not force)
        except PipelineError as e:
            error = str(e)
        except Exception as e:
            logger.exception("트렌드·USP 분석 실패")
            error = f"분석 중 오류가 발생했습니다: {e}"

    return render_template(
        "trend_usp.html",
        result=result,
        result_json=json.dumps(result, ensure_ascii=False, indent=2) if result else "",
        error=error,
        form=form,
        force=force,
        cluster_keys=CLUSTER_KEYS,
        cluster_meta=CLUSTER_META,
        funnel_stages=FUNNEL_STAGES_KO,
        evidence_labels=EVIDENCE_LABELS_KO,
    )


if __name__ == "__main__":
    ensure_required_keys()
    port = int(os.getenv("TREND_USP_PORT", "5080"))
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1", port=port)

#!/usr/bin/env python3
"""박람회 준비 데스크 리서치 웹 화면 (v9.0, Tavily 조사는 보여주기만 + OpenAI 자체 조사 기반 부스 컨셉).

실행: python app.py  ->  http://127.0.0.1:5055
(v5 5051 · v6 5052 · v7 5053 · v8 5054와 동시에 띄워 비교할 수 있도록 5055를 사용)
"""

from flask import Flask, render_template, request
from openai import AuthenticationError

from env_setup import ensure_required_keys
from research import run_research

PORT = 5055

app = Flask(__name__)

FIELDS = ("product_name", "country", "exhibition_name", "exhibition_website",
          "strengths", "ingredients", "certifications", "price_range")


@app.route("/", methods=["GET", "POST"])
def index():
    form = {f: "" for f in FIELDS}
    result, error = None, None
    if request.method == "POST":
        form = {f: request.form.get(f, "").strip() for f in FIELDS}
        try:
            result = run_research(
                form["product_name"], form["country"],
                exhibition_name=form["exhibition_name"],
                exhibition_website=form["exhibition_website"],
                company_profile={k: form[k] for k in ("strengths", "ingredients", "certifications", "price_range")},
                force=request.form.get("force") == "1",
            )
        except ValueError as e:
            error = str(e)
        except AuthenticationError:
            error = "OpenAI API 키가 유효하지 않습니다. .env의 OPENAI_API_KEY를 확인해주세요."
        except Exception:
            error = "조사 중 오류가 발생했습니다. 서버 터미널의 로그를 확인해주세요."
    return render_template("research.html", form=form, result=result, error=error)


if __name__ == "__main__":
    ensure_required_keys()
    app.run(debug=True, port=PORT)

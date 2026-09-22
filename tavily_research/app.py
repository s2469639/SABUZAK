#!/usr/bin/env python3
"""독립 실행형 Flask 웹앱. 제품명+국가 입력 -> HS코드 후보 + 시장 트렌드 조사.

사전 준비:
    pip install -r requirements.txt
    .env 파일에 OPENAI_API_KEY, TAVILY_API_KEY 설정 (없으면 실행 시 물어봄)

실행:
    python app.py
    -> 브라우저에서 http://127.0.0.1:5050 접속
"""

from flask import Flask, render_template, request

from env_setup import ensure_required_keys
from market_research import get_market_research

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    product_name = ""
    country = ""

    if request.method == "POST":
        product_name = request.form.get("product_name", "").strip()
        country = request.form.get("country", "").strip()
        try:
            result = get_market_research(product_name, country)
        except ValueError as e:
            error = str(e)  # 제품명/국가 미입력 등 (사용자 입력 문제)
        except Exception as e:
            error = f"조사 중 오류가 발생했습니다: {e}"  # API 키 누락/네트워크 오류 등

    return render_template(
        "market_research.html",
        result=result,
        error=error,
        product_name=product_name,
        country=country,
    )


if __name__ == "__main__":
    ensure_required_keys()  # 서버 뜨기 전에 키를 확인/입력받음
    app.run(debug=True, port=5050)

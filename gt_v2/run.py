#!/usr/bin/env python3
import json
import logging
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sabusak.server")

from competitors import analyze_market_competitors
from google_trends import analyze_country_and_keywords, fetch_google_trends, generate_trend_insights
from tavily_news import get_tavily_news

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    # 6대 명세 입력 필드 수신
    product_name = (request.form.get("product_name") or request.args.get("product_name") or "약과").strip()
    country = (request.form.get("country") or request.args.get("country") or "벨기에").strip()
    ingredients = (request.form.get("ingredients") or "밀가루, 찹쌀, 꿀, 계피").strip()
    target_price = (request.form.get("target_price") or "4~5 EUR / 200g").strip()
    certifications = (request.form.get("certifications") or "HACCP, 비건").strip()
    strengths = (request.form.get("strengths") or "겉바속쫀 식감, 자연 꿀 코팅 글레이즈").strip()
    exhibition_month = (request.form.get("exhibition_month") or "10월").strip()

    if request.method == "POST" or request.args.get("run") == "true":
        try:
            # 1. 키워드 추출
            geo_code, keywords_list, selection_reason = analyze_country_and_keywords(
                product_name, country, ingredients, target_price, certifications, strengths
            )
            # 2. 구글 트렌드 수집 (독립 및 상대 정규화)
            trend_data = fetch_google_trends(keywords_list, geo_code)
            # 3. B2B 소싱 역산 인사이트 생성
            trend_insights = generate_trend_insights(product_name, country, trend_data, exhibition_month)
            # 4. 경쟁사 & 뉴스 수집
            competitor_analysis = analyze_market_competitors(product_name, country, target_price)
            tavily_data = get_tavily_news(product_name, country)

            chart_labels = trend_data.get("dates", [])
            rel_series = trend_data.get("relative_series", {})
            ind_series = trend_data.get("independent_series", {})

            result = {
                "product_name": product_name,
                "country": country,
                "geo_code": geo_code,
                "keywords": keywords_list,
                "selection_reason": selection_reason,
                "chart_labels_json": json.dumps(chart_labels, ensure_ascii=False),
                "relative_datasets_json": json.dumps(
                    [{"label": kw, "data": vals} for kw, vals in rel_series.items()], ensure_ascii=False
                ),
                "independent_datasets_json": json.dumps(
                    [{"label": kw, "data": vals} for kw, vals in ind_series.items()], ensure_ascii=False
                ),
                "trend_insights": trend_insights,
                "competitor_analysis": competitor_analysis,
                "tavily_data": tavily_data,
                "is_simulated_trends": trend_data.get("is_simulated", False),
            }
        except Exception as e:
            logger.exception("시장 분석 파이프라인 처리 중 오류")
            error = f"분석 중 오류가 발생했습니다: {e}"

    return render_template(
        "google_trends.html",
        result=result,
        error=error,
        product_name=product_name,
        country=country,
        ingredients=ingredients,
        target_price=target_price,
        certifications=certifications,
        strengths=strengths,
        exhibition_month=exhibition_month,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    debug_mode = os.getenv("FLASK_DEBUG", "0") == "1"
    logger.info("🚀 서버 가동: http://127.0.0.1:%d", port)
    app.run(debug=debug_mode, port=port)
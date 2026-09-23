import os
import hashlib
from dotenv import load_dotenv

# 상위 폴더(..)의 .env 로드
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
env_path = os.path.join(parent_dir, '.env')
load_dotenv(dotenv_path=env_path)

from flask import Flask, render_template, request
from core.keyword_extractor import extract_keywords
from core.pytrends_engine import fetch_google_trends, COUNTRY_GEO_MAP
from core.lead_time_calculator import calculate_lead_time
from core.competitor_analyzer import analyze_competitors
from core.tavily_news_crawler import fetch_local_news
from database.cache_manager import get_cache, set_cache

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    if not request.args.get('product_name'):
        return '''
        <!DOCTYPE html>
        <html lang="ko">
        <head>
            <meta charset="UTF-8"><title>박람회 시장 분석 파라미터 입력</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 p-10 font-sans">
            <div class="max-w-xl mx-auto bg-white p-6 rounded-xl border shadow-sm">
                <h2 class="text-xl font-bold mb-4 text-slate-800">시장·트렌드 분석 대상 입력</h2>
                <form method="GET" action="/" class="space-y-3 text-sm">
                    <div><label class="font-medium text-slate-700">출품 제품명</label><input class="w-full border p-2 rounded mt-1" type="text" name="product_name" value="비건 만두" required></div>
                    <div><label class="font-medium text-slate-700">타깃 국가</label><input class="w-full border p-2 rounded mt-1" type="text" name="country" value="영국" required></div>
                    <div><label class="font-medium text-slate-700">핵심 베이스 원재료</label><input class="w-full border p-2 rounded mt-1" type="text" name="ingredients" value="두부, 대두단백, 표고버섯, 채소류" required></div>
                    <div><label class="font-medium text-slate-700">목표 소매 가격대/단위중량</label><input class="w-full border p-2 rounded mt-1" type="text" name="target_price" value="4.99 GBP / 350g" required></div>
                    <div><label class="font-medium text-slate-700">보유 인증</label><input class="w-full border p-2 rounded mt-1" type="text" name="certifications" value="비건, 코셔, HACCP"></div>
                    <div><label class="font-medium text-slate-700">식감/가공 메커니즘</label><input class="w-full border p-2 rounded mt-1" type="text" name="strengths" value="얇고 쫄깃한 만두피, 고기 육즙을 모사한 버섯 채즙"></div>
                    <div><label class="font-medium text-slate-700">박람회 개최 월</label><input class="w-full border p-2 rounded mt-1" type="text" name="exhibition_month" value="10월"></div>
                    <button type="submit" class="w-full bg-blue-600 text-white py-2 rounded font-semibold mt-4 hover:bg-blue-700 transition">분석 시작</button>
                </form>
            </div>
        </body>
        </html>
        '''

    specs = {
        "product_name": request.args.get('product_name'),
        "country": request.args.get('country'),
        "ingredients": request.args.get('ingredients'),
        "target_price": request.args.get('target_price'),
        "certifications": request.args.get('certifications'),
        "strengths": request.args.get('strengths'),
        "exhibition_month": request.args.get('exhibition_month', '10월')
    }

    # 캐시 키 뒤에 _v4를 붙여 이전 버전의 누락 캐시를 완전 격리
    raw_key = f"{specs['product_name']}_{specs['country']}_{specs['exhibition_month']}_v4"
    cache_key = hashlib.md5(raw_key.encode()).hexdigest()

    cached_result = get_cache(cache_key)
    if cached_result:
        return render_template('market_trend.html', **cached_result)

    # 1. 3단 키워드 추출 (OpenAI)
    keywords = extract_keywords(specs)
    kw_list = [keywords["kw1"], keywords["kw2"], keywords["kw3"]]

    # 2. 구글 트렌드 시계열 수집 (12m + 5y 듀얼 수집)
    trend_data = fetch_google_trends(kw_list, specs["country"])
    country_code = COUNTRY_GEO_MAP.get(specs["country"], "GB")
    
    # 3. B2B 납기 사이클 계산 엔진 (주간 단위인 12m 기준 실행)
    lead_time = calculate_lead_time(trend_data["12m"], keywords["kw1"], specs["exhibition_month"], country_code)

    # 4. 현지 매대 실존 경쟁사 분석
    competitors = analyze_competitors(specs, keywords)

    # 5. 현지 식문화 트렌드 뉴스 수집 및 요약
    news = fetch_local_news(specs["country"], keywords["kw3"])

    response_payload = {
        "specs": specs,
        "keywords": keywords,
        "trend_data": trend_data,
        "lead_time": lead_time,
        "competitors": competitors,
        "news": news
    }

    # 오류가 없을 때만 캐시에 안전하게 저장
    if not news.get("is_error"):
        set_cache(cache_key, response_payload)

    return render_template('market_trend.html', **response_payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
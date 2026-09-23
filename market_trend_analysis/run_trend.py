import os
import hashlib
from dotenv import load_dotenv

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
            <meta charset="UTF-8"><title>박람회 시장 분석 대상 입력</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 p-10 font-sans">
            <div class="max-w-xl mx-auto bg-white p-6 rounded-xl border shadow-sm">
                <h2 class="text-xl font-bold mb-4 text-slate-800">시장·트렌드 분석 대상 입력</h2>
                <form method="GET" action="/" class="space-y-3 text-sm">
                    <div><label class="font-medium text-slate-700">출품 제품명</label><input class="w-full border p-2 rounded mt-1" type="text" name="product_name" value="약과" required></div>
                    <div><label class="font-medium text-slate-700">타깃 국가</label><input class="w-full border p-2 rounded mt-1" type="text" name="country" value="영국" required></div>
                    <div><label class="font-medium text-slate-700">핵심 베이스 원재료</label><input class="w-full border p-2 rounded mt-1" type="text" name="ingredients" value="밀가루, 쌀조청, 꿀, 참기름, 생강즙, 계피가루" required></div>
                    <div><label class="font-medium text-slate-700">목표 소매 가격대/단위중량</label><input class="w-full border p-2 rounded mt-1" type="text" name="target_price" value="3.80 GBP / 200g" required></div>
                    <div><label class="font-medium text-slate-700">보유 인증</label><input class="w-full border p-2 rounded mt-1" type="text" name="certifications" value="HACCP, FSSC22000, 할랄"></div>
                    <div><label class="font-medium text-slate-700">식감/가공 메커니즘</label><input class="w-full border p-2 rounded mt-1" type="text" name="strengths" value="다층 페이스트리 유탕 방식을 통한 겉은 바삭하고 속은 쫀득한 식감, 은은한 생강·계피 풍미"></div>
                    <div><label class="font-medium text-slate-700">박람회 개최 월</label><input class="w-full border p-2 rounded mt-1" type="text" name="exhibition_month" value="10월"></div>
                    <button type="submit" class="w-full bg-blue-600 text-white py-2.5 rounded-lg font-semibold mt-4 hover:bg-blue-700 transition shadow">분석 시작</button>
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

    raw_key = f"{specs['product_name']}_{specs['country']}_{specs['exhibition_month']}_v6"
    cache_key = hashlib.md5(raw_key.encode()).hexdigest()

    cached_result = get_cache(cache_key)
    if cached_result:
        return render_template('market_trend.html', **cached_result)

    keywords = extract_keywords(specs)
    kw_list = [keywords["kw1"], keywords["kw2"], keywords["kw3"]]

    trend_data = fetch_google_trends(kw_list, specs["country"])
    country_code = COUNTRY_GEO_MAP.get(specs["country"], "GB")
    
    lead_time = calculate_lead_time(
        trend_data["12m"], 
        keywords["kw1"], 
        specs["exhibition_month"], 
        country=specs["country"], 
        product_name=specs["product_name"]
    )

    competitors = analyze_competitors(specs, keywords)
    news = fetch_local_news(specs["country"], keywords, specs["product_name"])

    response_payload = {
        "specs": specs,
        "keywords": keywords,
        "trend_data": trend_data,
        "lead_time": lead_time,
        "competitors": competitors,
        "news": news
    }

    if not news.get("is_error"):
        set_cache(cache_key, response_payload)

    return render_template('market_trend.html', **response_payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)

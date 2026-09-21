from flask import Flask, render_template, request
from test_trends import analyze_country_and_keywords, fetch_google_trends
from test_competitors import analyze_market_competitors

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    selected_timeframe = "today 12-m" # 기본값 1년

    if request.method == 'POST':
        product_name = request.form.get('product_name', '').strip()
        country = request.form.get('country', '').strip()
        selected_timeframe = request.form.get('timeframe', 'today 12-m')

        if product_name and country:
            # 1. 키워드 분석
            geo_code, keywords_list, selection_reason = analyze_country_and_keywords(product_name, country)

            # 2. 선택된 기간으로 트렌드 데이터 수집
            trend_data = fetch_google_trends(keywords_list, geo_code, selected_timeframe)

            # 3. 경쟁사 분석
            market_analysis = analyze_market_competitors(product_name, country)

            result = {
                "product_name": product_name,
                "country": country,
                "timeframe": selected_timeframe,
                "keywords": keywords_list,
                "selection_reason": selection_reason,
                "trend_data": trend_data,
                "analysis": market_analysis
            }

    return render_template('test_chart.html', result=result, timeframe=selected_timeframe)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
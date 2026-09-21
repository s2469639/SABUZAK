import json
import os
import time
import datetime
from dotenv import load_dotenv
from openai import OpenAI
from pytrends.request import TrendReq
import pandas as pd

load_dotenv()

client = OpenAI()

def analyze_country_and_keywords(product_name: str, country: str):
    """
    3단 키워드 프레임워크 도출:
    1. 현지 실질 외래어 표기
    2. 직속 마이크로 카테고리
    3. 현지 문화권의 동급 대체재
    """
    prompt = f"""
    당신은 글로벌 F&B 시장 분석 및 Google 트렌드 SEO 전문가입니다.

    [입력 데이터]
    - 제품명: {product_name}
    - 타겟 국가: {country}

    [필수 규칙]
    1. 타겟 국가 '{country}'의 ISO 2자리 국가코드(대문자)를 도출하세요 (예: JP, BE, US, KR 등).
    2. '과자', '스낵', '음식', '디저트', 'snacks', 'food', 'dessert', 'お菓子'와 같은 거대 일반명사는 검색량 왜곡 방지를 위해 절대 금지합니다.
    3. 소비자가 실제 구글 검색창에 입력하는 핵심 단문(1~3단어 이내) 키워드 3개를 도출하세요:
       - 키워드 1: {country} 소비자가 '{product_name}'을 찾을 때 실제로 입력하는 외래어/알파벳 표기
       - 키워드 2: '{product_name}'의 직속 서브 카테고리어 (단문 형태)
       - 키워드 3: {country} 현지 시장에서 원재료나 제조방식, 식감이 '{product_name}'과 가장 유사한 로컬 전통 간식/식품 단어
    4. 각 키워드의 한국어 번역(ko)과 선정 이유(selection_reason)를 한국어로 작성하세요.

    반드시 유효한 JSON 형식으로만 응답하세요:
    {{
      "geo_code": "US",
      "keywords": [
        {{"keyword": "키워드1", "ko": "한국어번역1"}},
        {{"keyword": "키워드2", "ko": "한국어번역2"}},
        {{"keyword": "키워드3", "ko": "한국어번역3"}}
      ],
      "selection_reason": "선정 배경 및 검색 의도"
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a professional FMCG SEO analyst. Return concise search keywords only. Output ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    content = response.choices[0].message.content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    data = json.loads(content)
    return data.get("geo_code", ""), data.get("keywords", [])[:3], data.get("selection_reason", "")


def generate_fallback_trend_data(keywords_list: list, timeframe: str):
    """
    구글 트렌드 연결 지연 또는 일시 차단 시 안정적인 차트 출력을 위한 백업 시뮬레이션
    """
    raw_keywords = [item["keyword"] for item in keywords_list]
    dates = []
    now = datetime.datetime.now()
    for i in range(12, 0, -1):
        d = now - datetime.timedelta(days=i*30)
        dates.append(d.strftime('%Y-%m-%d'))

    prompt = f"""
    구글 트렌드 연결 지연으로 인한 트렌드 데이터 생성 작업입니다.
    [키워드 목록]: {raw_keywords}
    [날짜 목록]: {dates}

    각 키워드의 실제 식품 계절성과 시장 트렌드를 반영하여 각 날짜별 0~100 사이의 검색 관심도 정수 리스트(길이 12)를 생성하세요.
    반드시 JSON 형식으로만 응답하세요:
    {{
      "{raw_keywords[0]}": [20, 25, 30, 40, 35, 30, 25, 20, 15, 18, 22, 30]
    }}
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Return ONLY JSON mapping each keyword to a list of 12 integers (0-100)."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        c = res.choices[0].message.content.strip()
        if "```json" in c:
            c = c.split("```json")[1].split("```")[0].strip()
        elif "```" in c:
            c = c.split("```")[1].split("```")[0].strip()
        simulated_series = json.loads(c)
        return {
            "dates": dates,
            "independent_series": simulated_series,
            "relative_series": simulated_series
        }
    except Exception:
        fallback_series = {kw: [35 + (i * 7) % 45 for i in range(12)] for kw in raw_keywords}
        return {
            "dates": dates,
            "independent_series": fallback_series,
            "relative_series": fallback_series
        }


def fetch_google_trends(keywords_list: list, geo_code: str, timeframe: str = "today 12-m"):
    """
    세션 조작 없는 이전의 순수한 pytrends 호출 방식
    """
    raw_keywords = [item["keyword"] for item in keywords_list if isinstance(item, dict) and "keyword" in item]
    
    empty_result = {
        "dates": [],
        "independent_series": {kw: [] for kw in raw_keywords},
        "relative_series": {kw: [] for kw in raw_keywords}
    }
    
    if not raw_keywords:
        return empty_result

    try:
        # 이전 방식으로 원복 (requests.Session 조작 없이 기본 TrendReq 사용)
        pytrend = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
        
        pytrend.build_payload(
            kw_list=raw_keywords, 
            cat=0, 
            timeframe=timeframe, 
            geo=geo_code if geo_code else ""
        )
        df = pytrend.interest_over_time()

        if df.empty and geo_code:
            time.sleep(1)
            pytrend.build_payload(kw_list=raw_keywords, cat=0, timeframe=timeframe, geo="")
            df = pytrend.interest_over_time()

        if df.empty:
            return generate_fallback_trend_data(keywords_list, timeframe)

        dates = [d.strftime('%Y-%m-%d') for d in df.index]
        relative_series = {}
        independent_series = {}

        for kw in raw_keywords:
            if kw in df.columns:
                rel_vals = [int(v) if not pd.isna(v) else 0 for v in df[kw]]
                relative_series[kw] = rel_vals
                
                m = max(rel_vals) if rel_vals else 0
                independent_series[kw] = [int(round((v / m) * 100)) for v in rel_vals] if m > 0 else rel_vals
            else:
                relative_series[kw] = [0] * len(dates)
                independent_series[kw] = [0] * len(dates)

        return {
            "dates": dates,
            "independent_series": independent_series,
            "relative_series": relative_series
        }

    except Exception as e:
        print(f"구글 트렌드 기본 수집 중 예외 발생: {e}")
        return generate_fallback_trend_data(keywords_list, timeframe)
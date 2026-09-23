import datetime
import json
import logging
import os
import time

from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd
from pytrends.request import TrendReq

load_dotenv()
client = OpenAI()
logger = logging.getLogger("sabusak.trends")

KEYWORD_MODEL = os.getenv("TRENDS_KEYWORD_MODEL", "gpt-4o-mini")
INSIGHT_MODEL = os.getenv("TRENDS_INSIGHT_MODEL", "gpt-4o-mini")


# ---------------------------------------------------------------------------
# 1. 6대 명세 기반 3단 키워드 추출
# ---------------------------------------------------------------------------

def analyze_country_and_keywords(
    product_name: str,
    country: str,
    ingredients: str = "",
    target_price: str = "",
    certifications: str = "",
    strengths: str = "",
) -> tuple:
    """
    사용자가 입력한 6대 명세를 바탕으로 타깃 국가의 ISO 코드와
    왜곡 없는 3단 키워드(현지 실질 표기, 마이크로 카테고리, 동등 체급 로컬 대체재)를 도출합니다.
    """
    prompt = f"""
    당신은 글로벌 F&B 무역 및 Google 트렌드 SEO 분석 전문가입니다.

    [출품 제품 6대 명세]
    - 제품명: {product_name}
    - 진출 국가: {country}
    - 주요 원재료: {ingredients or '명시되지 않음'}
    - 목표 소매 가격대(단위당): {target_price or '일반 식품 평균가'}
    - 보유 인증: {certifications or '없음'}
    - 제품 핵심 강점(식감/물성/맛/용도): {strengths or '일반적인 해당 식품 특성'}

    [필수 규칙]
    1. 타겟 국가 '{country}'의 ISO 2자리 국가코드(대문자)를 도출하세요 (예: US, BE, DE, JP, MY 등).
    2. '과자', '음식', '디저트', 'food', 'snack' 등 거대 일반명사는 검색량 왜곡 방지를 위해 절대 금지합니다.
    3. 소비자가 실제 구글 검색창에 입력하는 단문(1~3단어 이내) 키워드 3개를 도출하세요:
       - 키워드 1: {country} 소비자가 '{product_name}'을 찾을 때 실제로 입력하는 로컬 외래어/알파벳 표기
       - 키워드 2: [출신국/문화권] + [직속 서브 카테고리/제형] (예: Korean glazed pastry, Korean chili paste)
       - 키워드 3: {country} 현지 시장에서 [주요 원재료 + 제품 강점의 식감/물성 + 가격대 체급]이 가장 일치하는 **현지 고유의 대등 대체재/라이벌 제품 단어**

    [키워드 3 선정 금지 규칙]
    - 원재료 명칭만 같고 물리적 식감/물성이 전혀 다른 제품은 매핑하지 마세요 (예: 유과의 대체재로 쫄깃한 떡 '모찌' 매핑 금지 -> 바삭한 튀김 쌀과자류 매핑).
    - 가격대({target_price})와 제품 강점({strengths})에 부합하는 현지 로컬 제품을 지정하세요.

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
    try:
        response = client.chat.completions.create(
            model=KEYWORD_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("geo_code", ""), data.get("keywords", [])[:3], data.get("selection_reason", "")
    except Exception as e:
        logger.error("키워드 추출 실패: %s", e)
        return "", [], "키워드 추출 중 오류가 발생했습니다."


# ---------------------------------------------------------------------------
# 2. Google Trends 시계열 데이터 수집 및 이중 정규화
# ---------------------------------------------------------------------------

def generate_fallback_trend_data(keywords_list: list) -> dict:
    raw_keywords = [item["keyword"] for item in keywords_list]
    dates = []
    now = datetime.datetime.now()
    for i in range(12, 0, -1):
        d = now - datetime.timedelta(days=i * 30)
        dates.append(d.strftime('%Y-%m-%d'))

    fallback_series = {kw: [20 + (i * 7) % 40 for i in range(12)] for kw in raw_keywords}
    return {
        "dates": dates,
        "independent_series": fallback_series,
        "relative_series": fallback_series,
        "is_simulated": True,
    }


def fetch_google_trends(keywords_list: list, geo_code: str, timeframe: str = "today 12-m") -> dict:
    raw_keywords = [item["keyword"] for item in keywords_list if isinstance(item, dict) and "keyword" in item]
    if not raw_keywords:
        return {"dates": [], "independent_series": {}, "relative_series": {}, "is_simulated": False}

    try:
        pytrend = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
        pytrend.build_payload(kw_list=raw_keywords, cat=0, timeframe=timeframe, geo=geo_code or "")
        df = pytrend.interest_over_time()

        if df.empty and geo_code:
            time.sleep(1)
            pytrend.build_payload(kw_list=raw_keywords, cat=0, timeframe=timeframe, geo="")
            df = pytrend.interest_over_time()

        if df.empty:
            return generate_fallback_trend_data(keywords_list)

        dates = [d.strftime('%Y-%m-%d') for d in df.index]
        relative_series, independent_series = {}, {}

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
            "relative_series": relative_series,
            "is_simulated": False,
        }
    except Exception as e:
        logger.exception("구글 트렌드 수집 실패 (Fallback 전환): %s", e)
        return generate_fallback_trend_data(keywords_list)


# ---------------------------------------------------------------------------
# 3. 계절성 판별, 과거 시점 왜곡 보정, 차기 시즌 B2B 인사이트 도출
# ---------------------------------------------------------------------------

def generate_trend_insights(
    product_name: str,
    country: str,
    trend_data: dict,
    exhibition_month: str = "10월",
) -> list:
    dates = trend_data.get("dates", [])
    series = trend_data.get("relative_series", {})
    is_simulated = trend_data.get("is_simulated", False)

    if not dates or not series:
        return [
            "데이터 표본이 부족하여 시즌성을 판별할 수 없습니다.",
            "키워드 간 검색량 상관관계를 도출할 수 없습니다.",
            "현지 대중 인지도 확보를 위한 마케팅 전략이 필요합니다.",
        ]

    if is_simulated:
        return [
            "⚠️ 구글 트렌드 API 연결 지연으로 예시 데이터가 표시 중입니다.",
            "실제 데이터 기반 B2B 소싱 분석을 보류합니다.",
            "API 재연결 후 다시 조회해 주세요.",
        ]

    # --- 1. 오늘 기준 현재 시점 계산 (과거 왜곡 방지용) ---
    now = datetime.datetime.now()
    current_year = now.year
    current_month = now.month
    today_str = f"{current_year}년 {current_month}월"

    # --- 2. 통계 기반 계절성(Seasonal vs Year-round Stable) 판별 ---
    main_kw = list(series.keys())[0] if series else ""
    vals = series.get(main_kw, [])

    is_seasonal = False
    peak_month = 0
    upcoming_target_season = "연중 상시"
    max_v = max(vals) if vals else 0
    avg_v = sum(vals) / len(vals) if vals else 0

    if vals and max_v > 0:
        ratio = max_v / (avg_v + 1e-5)
        zero_ratio = vals.count(0) / len(vals)

        # 피크가 평균의 2.8배 이상이면서 0점 구간이 유의미하게 많을 때만 '시즌성 품목'으로 판정
        if ratio >= 2.8 and zero_ratio > 0.35:
            is_seasonal = True
            raw_peak_date = dates[vals.index(max_v)]  # 예: "2026-02-15"
            peak_dt = datetime.datetime.strptime(raw_peak_date, "%Y-%m-%d")
            peak_month = peak_dt.month  # 피크가 발생했던 '월(Month)'

            # [차기 시즌 연도 동적 연산]
            # 이미 올해 해당 월이 지났으면 다음 해(next year) 피크를 타깃으로 설정
            if peak_month <= current_month:
                target_year = current_year + 1
            else:
                target_year = current_year
            upcoming_target_season = f"{target_year}년 {peak_month}월경"
        else:
            is_seasonal = False

    pattern_desc = "시즌성 급등 품목" if is_seasonal else "연중 상시 소비재(계절성 미미/완만)"

    # --- 3. 팩트 기반 프롬프트 생성 (과거 시점 및 클리셰 템플릿 차단) ---
    prompt = f"""
    당신은 글로벌 B2B 식품 무역 컨설턴트입니다.
    '건강에 대한 관심 증가', 'K-컬처/SNS 바이럴', '글루텐프리'와 같은 일반적이고 뻔한 클리셰 표현을 일절 금지합니다.

    [중요: 시점 기준 원칙 - 과거 날짜를 미래로 오인하지 말 것]
    1. 오늘 시점은 **{today_str}**입니다.
    2. 제공된 구글 트렌드 데이터는 지난 1년간 수집된 '과거 통계 실적'입니다. 
       과거 날짜를 두고 "앞으로 ~에 검색이 집중될 것으로 예상된다"고 작성하면 치명적인 오답입니다.
    3. B2B 발주 및 부스 제언 시에는 반드시 **다가오는 차기 시즌({upcoming_target_season})**을 준비하는 관점으로 미래 시점을 설정하세요.

    [분석 데이터]
    - 제품명: {product_name}
    - 진출 국가: {country}
    - 참가(예정) 박람회 개최 월: {exhibition_month}
    - 데이터 패턴 판별: {pattern_desc}
    - 과거 최고 관심도: {max_v}점 (과거 피크 발생 월: {peak_month if is_seasonal else '연중 고름'}월) / 과거 연평균: {round(avg_v, 1)}점
    - 타깃으로 삼아야 할 다음 피크 시즌: {upcoming_target_season}

    [작성 요구사항 - 3개 항목, 한국어, 각 2문장 내외]
    1. [소비자 패턴 및 시즌성 진단]:
       - '{pattern_desc}'가 '연중 상시 소비재'인 경우: 억지로 특정 날짜의 피크 원인을 지어내지 말고, "이 제품은 특정 시즌을 타지 않는 일상 식사/간식 품목으로, 연중 고른 수요를 형성합니다."라는 취지로 명확히 서술할 것.
       - '시즌성 급등 품목'인 경우: 과거 통계를 근거로 **"매년 {peak_month}월경(현지 명절 또는 특정 시즌)"**에 검색 수요가 반복 집중되는 주기성을 가진다고 과거형/주기성으로 서술할 것.

    2. [카테고리 경쟁 및 시장 인지도]:
       - 타깃 제품({product_name})의 현지 검색 볼륨을 로컬 대체재와 비교하여, 현재 현지 메인스트림 대비 틈새(Niche) 시장인지 진입 초기인지를 냉정하게 진단할 것.

    3. [B2B 박람회 부스 슬로건 & 사전 발주 역산]:
       - '연중 상시 소비재'인 경우: '피크 역산'을 쓰지 말고, 바이어에게 "시즌 리스크 없는 연중 안정적 회전율(Year-round High Turnover)"을 어필하는 B2B 헤드라인 카피 1개를 따옴표로 포함할 것.
       - '시즌성 급등 품목'인 경우: **다가오는 차기 시즌({upcoming_target_season})**을 선점하기 위해, 이번 박람회({exhibition_month})에서 바이어가 3~6개월 전 사전 발주(Shelf-Ready)해야 하는 B2B 슬로건 1개를 따옴표로 포함할 것.

    반드시 아래 JSON 포맷으로만 응답하세요:
    {{
      "insights": [
        "1번 소비자 패턴 내용...",
        "2번 시장 인지도 진단 내용...",
        "3번 B2B 슬로건 내용..."
      ]
    }}
    """
    try:
        response = client.chat.completions.create(
            model=INSIGHT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        insights = data.get("insights", []) if isinstance(data, dict) else []
        while len(insights) < 3:
            insights.append("추가 시장 분석 전략을 도출 중입니다.")
        return insights[:3]
    except Exception as e:
        logger.error("인사이트 도출 실패: %s", e)
        return [
            f"{product_name}은 연중 고른 수요를 형성하는 품목입니다.",
            f"로컬 대체재 대비 현지 인지도는 초기 단계로 틈새 시장 공략이 필요합니다.",
            "차기 시즌에 대비하여 바이어에게 사전 납품 및 안정적 마진을 제안하세요.",
        ]
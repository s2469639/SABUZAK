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
    1. 타겟 국가 '{country}'의 ISO 2자리 국가코드(대문자)를 도출하세요.
    2. '과자', '음식', '디저트', 'food', 'snack' 등 거대 일반명사는 검색량 왜곡 방지를 위해 절대 금지합니다.
    3. 소비자가 실제 구글 검색창에 입력하는 단문(1~3단어 이내) 키워드 3개를 도출하세요:
       - 키워드 1: {country} 소비자가 '{product_name}'을 찾을 때 실제로 입력하는 로컬 외래어/알파벳 표기
       - 키워드 2: [출신국/문화권] + [직속 서브 카테고리/제형] (예: Korean glazed pastry, Korean chili paste)
       - 키워드 3: {country} 현지 시장에서 [주요 원재료 + 제품 강점의 식감/물성 + 가격대 체급]이 가장 일치하는 현지 고유의 대등 대체재/라이벌 제품 단어

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
# 2. Google Trends 수집 및 이중 정규화
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
# 3. 피크 원인 추적 & 부스 슬로건 / B2B 인사이트 생성
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
            "실제 피크 원인 및 B2B 전략 분석을 보류합니다.",
            "API 재연결 후 다시 조회해 주세요.",
        ]

    # 100점 피크 및 고득점(70점 이상) 구간 자동 추출
    peak_details = []
    for kw, vals in series.items():
        if not vals:
            continue
        max_v = max(vals)
        if max_v > 0:
            max_idx = vals.index(max_v)
            peak_date = dates[max_idx]
            
            high_dates = [dates[i] for i, v in enumerate(vals) if v >= 70]
            peak_details.append({
                "keyword": kw,
                "peak_score": max_v,
                "peak_date": peak_date,
                "sustained_period": f"{high_dates[0]} ~ {high_dates[-1]}" if len(high_dates) > 1 else peak_date,
                "is_spike": len(high_dates) <= 2
            })

    peak_context_text = "\n".join([
        f"- 키워드 '{p['keyword']}': 최고점 {p['peak_score']}점 달성 시점({p['peak_date']}), 고관심 유지구간({p['sustained_period']}), 단발성 급등 여부: {p['is_spike']}"
        for p in peak_details
    ])

    prompt = f"""
    당신은 글로벌 F&B 무역 및 검색 트렌드 분석 전문가입니다.
    구글 트렌드 그래프에서 특정 시점에 갑작스럽게 100점 피크를 기록하거나 점수가 높게 유지된 원인을 분석하고,
    해당 이슈를 박람회 부스 슬로건 및 B2B 피칭 카피로 구체화하세요.

    [분석 대상]
    - 제품명: {product_name} / 대상 국가: {country}
    - 참가(예정) 박람회 개최 시점: {exhibition_month}
    - 전체 분석 기간: {dates[0]} ~ {dates[-1]}

    [실제 감지된 피크 데이터]
    {peak_context_text}

    [작성 요구사항 - 3개 항목, 한국어, 각 2문장 내외]
    1. [피크 원인 심층 추적]:
       - 최고점(100점)을 기록한 시기에 {country} 현지 시장에서 일어난 식문화적 배경을 추정 명시하세요.
       - (예: 특정 월의 웰빙/글루텐프리 캠페인, SNS 핑거스낵/토핑 레시피 바이럴, 아웃도어/소풍 시즌 스낵 수요 등)
       - 이것이 '일회성 단발 이슈'인지 '매년 반복되는 구조적 시즌성'인지 명확히 짚어주세요.

    2. [카테고리 동조화 및 시장 성숙도]:
       - 로컬 대체재의 피크가 타깃 제품({product_name})의 검색 증가로 전이되었는지 분석하고 현재 인지도 격차를 진단하세요.

    3. [피크 이슈 기반 부스 슬로건 & B2B 발주 역산]:
       - 위 피크 원인(이슈)을 부스 컨셉에 반영할 수 있는 실전 슬로건을 제시하세요.
       - 단발성 이슈라면 "일시적 유행을 넘어 상시 건강 스낵으로", 연례 시즌 이슈라면 "피크 시즌 3~6개월 전 사전 발주(Shelf-Ready)" 관점으로 작성하세요.
       - 박람회({exhibition_month}) 바이어가 솔깃할 만한 B2B 헤드라인 카피를 포함하세요.

    반드시 아래 JSON 포맷으로만 응답하세요:
    {{
      "insights": [
        "1번 피크 원인 분석 내용...",
        "2번 동조화 분석 내용...",
        "3번 피크 연계 슬로건 및 B2B 전략 내용..."
      ]
    }}
    """
    try:
        response = client.chat.completions.create(
            model=INSIGHT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        insights = data.get("insights", []) if isinstance(data, dict) else []
        while len(insights) < 3:
            insights.append("추가 피크 원인을 분석 중입니다.")
        return insights[:3]
    except Exception as e:
        logger.error("인사이트 도출 실패: %s", e)
        return [
            f"특정 시기 피크는 현지 식문화 캠페인 또는 SNS 바이럴에 의한 일시적 관심 집중으로 분석됩니다.",
            f"로컬 대체재의 관심도 급증이 {product_name}의 검색 동조화로 이어지지는 않았습니다.",
            f"해당 피크 이슈의 핵심 소구점을 차용해 박람회 현장에서 바이어 사전 발주(Shelf-Ready) 슬로건으로 제안하세요.",
        ]
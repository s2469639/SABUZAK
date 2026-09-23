import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()
logger = logging.getLogger("sabusak.competitors")
MODEL = os.getenv("COMPETITORS_MODEL", "gpt-4o")


def analyze_market_competitors(product_name: str, country: str, target_price: str = "") -> dict:
    prompt = f"""
    당신은 글로벌 F&B 리테일 시장 분석가입니다.

    [분석 대상]
    - 제품명: {product_name}
    - 대상 국가: {country}
    - 목표 소매가: {target_price or '일반 소비자가 기준'}

    아래 항목을 포함하여 JSON 형식으로 작성하세요 (모든 설명은 한국어 작성):
    1. competitors: {country} 현지 시장 내 주요 경쟁 브랜드/제조사 (3개 이상)
    2. competitor_products: 현지 유통 매대에 실존하는 대표 경쟁 제품 (제품명, 제조사, 한국어 특징)
    3. similar_products: {product_name}과 식감/카테고리가 유사한 현지 대체 제품 (제품명, 한국어 설명)
    4. average_snack_price: {country} 현지 해당 식품/스낵류의 일반적인 평균 가격대 (현지 통화 및 원화 환산 병기)
    5. market_summary: 현지 시장 진입 시 핵심 고려사항 및 소비자 선호도 분석 요약 (3~4문장)

    JSON 포맷:
    {{
      "competitors": ["브랜드1", "브랜드2", "브랜드3"],
      "competitor_products": [{{"name": "제품명", "maker": "제조사", "desc": "특징"}}],
      "similar_products": [{{"name": "대체재명", "desc": "설명"}}],
      "average_snack_price": "예: 3 ~ 5 EUR (약 4,400원 ~ 7,300원)",
      "market_summary": "현지 시장 요약..."
    }}
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.error("경쟁사 분석 실패: %s", e)
        return {
            "competitors": [],
            "competitor_products": [],
            "similar_products": [],
            "average_snack_price": "정보 없음",
            "market_summary": "경쟁사 데이터를 불러오지 못했습니다.",
        }
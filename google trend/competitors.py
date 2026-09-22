import json
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

def analyze_market_competitors(product_name: str, country: str) -> dict:
    """
    타겟 국가 시장 내 경쟁사, 대표 제품, 대체 제품, 평균 가격을 한국어로 분석
    """
    prompt = f"""
    당신은 글로벌 F&B/스낵 시장 분석가입니다.

    [분석 대상]
    - 제품명: {product_name}
    - 대상 국가: {country}

    [필수 작성 규칙]
    - **모든 설명, 요약, 제품 특징은 반드시 한국어로 작성하세요.** (외국 브랜드/제품 고유명사는 영문 또는 현지어 병기 가능)
    
    아래 항목을 포함하여 JSON 형식으로 분석 결과를 작성하세요:
    1. competitors: {country} 현지 시장 내 주요 경쟁 브랜드/제조사 (3개 이상)
    2. competitor_products: 현지에서 자리 잡은 대표 경쟁 제품 (제품명, 제조사, 한국어로 된 특징 설명)
    3. similar_products: {product_name}과 식감/카테고리가 유사한 현지 대체 제품 (제품명 및 한국어로 된 설명)
    4. average_snack_price: {country} 현지 과자/스낵류의 일반적인 평균 가격대 (현지 통화 및 원화 환산 병기)
    5. market_summary: 현지 시장 진입 시 핵심 고려사항 및 소비자 선호도에 대한 한국어 분석 요약 (3~4문장)

    반드시 아래 JSON 포맷으로만 응답하세요:
    {{
      "competitors": ["브랜드1", "브랜드2", "브랜드3"],
      "competitor_products": [
        {{"name": "제품명", "maker": "제조사", "desc": "한국어로 된 제품 특징 설명"}}
      ],
      "similar_products": [
        {{"name": "유사 제품명", "desc": "한국어로 된 제품 설명"}}
      ],
      "average_snack_price": "예: 2 ~ 5 USD (약 2,700원 ~ 6,700원)",
      "market_summary": "현지 시장 특성 및 소비자 반응에 대한 한국어 요약"
    }}
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a senior global FMCG & snack market analyst. All explanations, summaries, and descriptions MUST be in Korean. Return ONLY JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    content = response.choices[0].message.content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    return json.loads(content)
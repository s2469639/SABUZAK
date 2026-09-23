import os
import json
from openai import OpenAI

def analyze_competitors(specs: dict, keywords: dict) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = f"""
당신은 해외 식품 유통 전문 바이어입니다.
아래 제품의 타깃 국가 유통 매대에 실제 입점된 2대 실존 경쟁 브랜드와 동등 식감 로컬 대체재를 분석하세요.

- 출품 제품: {specs['product_name']} ({keywords['kw1']})
- 타깃 국가: {specs['country']}
- 원재료 및 식감: {specs['ingredients']} / {specs['strengths']}
- 로컬 대체재: {keywords['kw3']}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
    "competitors": [
        {{
            "brand": "실존 브랜드명 (한국어 발음 병기)",
            "product": "대표 상품명 (한국어 번역 병기)",
            "price": "현지 소비자가 (예: £3.50 / 약 6,100원)",
            "feature": "핵심 셀링 포인트 및 바이어 관점의 특징"
        }},
        {{
            "brand": "실존 브랜드명 2 (한국어 발음 병기)",
            "product": "대표 상품명 2 (한국어 번역 병기)",
            "price": "현지 소비자가 (예: £4.20 / 약 7,300원)",
            "feature": "핵심 셀링 포인트 및 특징"
        }}
    ],
    "substitute": {{
        "name": "{keywords['kw3']} (동등 식감 로컬 대체재)",
        "price": "현지 매대 평균 가격",
        "texture_match": "물리적 식감 및 취식 상황 일치 이유"
    }},
    "benchmarks": [
        "바이어 매대 진입을 위해 반드시 충족해야 할 가격/패키징 벤치마크 1",
        "로컬 경쟁사 대비 우리 제품의 차별화 포인트 2",
        "현지 유통 인증 및 매대 진열(Shelf-Ready) 전략 3"
    ]
}}
"""
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        return json.loads(res.choices[0].message.content)
    except Exception:
        return {
            "competitors": [
                {"brand": "현지 대형마트 PB", "product": "로컬 프리미엄 디저트", "price": "£3.20", "feature": "안정적인 전국 유통망"}
            ],
            "substitute": {"name": keywords.get("kw3", "대체재"), "price": "£3.50", "texture_match": "유사한 단맛 및 쫀득한 물성"},
            "benchmarks": ["현지 친환경 포장 기준 준수", "클린라벨 인증 확보", "소포장 구성"]
        }


import os
import json
from openai import OpenAI

def analyze_competitors(specs: dict, keywords: dict) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    prompt = f"""
타깃 국가({specs.get('country')}) 오프라인/온라인 유통 매대에 실제 입점되어 있는 경쟁 제품 및 동등 식감 대체재를 분석하세요.

[제품 명세]
- 제품명: {specs.get('product_name')}
- 핵심 원재료: {specs.get('ingredients')}
- 목표 가격대: {specs.get('target_price')}
- 식감/물성: {specs.get('strengths')}
- 현지 로컬 대체재 키워드: {keywords.get('kw3')}

[필수 번역 및 표기 규칙]
1. 브랜드명, 제품명, 대체재명이 영문/외국어인 경우 반드시 옆에 괄호로 한국어 번역/발음을 병기하세요.
   예: Itsu Vegetable Fusion Gyoza (잇츠 베지터블 퓨전 교자)
2. 가격은 현지 통화와 원화 환산 가격을 반드시 함께 적으세요.
3. 매대 진입 벤치마크 포인트는 완결된 한국어 문장으로 작성하세요.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
    "competitors": [
        {{
            "brand": "영문 브랜드명 (한국어 발음)",
            "product": "영문 제품명 (한국어 번역/발음)",
            "price": "현지통화 소매가 (원화 환산 병기)",
            "feature": "한국어 특징 요약"
        }}
    ],
    "substitute": {{
        "name": "영문 대체재명 (한국어 번역)",
        "price": "소매가",
        "texture_match": "식감 및 매대 경쟁 요인 설명"
    }},
    "benchmarks": [
        "벤치마크 포인트 1",
        "벤치마크 포인트 2"
    ]
}}
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an international FMCG retail analyst. Output strictly JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )
    return json.loads(response.choices[0].message.content)
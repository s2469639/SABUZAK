import os
import json
from openai import OpenAI

def extract_keywords(specs: dict) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = f"""
당신은 글로벌 소비재 무역 전문 컨설턴트입니다.
아래 한국 식품의 6대 명세를 분석하여 구글 트렌드 및 시장 조사를 위한 '3단 키워드'를 도출하세요.

[제품 명세]
- 제품명: {specs['product_name']}
- 타깃 국가: {specs['country']}
- 원재료: {specs['ingredients']}
- 목표 가격/중량: {specs['target_price']}
- 보유 인증: {specs['certifications']}
- 식감/가공 메커니즘: {specs['strengths']}

[3단 키워드 엄격 규칙]
1. kw1 (현지 실질 검색어): 타깃 국가 소비자가 구글 검색창에 실제로 입력하는 영문/현지어 검색어 (예: yakgwa, vegan dumplings).
2. kw2 (직속 마이크로 카테고리): 너무 거대한 일반명사(예: Snack, Food)를 절대 배제하고, [출신국/문화권 + 직속 제형] 형태를 취할 것 (예: Korean pastry, Korean dessert).
3. kw3 (동등 체급 로컬 대체재): 현지 시장에서 원재료나 물리적 식감, 취식 형태가 일치하는 라이벌 로컬 제품명 (예: baklava, shortbread).
   * 네거티브 룰: 원재료 명칭만 같고 식감이 판이한 품목 매핑 금지 (예: 유과에 떡 Mochi 매핑 금지).

반드시 아래 JSON 포맷으로만 응답하세요:
{{
    "kw1": "현지 실질 검색어",
    "kw2": "직속 마이크로 카테고리",
    "kw3": "동등 체급 로컬 대체재"
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
            "kw1": specs.get("product_name", "korean food"),
            "kw2": "Korean specialty food",
            "kw3": "local snack alternative"
        }


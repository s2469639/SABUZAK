import os
import json
from openai import OpenAI

def extract_keywords(specs: dict) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    prompt = f"""
출품 제품의 6대 명세를 분석하여 구글 트렌드 및 시장 조사용 정밀 키워드 3개를 도출하세요.

[제품 6대 명세]
- 제품명: {specs.get('product_name')}
- 타깃 국가: {specs.get('country')}
- 핵심 베이스 원재료: {specs.get('ingredients')}
- 목표 가격대/단위중량: {specs.get('target_price')}
- 보유 인증: {specs.get('certifications')}
- 식감/가공 메커니즘: {specs.get('strengths')}

[키워드 도출 규칙]
1. kw1 (현지 실질 표기명): 타깃 국가 소비자가 구글에 실제로 검색하는 알파벳/외래어 표기
2. kw2 (직속 마이크로 카테고리): '스낵', '음식' 같은 거대 일반명사 금지. [출신국/문화권] + [직속 카테고리/제형]
3. kw3 (동등 체급 로컬 대체재): 원재료, 물리적 식감/물성, 취식 상황 체급이 가장 유사한 현지 대등 라이벌 제품 단어
* 네거티브 룰: 원재료 명칭만 같고 물리적 식감 형태가 전혀 다른 제품 매핑 절대 금지 (예: 유과에 떡 'Mochi' 매핑 금지 -> 바삭한 쌀스낵 매핑)
* 상투적 템플릿(건강 관심, K-컬처 바이럴 등) 배제.

반드시 아래 JSON 포맷으로만 응답하세요:
{{
    "kw1": "...",
    "kw2": "...",
    "kw3": "..."
}}
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise B2B food trade research assistant. Output strictly JSON."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.2
    )
    return json.loads(response.choices[0].message.content)
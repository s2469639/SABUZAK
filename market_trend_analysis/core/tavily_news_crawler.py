import os
import json
from tavily import TavilyClient
from openai import OpenAI

def fetch_local_news(country: str, kw: str) -> dict:
    tavily_key = os.getenv("TAVILY_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not tavily_key or not openai_key:
        return {
            "articles": [],
            "summary": "API 키(TAVILY_API_KEY 또는 OPENAI_API_KEY)가 설정되지 않았습니다.",
            "is_error": True
        }
        
    tavily = TavilyClient(api_key=tavily_key)
    query = f"{country} food retail market trend {kw} consumer"
    
    try:
        search_res = tavily.search(query=query, search_depth="advanced", max_results=3)
        results = search_res.get("results", [])
        
        if not results:
            return {
                "articles": [],
                "summary": "관련 기사 검색 결과가 없습니다.",
                "is_error": False
            }

        raw_items = []
        for r in results:
            raw_items.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:250]
            })
            
        client = OpenAI(api_key=openai_key)
        
        prompt = f"""
다음은 {country}의 식품 시장 관련 기사 원문들입니다.
1. 각 기사의 제목이 영어/외국어라면 '원문 제목 (한국어 번역)' 형태로 수정하세요.
2. 기사 본문을 한국어로 자연스럽게 번역 요약하세요.
3. 전체 기사를 종합하여 시장 핵심 요약 2문장을 작성하되, 바이어가 주목할 만한 핵심 키워드(예: <b>비건 수요</b>, <b>간편 조리</b> 등)를 반드시 <b> 태그로 감싸서 강조하세요.

[기사 데이터]
{raw_items}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
    "articles": [
        {{
            "title": "원문제목 (한국어 번역)",
            "url": "원문url",
            "content": "한국어 번역 요약"
        }}
    ],
    "summary": "핵심 키워드는 <b>태그로 강조된</b> 종합 2줄 요약문"
}}
"""
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        data = json.loads(res.choices[0].message.content)
        data["is_error"] = False
        return data

    except Exception as e:
        return {
            "articles": [],
            "summary": f"기사 수집 중 오류 발생: {str(e)}",
            "is_error": True
        }
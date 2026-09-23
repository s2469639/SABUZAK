import json
import logging
import os

from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

load_dotenv()
logger = logging.getLogger("sabusak.tavily")


def get_tavily_news(product_name: str, country: str) -> dict:
    tavily_key = os.getenv("TAVILY_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not tavily_key or not openai_key:
        return {"overall_summary_ko": "API 키가 설정되지 않았습니다.", "insights": []}

    try:
        t_client = TavilyClient(api_key=tavily_key)
        o_client = OpenAI(api_key=openai_key)

        query = f"{product_name} {country} food market trends news"
        results = t_client.search(query=query, search_depth="advanced", max_results=3).get("results", [])

        insights = []
        for r in results:
            content = r.get("content", "")
            insights.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "summary": content[:200] + ("..." if len(content) > 200 else ""),
            })

        summary_prompt = f"""
        당신은 F&B 시장조사원입니다. 아래 {country}의 {product_name} 관련 뉴스 검색결과를 종합하여
        한국어 2문장으로 전체 트렌드를 요약하세요:
        {json.dumps(insights, ensure_ascii=False)}
        """
        resp = o_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.2,
        )
        overall_summary = resp.choices[0].message.content.strip()

        return {"overall_summary_ko": overall_summary, "insights": insights}
    except Exception as e:
        logger.error("Tavily 뉴스 수집 오류: %s", e)
        return {"overall_summary_ko": "최신 뉴스를 가져오는 중 오류가 발생했습니다.", "insights": []}
import os
import json
from openai import OpenAI
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY"))
tavily_key = os.getenv("TAVILY_API_KEY")
tavily_client = TavilyClient(api_key=tavily_key) if tavily_key else None

def search_tavily_news(country_name: str, product_name: str) -> tuple[list, list]:
    """
    Tavily를 활용해 개최국 시장의 최근 식품/스낵 트렌드 뉴스 수집
    """
    if not tavily_client:
        return ["TAVILY_API_KEY 미설정"], []

    # 1. 현지 시장 조사를 위한 영문 검색 키워드 3개 생성
    prompt = f"""
    국가: {country_name}
    제품: {product_name}

    위 국가의 최신 제과/스낵 시장 동향, 수입 식품 트렌드, 소비자 반응을 조사하기 위한 영문 검색 쿼리 3개를 JSON으로 작성하세요.
    반드시 아래 포맷으로 응답하세요:
    {{"queries": ["query 1", "query 2", "query 3"]}}
    """
    try:
        res = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        queries = json.loads(res.choices[0].message.content).get("queries", [])
    except Exception:
        queries = [f"{product_name} market trends {country_name}", f"snack industry in {country_name}"]

    # 2. Tavily 뉴스 검색 실행
    articles = []
    seen_urls = set()
    for q in queries[:2]:  # API 쿼터 절약을 위해 상위 2개 쿼리 실행
        try:
            response = tavily_client.search(
                query=q,
                search_depth="advanced",
                topic="news",
                days=180,
                max_results=2
            )
            for r in response.get("results", []):
                url = r.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                articles.append({
                    "query": q,
                    "title": r.get("title"),
                    "url": url,
                    "summary": r.get("content", "")[:200] + "...",
                    "published_date": r.get("published_date")
                })
        except Exception as e:
            print(f"Tavily 검색 에러 ({q}): {e}")

    return queries, articles
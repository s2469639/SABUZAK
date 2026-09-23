import os
import json
import re
from urllib.parse import urlparse
from tavily import TavilyClient
from openai import OpenAI

REGIONS_MAP = {
    "영국": "유럽", "독일": "유럽", "프랑스": "유럽", "이탈리아": "유럽", "스페인": "유럽",
    "미국": "북미", "캐나다": "북미",
    "일본": "동아시아", "중국": "동아시아",
    "베트남": "동남아시아", "말레이시아": "동남아시아", "태국": "동남아시아"
}

EXCLUDED_DOMAINS = [
    "factmr.com", "wiseguyreports.com", "grandviewresearch.com", 
    "marketresearchfuture.com", "mordorintelligence.com", "alliedmarketresearch.com",
    "marketsandmarkets.com", "researchandmarkets.com", "fortunebusinessinsights.com",
    "facebook.com", "instagram.com", "tiktok.com", "linkedin.com", "twitter.com", "x.com", "youtube.com"
]

def build_search_queries(country: str, kw_obj: dict, product_name: str) -> list:
    main_kw = kw_obj.get("kw1", "")
    sub_kw = kw_obj.get("kw3", "")
    return [
        f"{country} {main_kw} consumer preference trend market",
        f"{country} retail supermarket {sub_kw} shelf brand price",
        f"site:kotra.or.kr OR site:kati.net {country} {product_name} 시장동향"
    ]

def extract_year(url: str, text: str) -> str:
    """URL이나 텍스트에서 연도(2020~2027) 추출, 없으면 연도 미상"""
    matches = re.findall(r'(202[0-7])', url + " " + text[:200])
    return f"{matches[0]}년" if matches else "연도 미상"

def fetch_local_news(country: str, kw_obj: dict, product_name: str) -> dict:
    tavily_key = os.getenv("TAVILY_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    
    if not tavily_key or not openai_key:
        return {"quotes": [], "summary": "API 키가 설정되지 않았습니다.", "is_error": True}
        
    tavily = TavilyClient(api_key=tavily_key)
    queries = build_search_queries(country, kw_obj, product_name)
    
    raw_results = []
    seen_urls = set()
    
    for q in queries:
        try:
            res = tavily.search(query=q, search_depth="advanced", max_results=2, exclude_domains=EXCLUDED_DOMAINS)
            for item in res.get("results", []):
                url = item.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    raw_results.append(item)
        except Exception:
            continue
            
    if not raw_results:
        return {"quotes": [], "summary": "현지 유통 및 식문화 관련 신뢰할 수 있는 기사를 찾지 못했습니다.", "is_error": False}

    # 기사별 원문 문장 수집
    source_corpus = []
    for idx, r in enumerate(raw_results[:4]):
        source_corpus.append({
            "id": f"E{idx + 1}",
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "domain": urlparse(r.get("url", "")).netloc.replace("www.", ""),
            "year": extract_year(r.get("url", ""), r.get("content", "")),
            "content": r.get("content", "")[:400]
        })

    client = OpenAI(api_key=openai_key)
    prompt = f"""
당신은 해외 식품 박람회 수출 전문 리서처입니다.
수집된 기사 본문에서 바이어 상담 시 증빙으로 제시할 핵심 문장을 발췌하고 번역하세요.

[원문 준수 엄격 규칙]
1. 원문 문장(quote)은 본문에 실제로 존재하는 문장을 그대로 가져오세요 (문형 임의 변형 금지).
2. 한국어 번역문(translation)을 정확하고 깔끔하게 작성하세요.
3. 기사별로 가장 중요한 1개 문장씩 발췌하세요.
4. 전체 기사를 종합하여 시장 핵심 요약 2줄을 작성하되 핵심 단어는 <b>태그로 강조하세요.

[수집된 원문 데이터]
{json.dumps(source_corpus, ensure_ascii=False)}

반드시 아래 JSON 포맷으로만 응답하세요:
{{
    "quotes": [
        {{
            "id": "E1",
            "quote": "원문 문장 그대로",
            "translation": "한국어 번역문"
        }}
    ],
    "summary": "핵심 키워드가 <b>태그로 강조된</b> 종합 2줄 요약"
}}
"""
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        ai_data = json.loads(res.choices[0].message.content)
        
        # 뱃지 판별 로직 적용
        final_quotes = []
        region_name = REGIONS_MAP.get(country, "해외")
        kw1 = kw_obj.get("kw1", "").lower()
        kw2 = kw_obj.get("kw2", "").lower()
        
        src_dict = {s["id"]: s for s in source_corpus}
        
        for q in ai_data.get("quotes", []):
            src_info = src_dict.get(q["id"], {})
            if not src_info:
                continue
                
            text_combo = (q["quote"] + " " + q["translation"] + " " + src_info["domain"]).lower()
            
            # 1. 공공기관 판별
            is_public = any(dom in src_info["domain"] for dom in ["kotra.or.kr", "kati.net"])
            
            # 2. 시장 판정
            if country.lower() in text_combo or (is_public and country in text_combo):
                market_badge = "대상 국가"
                market_type = "country"
            else:
                market_badge = f"권역 참고({region_name})"
                market_type = "region"
                
            # 3. 발췌 범위 판정
            if kw1 and kw1 in text_combo:
                scope_badge = "제품"
                scope_type = "product"
            elif kw2 and kw2 in text_combo:
                scope_badge = "제품군"
                scope_type = "category"
            elif any(k in text_combo for k in ["korean", "k-food", "한국", "korea"]):
                scope_badge = "한국 식품"
                scope_type = "kfood"
            else:
                scope_badge = "시장 일반"
                scope_type = "general"
                
            final_quotes.append({
                "id": src_info["id"],
                "domain": src_info["domain"],
                "year": src_info["year"],
                "url": src_info["url"],
                "quote": q["quote"],
                "translation": q["translation"],
                "is_public": is_public,
                "market_badge": market_badge,
                "market_type": market_type,
                "scope_badge": scope_badge,
                "scope_type": scope_type
            })
            
        return {
            "quotes": final_quotes,
            "summary": ai_data.get("summary", ""),
            "is_error": False
        }
    except Exception as e:
        return {"quotes": [], "summary": f"기사 분석 중 오류 발생: {str(e)}", "is_error": True}
"""market_trend_analysis/ 폴더의 분석 로직을 그대로 재사용하는 얇은 래퍼.

원본 폴더(market_trend_analysis/)는 건드리지 않고, 그 안의 core/*.py,
database/cache_manager.py 함수를 import해서 우리 Flask 앱(exhibition
상세 페이지 "트렌드 조사" 탭)에서 호출할 수 있게만 연결한다.
"""

import hashlib
import os
import sys

_MTA_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "market_trend_analysis")
if _MTA_ROOT not in sys.path:
    sys.path.insert(0, _MTA_ROOT)

from core.keyword_extractor import extract_keywords  # noqa: E402
from core.pytrends_engine import fetch_google_trends, COUNTRY_GEO_MAP  # noqa: E402
from core.lead_time_calculator import calculate_lead_time  # noqa: E402
from core.competitor_analyzer import analyze_competitors  # noqa: E402
from core.tavily_news_crawler import fetch_local_news  # noqa: E402
from database.cache_manager import get_cache, set_cache  # noqa: E402


def _cache_key(specs):
    raw_key = f"{specs['product_name']}_{specs['country']}_{specs['exhibition_month']}_v6"
    return hashlib.md5(raw_key.encode()).hexdigest()


def get_cached_analysis(specs):
    """네트워크 호출 없이 캐시만 조회한다."""
    return get_cache(_cache_key(specs))


def run_analysis(specs, force=False):
    """market_trend_analysis/run_trend.py의 index() 파이프라인 그대로."""
    if not force:
        cached = get_cached_analysis(specs)
        if cached:
            return cached

    keywords = extract_keywords(specs)
    kw_list = [keywords["kw1"], keywords["kw2"], keywords["kw3"]]

    trend_data = fetch_google_trends(kw_list, specs["country"])

    lead_time = calculate_lead_time(
        trend_data["12m"],
        keywords["kw1"],
        specs["exhibition_month"],
        country=specs["country"],
        product_name=specs["product_name"],
    )

    competitors = analyze_competitors(specs, keywords)
    news = fetch_local_news(specs["country"], keywords, specs["product_name"])

    payload = {
        "specs": specs,
        "keywords": keywords,
        "trend_data": trend_data,
        "lead_time": lead_time,
        "competitors": competitors,
        "news": news,
    }

    if not news.get("is_error"):
        set_cache(_cache_key(specs), payload)

    return payload

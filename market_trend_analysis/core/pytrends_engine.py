import pandas as pd
from pytrends.request import TrendReq
import time
import random
from datetime import datetime

COUNTRY_GEO_MAP = {
    "미국": "US", "United States": "US", "USA": "US",
    "영국": "GB", "United Kingdom": "GB", "UK": "GB",
    "베트남": "VN", "Vietnam": "VN",
    "독일": "DE", "Germany": "DE",
    "일본": "JP", "Japan": "JP",
    "말레이시아": "MY", "Malaysia": "MY"
}

def generate_fallback_series(keywords: list, periods: int, freq: str):
    dates = pd.date_range(end=datetime.now(), periods=periods, freq=freq).strftime('%Y-%m-%d').tolist()
    relative_series = {}
    independent_series = {}
    
    for kw in keywords:
        base_vals = [random.randint(15, 60) for _ in range(periods)]
        peak_idx = random.randint(0, periods - 1)
        base_vals[peak_idx] = random.randint(85, 100)
        relative_series[kw] = base_vals
        
        max_v = max(base_vals) or 1
        independent_series[kw] = [round((v / max_v) * 100) for v in base_vals]
        
    return {
        "dates": dates,
        "relative": relative_series,
        "independent": independent_series,
        "is_simulated": True
    }

def fetch_period_data(pytrends, keywords: list, timeframe: str, geo_code: str, fallback_periods: int, fallback_freq: str):
    try:
        pytrends.build_payload(kw_list=keywords[:3], timeframe=timeframe, geo=geo_code)
        df = pytrends.interest_over_time()
        
        if df.empty and geo_code:
            pytrends.build_payload(kw_list=keywords[:3], timeframe=timeframe, geo="")
            df = pytrends.interest_over_time()
            
        if df.empty:
            return generate_fallback_series(keywords, fallback_periods, fallback_freq)
            
        dates = df.index.strftime('%Y-%m-%d').tolist()
        relative_series = {}
        independent_series = {}
        
        for kw in keywords[:3]:
            if kw in df.columns:
                vals = df[kw].tolist()
                relative_series[kw] = vals
                max_v = max(vals) if max(vals) > 0 else 1
                independent_series[kw] = [round((v / max_v) * 100) for v in vals]
            else:
                relative_series[kw] = [0] * len(dates)
                independent_series[kw] = [0] * len(dates)
                
        return {
            "dates": dates,
            "relative": relative_series,
            "independent": independent_series,
            "is_simulated": False
        }
    except Exception:
        return generate_fallback_series(keywords, fallback_periods, fallback_freq)

def fetch_google_trends(keywords: list, country_name: str) -> dict:
    geo_code = COUNTRY_GEO_MAP.get(country_name, "")
    try:
        pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
    except Exception:
        pytrends = None

    if pytrends is None:
        return {
            "12m": generate_fallback_series(keywords, 52, 'W'),
            "5y": generate_fallback_series(keywords, 60, 'ME')
        }

    # 1. 최근 12개월(주간 단위) 수집
    data_12m = fetch_period_data(pytrends, keywords, 'today 12-m', geo_code, 52, 'W')
    time.sleep(1)  # 429 레이트 리밋 방지
    # 2. 최근 5년(월간 단위) 수집
    data_5y = fetch_period_data(pytrends, keywords, 'today 5-y', geo_code, 60, 'ME')

    return {
        "12m": data_12m,
        "5y": data_5y
    }

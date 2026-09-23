import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pytrends.request import TrendReq

COUNTRY_GEO_MAP = {
    "영국": "GB", "미국": "US", "독일": "DE", "프랑스": "FR", "일본": "JP",
    "베트남": "VN", "태국": "TH", "말레이시아": "MY", "인도네시아": "ID", "호주": "AU"
}

def generate_fallback_data(kw_list: list, timeframe: str) -> dict:
    if timeframe == 'today 12-m':
        dates = [(datetime.now() - timedelta(weeks=51-i)).strftime('%Y-%m-%d') for i in range(52)]
    else:
        dates = [(datetime.now() - timedelta(days=30*(59-i))).strftime('%Y-%m') for i in range(60)]
        
    independent = {}
    relative = {}
    
    for i, kw in enumerate(kw_list):
        base_curve = np.sin(np.linspace(0, 3.14 * 2, len(dates))) * 25 + 35
        noise = np.random.normal(0, 5, len(dates))
        curve = np.clip(base_curve + noise, 5, 100)
        
        if i == 0:
            curve[len(dates)//2] = 100
            
        independent[kw] = [int(x) for x in curve]
        scale = 1.0 if i == 0 else (0.5 if i == 1 else 0.75)
        relative[kw] = [int(x * scale) for x in curve]
        
    return {
        "dates": dates,
        "independent": independent,
        "relative": relative,
        "is_simulated": True
    }

def fetch_google_trends(kw_list: list, country_name: str) -> dict:
    geo = COUNTRY_GEO_MAP.get(country_name, "")
    pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
    
    result = {}
    for tf_key, tf_val in [("12m", "today 12-m"), ("5y", "today 5-y")]:
        try:
            pytrends.build_payload(kw_list, cat=0, timeframe=tf_val, geo=geo)
            df = pytrends.interest_over_time()
            
            if df.empty and geo != "":
                pytrends.build_payload(kw_list, cat=0, timeframe=tf_val, geo="")
                df = pytrends.interest_over_time()
                
            if df.empty:
                result[tf_key] = generate_fallback_data(kw_list, tf_val)
                continue
                
            dates = [d.strftime('%Y-%m-%d') if tf_key == '12m' else d.strftime('%Y-%m') for d in df.index]
            relative = {}
            independent = {}
            
            for kw in kw_list:
                series = df[kw].tolist() if kw in df.columns else [0] * len(dates)
                relative[kw] = [int(v) for v in series]
                max_v = max(series) if max(series) > 0 else 1
                independent[kw] = [int(round((v / max_v) * 100)) for v in series]
                
            result[tf_key] = {
                "dates": dates,
                "independent": independent,
                "relative": relative,
                "is_simulated": False
            }
        except Exception:
            result[tf_key] = generate_fallback_data(kw_list, tf_val)
            
    return result

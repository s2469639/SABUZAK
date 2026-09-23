"""WTO Timeseries API(api.wto.org/timeseries/v1)에서 국가 단위 평균 관세율을
참고용으로 가져온다.

주의: 이 API는 "이 나라 농산물 평균 관세가 몇 %"처럼 국가 전체를 뭉뚱그린
숫자만 주지, 특정 HS코드(품목) 하나의 정확한 세율은 안 준다
(indicator 목록을 확인해보니 관세율 관련 지표들의 productSectorClassificationCode가
전부 null - 품목 분류 자체가 없음). 그래서 제품별 정확한 세율(농림축산식품부
실데이터, tariff_lookup)을 대체하는 게 아니라, "이 나라는 전반적으로 농산물
수입 문턱이 높은 편인가" 정도를 보여주는 참고 수치로만 쓴다.

WTO_API_KEY(구독키, api.wto.org 포털에서 Timeseries API 구독 시 발급)가
없으면 조용히 None을 반환해 기능이 아예 꺼진 것처럼 동작한다 (app/services/
exchange.py의 EXCHANGE_API_KEY와 같은 패턴)."""

import os
import time

import requests

WTO_API_KEY = os.environ.get("WTO_API_KEY")

BASE = "https://api.wto.org/timeseries/v1"

# "Simple average MFN applied tariff" 지표. 무역가중 평균(TP_A_0030 등)도 있지만,
# 품목 하나하나의 특수 사정에 안 휘둘리는 단순 평균이 "이 나라 문턱이 대체로
# 높다/낮다" 참고용으로는 더 이해하기 쉬워서 이쪽을 쓴다.
INDICATOR_ALL_PRODUCTS = "TP_A_0010"
INDICATOR_AGRICULTURAL = "TP_A_0160"

_CACHE_TTL_SEC = 24 * 60 * 60  # 하루 1번이면 충분 (연 단위 통계라 자주 안 바뀜)
_cache: dict = {}  # {(country_iso3, indicator): (value_dict_or_None, fetched_at)}


def _fetch_latest(country_iso3: str, indicator: str):
    """이 지표의 이 나라 최신 연도 값 하나를 가져온다. 실패/데이터 없음 -> None."""
    cache_key = (country_iso3, indicator)
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SEC:
        return cached[0]

    result = None
    try:
        resp = requests.get(
            f"{BASE}/data",
            headers={"Ocp-Apim-Subscription-Key": WTO_API_KEY},
            params={"i": indicator, "r": country_iso3, "ps": "default", "pc": "default"},
            timeout=10,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if isinstance(rows, list) and rows:
                latest = max(rows, key=lambda r: r.get("year") or 0)
                if latest.get("value") is not None:
                    result = {"value": latest["value"], "year": latest.get("year")}
    except (requests.exceptions.RequestException, ValueError):
        pass

    _cache[cache_key] = (result, time.time())
    return result


def get_country_tariff_averages(country_iso3: str):
    """이 나라의 WTO 평균 관세율(전체 품목 / 농산물)을 참고용으로 반환.
    {"all_products": {"value": 6.5, "year": 2023}, "agricultural": {...}}
    형태이며, 둘 다 없으면 None (호출부에서 화면에 아예 안 보여주면 됨).
    WTO_API_KEY가 없거나 country_iso3가 없으면 바로 None."""
    if not WTO_API_KEY or not country_iso3:
        return None

    all_products = _fetch_latest(country_iso3, INDICATOR_ALL_PRODUCTS)
    agricultural = _fetch_latest(country_iso3, INDICATOR_AGRICULTURAL)

    if not all_products and not agricultural:
        return None

    return {"all_products": all_products, "agricultural": agricultural}

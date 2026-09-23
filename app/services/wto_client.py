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

try:
    import pycountry
except ImportError:
    pycountry = None

WTO_API_KEY = os.environ.get("WTO_API_KEY")

BASE = "https://api.wto.org/timeseries/v1"

# "Simple average MFN applied tariff" 지표. 무역가중 평균(TP_A_0030 등)도 있지만,
# 품목 하나하나의 특수 사정에 안 휘둘리는 단순 평균이 "이 나라 문턱이 대체로
# 높다/낮다" 참고용으로는 더 이해하기 쉬워서 이쪽을 쓴다.
INDICATOR_ALL_PRODUCTS = "TP_A_0010"
INDICATOR_AGRICULTURAL = "TP_A_0160"

_CACHE_TTL_SEC = 24 * 60 * 60  # 하루 1번이면 충분 (연 단위 통계라 자주 안 바뀜)
_cache: dict = {}  # {(country_iso3, indicator): (value_dict_or_None, fetched_at)}

# EU는 관세를 공동으로 매기는 관세동맹이라, WTO 통계에 개별 회원국이 아니라
# "European Union"(코드 918) 하나로만 잡힌다 (실제로 확인함 - 스페인
# 개별조회는 204 No Content, EU로는 데이터 있음). 개별 회원국으로 조회해서
# 데이터가 없으면 이 목록에 있는 나라는 EU 코드로 재시도한다.
EU_MEMBER_ISO3 = {
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA",
    "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD",
    "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE",
}
EU_REPORTER_CODE = "918"


def _to_wto_reporter_code(country_iso3: str):
    """WTO는 국가를 ISO3(알파벳)가 아니라 UN M49 숫자 코드로 받는다
    (예: 스페인 ESP -> "724", /reporters 엔드포인트로 실제 확인함). 이 숫자
    코드는 ISO 3166-1 numeric과 동일해서, pycountry의 country.numeric으로
    별도 API 호출 없이 바로 변환 가능하다."""
    if pycountry is None:
        return None
    try:
        country = pycountry.countries.get(alpha_3=country_iso3)
        return country.numeric if country else None
    except LookupError:
        return None


def _fetch_by_reporter_code(reporter_code: str, indicator: str):
    """WTO 리포터 코드(UN M49 숫자, 예: "724")로 최신 연도 값 하나를 가져온다.
    데이터 없음/실패 -> None."""
    try:
        resp = requests.get(
            f"{BASE}/data",
            headers={"Ocp-Apim-Subscription-Key": WTO_API_KEY},
            # head=M(machine-readable)을 안 주면 응답이 {"Dataset": [...]} 로
            # 한 번 더 감싸지고 필드명도 Value/Year처럼 대문자로 시작하는
            # "사람이 읽기 좋은" 형태로 온다 (실제로 확인함). M으로 명시해서
            # 평평한 배열 + 소문자 camelCase 필드로 받는다.
            params={
                "i": indicator, "r": reporter_code, "ps": "default", "pc": "default",
                "head": "M",
            },
            timeout=10,
        )
        if resp.status_code == 200 and resp.content:
            rows = resp.json()
            # head=M이어도 혹시 몰라 {"Dataset": [...]} 래핑까지 방어적으로 처리
            if isinstance(rows, dict):
                rows = rows.get("Dataset", [])
            if isinstance(rows, list) and rows:
                latest = max(rows, key=lambda r: r.get("year") or 0)
                if latest.get("value") is not None:
                    return {"value": latest["value"], "year": latest.get("year")}
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def _fetch_latest(country_iso3: str, indicator: str):
    """이 지표의 이 나라 최신 연도 값 하나를 가져온다. 실패/데이터 없음 -> None.
    EU 회원국은 개별 국가로 조회하면 데이터가 없는 경우가 많아(관세동맹이라
    EU 전체로만 보고됨), 그럴 때 EU 코드로 한 번 더 시도한다."""
    cache_key = (country_iso3, indicator)
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SEC:
        return cached[0]

    reporter_code = _to_wto_reporter_code(country_iso3)
    result = _fetch_by_reporter_code(reporter_code, indicator) if reporter_code else None

    if result is None and country_iso3 in EU_MEMBER_ISO3:
        result = _fetch_by_reporter_code(EU_REPORTER_CODE, indicator)
        if result:
            result["is_eu_aggregate"] = True  # 화면에 "EU 전체 기준"임을 밝혀야 함

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

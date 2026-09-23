"""박람회 개최국 통화 기준 실시간 환율 (ExchangeRate-API, exchangerate-api.com)."""

import os
import time

import pycountry
import requests
from babel.numbers import get_territory_currencies

from app.services.hscode import resolve_country_iso

EXCHANGE_API_KEY = os.environ.get("EXCHANGE_API_KEY")

_CURRENCY_KO_NAMES = {
    "USD": "미국 달러", "EUR": "유로", "JPY": "일본 엔", "CNY": "중국 위안",
    "GBP": "영국 파운드", "VND": "베트남 동", "THB": "태국 바트", "INR": "인도 루피",
    "AUD": "호주 달러", "CAD": "캐나다 달러", "SGD": "싱가포르 달러", "HKD": "홍콩 달러",
    "AED": "아랍에미리트 디르함", "SAR": "사우디 리얄", "MXN": "멕시코 페소",
    "BRL": "브라질 레알", "RUB": "러시아 루블", "ZAR": "남아공 랜드",
    "IDR": "인도네시아 루피아", "MYR": "말레이시아 링깃", "PHP": "필리핀 페소",
    "TRY": "튀르키예 리라", "CHF": "스위스 프랑", "NZD": "뉴질랜드 달러",
    "TWD": "대만 달러", "QAT": "카타르 리알", "KWD": "쿠웨이트 디나르",
    "PLN": "폴란드 즈워티", "MAD": "모로코 디르함",
}

_rate_cache = {}
_CACHE_TTL_SEC = 3600


def resolve_currency_code(country_name):
    """박람회 국가명(영문)으로 ISO 4217 통화 코드를 찾는다. 실패 시 None."""
    iso3 = resolve_country_iso(country_name)
    if not iso3:
        return None
    try:
        country = pycountry.countries.get(alpha_3=iso3)
        if not country:
            return None
        currencies = get_territory_currencies(country.alpha_2)
        return currencies[0] if currencies else None
    except Exception:
        return None


def _fetch_krw_rate(currency_code):
    cached = _rate_cache.get(currency_code)
    if cached and time.time() - cached[1] < _CACHE_TTL_SEC:
        return cached[0]

    try:
        resp = requests.get(
            f"https://v6.exchangerate-api.com/v6/{EXCHANGE_API_KEY}/pair/{currency_code}/KRW",
            timeout=5,
        )
        data = resp.json()
        if data.get("result") == "success":
            rate = data.get("conversion_rate")
            _rate_cache[currency_code] = (rate, time.time())
            return rate
    except Exception:
        pass
    return None


def get_exchange_info(country_name):
    """박람회 개최국 통화 → 원화 환율. {currency_code, currency_name, rate_krw} 또는 실패 시 None."""
    if not EXCHANGE_API_KEY:
        return None

    currency_code = resolve_currency_code(country_name)
    if not currency_code or currency_code == "KRW":
        return None

    rate = _fetch_krw_rate(currency_code)
    if rate is None:
        return None

    return {
        "currency_code": currency_code,
        "currency_name": _CURRENCY_KO_NAMES.get(currency_code, currency_code),
        "rate_krw": rate,
    }

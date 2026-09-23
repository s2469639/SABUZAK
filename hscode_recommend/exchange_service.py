import requests

# 주요 수입국별 현지 통화 매핑 사전
COUNTRY_CURRENCY_MAP = {
    "미국": {"currency": "USD", "name": "미국 달러"},
    "usa": {"currency": "USD", "name": "미국 달러"},
    "중국": {"currency": "CNY", "name": "중국 위안"},
    "china": {"currency": "CNY", "name": "중국 위안"},
    "일본": {"currency": "JPY", "name": "일본 엔"},
    "japan": {"currency": "JPY", "name": "일본 엔"},
    "베트남": {"currency": "VND", "name": "베트남 동"},
    "vietnam": {"currency": "VND", "name": "베트남 동"},
    "독일": {"currency": "EUR", "name": "유로"},
    "프랑스": {"currency": "EUR", "name": "유로"},
    "이탈리아": {"currency": "EUR", "name": "유로"},
    "오스트리아": {"currency": "EUR", "name": "유로"},
    "영국": {"currency": "GBP", "name": "영국 파운드"},
    "캐나다": {"currency": "CAD", "name": "캐나다 달러"},
    "호주": {"currency": "AUD", "name": "호주 달러"},
    "멕시코": {"currency": "MXN", "name": "멕시코 페소"},
    "브라질": {"currency": "BRL", "name": "브라질 레알"},
    "러시아": {"currency": "RUB", "name": "러시아 루블"},
    "우루과이": {"currency": "UYU", "name": "우루과이 페소"},
    "파라과이": {"currency": "PYG", "name": "파라과이 과라니"},
    "인도": {"currency": "INR", "name": "인도 루피"}
}

def get_country_currency(country_name: str):
    clean_name = str(country_name).strip().lower()
    return COUNTRY_CURRENCY_MAP.get(clean_name, {"currency": "USD", "name": "미국 달러 (기본)"})

def fetch_exchange_rates():
    """
    ExchangeRate-API를 사용하여 USD 기준 실시간 환율 정보를 가져옵니다.
    """
    url = "https://open.er-api.com/v6/latest/USD"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("rates", {})
    except Exception:
        pass
    return {}
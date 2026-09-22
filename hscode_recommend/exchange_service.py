import os
import requests
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 전 세계 주요 수입국 및 통화(Currency) 매핑 딕셔너리
COUNTRY_CURRENCY_MAP = {
    "중국": {"currency": "CNY", "name": "중국 위안 (CNY)"},
    "china": {"currency": "CNY", "name": "중국 위안 (CNY)"},
    "미국": {"currency": "USD", "name": "미국 달러 (USD)"},
    "usa": {"currency": "USD", "name": "미국 달러 (USD)"},
    "일본": {"currency": "JPY", "name": "일본 엔 (JPY)"},
    "japan": {"currency": "JPY", "name": "일본 엔 (JPY)"},
    "베트남": {"currency": "VND", "name": "베트남 동 (VND)"},
    "vietnam": {"currency": "VND", "name": "베트남 동 (VND)"},
    "독일": {"currency": "EUR", "name": "유로 (EUR)"},
    "germany": {"currency": "EUR", "name": "유로 (EUR)"},
    "영국": {"currency": "GBP", "name": "영국 파운드 (GBP)"},
    "uk": {"currency": "GBP", "name": "영국 파운드 (GBP)"},
    "프랑스": {"currency": "EUR", "name": "유로 (EUR)"},
    "호주": {"currency": "AUD", "name": "호주 달러 (AUD)"},
    "캐나다": {"currency": "CAD", "name": "캐나다 달러 (CAD)"},
    "인도": {"currency": "INR", "name": "인도 루피 (INR)"},
    "브라질": {"currency": "BRL", "name": "브라질 헤알 (BRL)"},
    "칠레": {"currency": "CLP", "name": "칠레 페소 (CLP)"}
}

def get_country_currency(val: str):
    clean = str(val).strip().lower()
    if clean in COUNTRY_CURRENCY_MAP:
        return COUNTRY_CURRENCY_MAP[clean]
    else:
        return {"currency": "USD", "name": f"미국 달러 (USD) - {val}"}

def fetch_exchange_rates():
    """ExchangeRate-API를 통해 USD 기준 전 세계 환율 데이터를 가져옴"""
    api_key = os.getenv("EXCHANGE_API_KEY")
    if not api_key:
        return None, "API 키가 .env 파일에 설정되지 않았습니다."
    
    url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/USD"
    try:
        response = requests.get(url)
        data = response.json()
        if data.get("result") == "success":
            return data.get("conversion_rates", {}), None
        else:
            return None, "API 응답 오류 발생"
    except Exception as e:
        return None, str(e)
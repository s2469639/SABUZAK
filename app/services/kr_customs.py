"""한국 관세청 수출입무역통계(품목·국가별, nitemtrade) - "한국의 OO 수출 추이".

UN Comtrade가 "전 세계 대비 시장 규모/한국 점유율"을 보여준다면, 이 모듈은
관세청이 직접 집계한 "한국이 그 나라에 실제로 얼마나 수출했는가"(FOB 기준)를
보여준다. data.go.kr의 "관세청_수출입무역통계" 서비스(getNitemtradeList)를
쓰며, 무료 API키(DATA_GO_KR_API_KEY)가 필요하다.

⚠️ un_v6/test_customs.py로 파라미터 구조까지는 확인했지만, 이 환경은
apis.data.go.kr 접속이 막혀 있어 실제 응답 스키마를 직접 받아본 적은 없다.
컬럼명(statKor, expDlr 등)은 공공데이터포털 문서 기준으로 가정한 것이라,
실제 배포 환경에서 첫 호출 실패 시 응답 원문을 보고 컬럼명을 맞춰야 할 수
있다. 그래서 키가 없거나 호출이 실패해도 화면의 다른 섹션에는 영향이 없게
예외를 그 안에서만 삼킨다.
"""

import os

import requests

NITEMTRADE_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"

# data.go.kr 관세청 통계가 쓰는 국가부호(우리나라 관세청 고유 코드, ISO2와
# 대체로 같지만 전부 일치하진 않는다). 한국의 주요 교역 상대국 위주로만
# 채워뒀다 - 여기 없는 나라는 "국가부호를 알 수 없음"으로 표시한다.
ISO3_TO_CUSTOMS_CODE = {
    "USA": "US", "CHN": "CN", "JPN": "JP", "VNM": "VN", "DEU": "DE",
    "GBR": "GB", "FRA": "FR", "IND": "IN", "THA": "TH", "IDN": "ID",
    "MYS": "MY", "PHL": "PH", "SGP": "SG", "AUS": "AU", "CAN": "CA",
    "MEX": "MX", "BRA": "BR", "ITA": "IT", "ESP": "ES", "NLD": "NL",
    "RUS": "RU", "SAU": "SA", "ARE": "AE", "HKG": "HK", "CHE": "CH",
    "TUR": "TR",
}


def get_api_key():
    return os.getenv("DATA_GO_KR_API_KEY")


def customs_code_for(target_iso3: str) -> str | None:
    return ISO3_TO_CUSTOMS_CODE.get(target_iso3)


def get_kr_export_trend(hscode6: str, target_iso3: str, years: list[int], timeout=20) -> dict:
    """한국 -> target_iso3, HS6자리 품목의 연도별 수출액(FOB, USD) 추이.
    키가 없거나 국가부호를 모르거나 호출이 실패하면 available=False +
    reason만 채워서 돌려준다 (화면에서 그대로 안내 문구로 씀)."""
    api_key = get_api_key()
    if not api_key:
        return {"available": False, "reason": "DATA_GO_KR_API_KEY가 설정되어 있지 않습니다.", "by_year": []}

    customs_code = customs_code_for(target_iso3)
    if not customs_code:
        return {"available": False, "reason": f"'{target_iso3}'의 관세청 국가부호를 찾지 못했습니다.", "by_year": []}

    by_year = []
    try:
        for year in years:
            resp = requests.get(
                NITEMTRADE_URL,
                params={
                    "serviceKey": api_key,
                    "strtYymm": f"{year}01",
                    "endYymm": f"{year}12",
                    "hsSgn": hscode6,
                    "cntyCd": customs_code,
                    "type": "json",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            items = (
                payload.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            )
            if isinstance(items, dict):
                items = [items]
            export_usd = 0.0
            found = False
            for item in items:
                value = item.get("expDlr")
                if value in (None, ""):
                    continue
                export_usd += float(value)
                found = True
            by_year.append({
                "year": year,
                "export_value_usd": export_usd if found else None,
            })
    except Exception as e:
        return {"available": False, "reason": f"관세청 자료를 불러오지 못했습니다 ({e}).", "by_year": []}

    if not any(y["export_value_usd"] is not None for y in by_year):
        return {"available": False, "reason": "해당 기간의 관세청 수출 통계가 없습니다.", "by_year": []}

    cagr_pct = None
    first = next((y for y in by_year if y["export_value_usd"]), None)
    last = next((y for y in reversed(by_year) if y["export_value_usd"]), None)
    if first and last and first is not last:
        num_years = last["year"] - first["year"]
        if num_years > 0 and first["export_value_usd"]:
            cagr_pct = round(
                ((last["export_value_usd"] / first["export_value_usd"]) ** (1 / num_years) - 1) * 100, 1
            )

    return {"available": True, "reason": None, "by_year": by_year, "cagr_pct": cagr_pct}

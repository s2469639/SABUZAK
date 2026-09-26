"""
macmap.org 내부 API 호출 클라이언트 (scripts/market/macmap_api.py 로직을 그대로 가져옴).

x-api-key 없이 세션 쿠키 + Referer 헤더로 동작하는 비공식(그러나 스크래핑이 아닌
내부 API 직접 호출) 방식. 이 모듈은 sync 스크립트(scripts/market/sync_ntm_cache.py)
에서만 사용하고, 웹앱 요청 경로에서는 절대 직접 호출하지 않는다 — 대신
NtmMeasure 캐시 테이블을 읽는다.
"""

import time

import requests

BASE = "https://www.macmap.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SEC = 2  # 매너 크롤링 - 요청 간 최소 대기
KOREA_M49 = "410"  # 수출국(partner) 고정값


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"})
    s.get(f"{BASE}/en/query/results", timeout=15)
    return s


def fetch_ntm(session: requests.Session, reporter_m49: str, product_hs: str, partner_m49: str = KOREA_M49) -> list:
    """비관세조치(NTM) 원본 JSON을 가져온다. reporter=수입국(대상 시장), partner=수출국(한국)."""
    url = f"{BASE}/api/results/ntm-measures"
    params = {"reporter": reporter_m49, "partner": partner_m49, "product": product_hs}
    referer = (
        f"{BASE}/en/query/results?reporter={reporter_m49}&partner={partner_m49}"
        f"&product={product_hs}&level=6"
    )
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    resp = session.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.json()


def flatten_ntm(data: list, reporter: str, partner: str, product: str) -> list:
    """ntm-measures 응답을 DB에 저장하기 좋은 평평한 dict 리스트로 변환."""
    rows = []
    for group in data:
        section = group.get("MeasureSection", "")
        source = group.get("DataSource", "")
        for m in group.get("AllMeasures", []):
            rows.append({
                "reporter": reporter,
                "partner": partner,
                "product": product,
                "measure_section": section,
                "measure_code": m.get("Code", ""),
                "measure_title": m.get("Title", ""),
                "measure_summary": m.get("Summary", ""),
                "legislation_title": m.get("LegislationTitle", ""),
                "legislation_summary": m.get("LegislationSummary", ""),
                "implementation_authority": m.get("ImplementationAuthority", ""),
                "start_date": m.get("StartDate", ""),
                "end_date": m.get("EndDate", ""),
                "web_link": m.get("WebLink", ""),
                "data_source": source,
            })
    return rows


def fetch_ntm_rows(session: requests.Session, reporter_m49: str, product_hs: str, partner_m49: str = KOREA_M49) -> list:
    data = fetch_ntm(session, reporter_m49, product_hs, partner_m49)
    time.sleep(REQUEST_DELAY_SEC)
    return flatten_ntm(data, reporter_m49, partner_m49, product_hs)

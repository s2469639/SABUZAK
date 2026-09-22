"""
UNCTAD TRAINS Online(trainsonline.unctad.org) 내부 API 클라이언트.

macmap.org 대신 사용. macmap은 Cloudflare로 완전히 막혀서(403 + JS challenge)
requests로는 접근 불가능해졌지만, TRAINS Online(macmap이 원래 참조하는 원본
데이터 출처)은 별도 보호 없이 그대로 호출된다.

브라우저 개발자도구로 확인한 실제 엔드포인트:
    POST https://api-trains2.unctad.org/export-regulations
    Content-Type: application/json
    {
      "imposingCountries": ["SGP"],
      "products": ["190590", ...],   # HS코드 문자열 그대로 (내부 ID 변환 불필요)
      "exportTo": "csv",
      "columnsVisibility": {...},
      "pageNumber": 1, "pageSize": 200
    }

응답은 CSV 텍스트인데, 앞부분에 메타 안내 줄이 몇 줄 붙어있고 그 다음에
진짜 헤더 행("Economies applying the regulation,...")이 나온다.
"""

import csv
import io

import requests

BASE = "https://api-trains2.unctad.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

COLUMNS_VISIBILITY = {
    "imposingCountryName": True,
    "officialTitle": True,
    "officialTitleOriginal": False,
    "implementationDate": True,
    "repealDate": False,
    "agencies": True,
    "hsCodes": True,
    "affectedProductsDesc": False,
    "links": True,
    "documentation": True,
    "description": True,
    "descriptionOriginal": False,
    "source": False,
    "publicationDate": False,
    "publicationSymbol": False,
    "symbol": False,
    "ntmTypes": True,
}


def fetch_regulations_csv(country_iso3: str, hs_codes: list, page_size: int = 500) -> str:
    """국가(ISO3) + HS코드 목록으로 규정 목록을 CSV 텍스트로 받는다."""
    payload = {
        "imposingCountries": [country_iso3],
        "internationalStandardsImposing": False,
        "FromDate": None,
        "NTMType": None,
        "ToDate": None,
        "columnsVisibility": COLUMNS_VISIBILITY,
        "exportTo": "csv",
        "pageNumber": 1,
        "pageSize": page_size,
        "products": list(hs_codes),
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://trainsonline.unctad.org",
        "Referer": "https://trainsonline.unctad.org/",
        "User-Agent": UA,
    }
    resp = requests.post(f"{BASE}/export-regulations", json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def parse_regulations_csv(csv_text: str) -> list:
    """앞의 메타 안내 줄들을 건너뛰고, 진짜 헤더 행부터 DictReader로 파싱."""
    lines = csv_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("Economies applying the regulation"):
            header_idx = i
            break
    if header_idx is None:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    return [
        row
        for row in reader
        if row.get("Official title in English", "").strip() not in ("", "-")
    ]


def fetch_regulations(country_iso3: str, hs_codes: list, page_size: int = 500) -> list:
    """국가+HS코드 -> 파싱된 규정 dict 리스트."""
    csv_text = fetch_regulations_csv(country_iso3, hs_codes, page_size=page_size)
    return parse_regulations_csv(csv_text)


def to_ntm_measure_rows(country_iso3: str, product_key: str, regulations: list) -> list:
    """파싱된 규정 dict 리스트 -> NtmMeasure(**row) 로 바로 넣을 수 있는 dict 리스트.
    CSV 헤더 이름(Show/Hide Column(s)에서 켠 컬럼들 기준)을 우리 모델 컬럼에 매핑.
    product_key는 실제 필터링이 안 되므로 보통 "ALL" 고정값을 넘긴다."""
    rows = []
    for reg in regulations:
        rows.append({
            "reporter": country_iso3,
            "partner": "KOR",
            "product": product_key,
            "measure_code": "",
            "measure_section": reg.get("NTM Types", ""),
            "measure_title": reg.get("Official title in English", ""),
            "measure_summary": reg.get("Regulation description in English", ""),
            "legislation_title": reg.get("Official title in English", ""),
            "legislation_summary": reg.get("Regulation description in English", ""),
            "implementation_authority": reg.get("Agencies", ""),
            "start_date": reg.get("Implementation date", ""),
            "end_date": reg.get("Repeal Date", ""),
            "web_link": reg.get("Documents") or reg.get("Links") or "",
            "data_source": "UNCTAD TRAINS",
        })
    return rows

"""
UNCTAD TRAINS Online(trainsonline.unctad.org) 내부 API 클라이언트.

macmap.org 대신 사용. macmap은 Cloudflare로 완전히 막혀서(403 + JS challenge)
requests로는 접근 불가능해졌다.

2026-09 기준 실제로 확인된 엔드포인트(브라우저 개발자도구로 확인, "Detailed
search" 화면 - 예전에 참고했던 export-regulations는 지금 404가 뜨는 걸 보면
이미 없어진 것으로 보임):

    POST https://api-trains2.unctad.org/denormalisedMeasures
    Content-Type: application/json
    {
      "imposingCountries": [202],       # UNCTAD 내부 숫자 ID (ISO코드 아님!)
      "allImposingCountries": false,
      "affectedCountries": [117],       # 마찬가지로 내부 숫자 ID
      "allAffectedCountries": false,
      "products": [2451798, ...],       # 이것도 내부 숫자 ID (HS코드 아님!)
      "allProducts": false,
      "pageNumber": 1, "pageSize": 20,
      "columnsVisibility": {...},
      "exportTo": "excel"
    }
    -> JSON 배열 응답 (Excel/CSV 아님). 필드명 그대로 사용 가능:
       countryImposingNTMs(국가명 문자열), ntmCode, ntmDescription,
       measureDescription, hsCode, regulationTitle, implementationDate,
       issuingAgency, regulationFile, affectedCountriesNames, ...

문제: "imposingCountries"/"affectedCountries"/"products"는 ISO코드나
HS코드가 아니라 UNCTAD 내부 전용 숫자 ID라서, 어떤 코드가 어느 나라/품목인지
알아내려면 그 나라를 프론트엔드 드롭다운에서 직접 선택해봐야 한다. 그래서
이 클라이언트는 나라 ID를 몰라도 되도록 **"allImposingCountries": true로
전세계를 한 번에 조회한 뒤, 응답에 이미 문자열로 들어있는
countryImposingNTMs 값으로 우리 쪽에서 국가를 매칭**하는 방식을 쓴다.
"affectedCountries"(한국에 영향 주는 것만)만 미리 확인해둔 한국의 ID(117)로
고정한다.

주의: 이 방식은 한 번 호출로 전세계 규정을 다 받아오기 때문에(페이지네이션
필요) 국가 하나만 볼 때도 다소 느릴 수 있다. 대신 국가 ID 매핑표를 유지할
필요가 없다는 장점이 있다.
"""

import requests

try:
    import pycountry
except ImportError:
    pycountry = None

BASE = "https://api-trains2.unctad.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# "Affected Markets"에서 "Korea, Republic of"를 선택했을 때 실제로 확인된
# UNCTAD 내부 숫자 ID. (imposingCountries와 달리 이건 항상 한국 고정이라
# 하나만 알면 됨.)
KOREA_AFFECTED_COUNTRY_ID = 117

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://trainsonline.unctad.org",
    "Referer": "https://trainsonline.unctad.org/",
    "User-Agent": UA,
}

COLUMNS_VISIBILITY = {
    "countryImposingNTMsVisible": True,
    "affectedCountriesNamesVisible": True,
    "ntmCodeVisible": True,
    "ntmDescriptionVisible": True,
    "measureDescriptionVisible": True,
    "productDescriptionVisible": True,
    "hsCodeVisible": True,
    "issuingAgencyVisible": True,
    "regulationTitleVisible": True,
    "regulationSymbolVisible": False,
    "implementationDateVisible": True,
    "regulationFileVisible": True,
    "regulationOfficialTitleOriginalVisible": False,
    "measureDescriptionOriginalVisible": False,
    "measureProductDescriptionOriginalVisible": False,
    "supportingRegulationsVisible": False,
    "measureObjectivesOriginalVisible": False,
    "yearsOfDataCollectionVisible": False,
    "repealDateVisible": True,
    "objectiveCodesVisible": True,
}


def _payload(page_number: int, page_size: int) -> dict:
    return {
        "imposingCountries": [],
        "allImposingCountries": True,
        "internationalStandardsImposing": False,
        "affectedCountries": [KOREA_AFFECTED_COUNTRY_ID],
        "allAffectedCountries": False,
        "products": [],
        "allProducts": True,
        "NTMType": None,
        "ExcludeHorizontalMeasures": None,
        "FromDate": None,
        "ToDate": None,
        "IsImportNtm": None,
        "IsUnilateral": None,
        "pageNumber": page_number,
        "pageSize": page_size,
        "columnsVisibility": COLUMNS_VISIBILITY,
        "exportTo": "excel",
    }


def fetch_all_measures_affecting_korea(page_size: int = 500, max_pages: int = 30) -> list:
    """한국에 영향을 주는 전세계 비관세조치(NTM)를 전부 가져온다 (페이지네이션 처리).

    국가 ID를 몰라도 되도록 전세계(allImposingCountries=true)를 조회하고,
    각 행의 countryImposingNTMs(국가명 문자열)로 나중에 걸러서 쓴다.
    응답 형식이 예상과 다르면(리스트가 아니면) 명확한 예외를 던진다."""
    all_rows = []
    for page in range(1, max_pages + 1):
        resp = requests.post(
            f"{BASE}/denormalisedMeasures",
            json=_payload(page, page_size),
            headers=HEADERS,
            timeout=60,
        )
        resp.raise_for_status()
        try:
            batch = resp.json()
        except ValueError as exc:
            preview = resp.text[:300]
            raise ValueError(
                f"TRAINS 응답이 JSON이 아닙니다 (형식이 또 바뀌었을 수 있음). "
                f"응답 앞부분: {preview!r}"
            ) from exc

        if not isinstance(batch, list):
            raise ValueError(f"TRAINS 응답이 예상한 배열 형식이 아닙니다: {type(batch)}")

        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
    return all_rows


def _resolve_country_name(name: str):
    """UNCTAD가 준 국가명 문자열(예: 'Singapore')을 ISO3로 변환.
    app.services.hscode.resolve_country_iso와 동일한 규칙을 쓰되, 순환
    import를 피하려 여기서 pycountry를 직접 부른다."""
    if not name:
        return None
    if pycountry is None:
        return None
    try:
        country = pycountry.countries.get(name=name.strip())
        if country:
            return country.alpha_3
        matches = pycountry.countries.search_fuzzy(name.strip())
        if matches:
            return matches[0].alpha_3
    except LookupError:
        pass
    return None


def fetch_regulations_for_country(country_iso3: str, page_size: int = 500) -> list:
    """전세계 조회 결과 중 country_iso3(예: 'SGP')에 해당하는 것만 걸러서 반환."""
    all_rows = fetch_all_measures_affecting_korea(page_size=page_size)
    matched = []
    for row in all_rows:
        row_iso3 = _resolve_country_name(row.get("countryImposingNTMs"))
        if row_iso3 == country_iso3:
            matched.append(row)
    return matched


def group_measures_by_country(all_rows: list) -> dict:
    """fetch_all_measures_affecting_korea()로 받은 전세계 결과를 국가(ISO3)별로
    묶는다. 여러 나라를 한 번에 캐싱할 때(sync_ntm_cache.py) 나라마다 다시
    전세계 조회를 반복하지 않도록 쓴다. 국가명을 ISO3로 못 바꾼 행은 버린다."""
    grouped = {}
    for row in all_rows:
        iso3 = _resolve_country_name(row.get("countryImposingNTMs"))
        if not iso3:
            continue
        grouped.setdefault(iso3, []).append(row)
    return grouped


def to_ntm_measure_rows(country_iso3: str, product_key: str, regulations: list) -> list:
    """denormalisedMeasures 응답 dict 리스트 -> NtmMeasure(**row)에 바로 넣을 dict 리스트."""
    rows = []
    for reg in regulations:
        rows.append({
            "reporter": country_iso3,
            "partner": "KOR",
            "product": product_key,
            "measure_code": reg.get("ntmCode") or "",
            "measure_section": reg.get("ntmType") or "",
            "measure_title": reg.get("regulationTitle") or reg.get("ntmDescription") or "",
            "measure_summary": reg.get("measureDescription") or "",
            "legislation_title": reg.get("regulationTitle") or "",
            "legislation_summary": reg.get("measureDescription") or "",
            "implementation_authority": reg.get("issuingAgency") or "",
            "start_date": reg.get("implementationDate") or "",
            "end_date": reg.get("repealDate") or "",
            "web_link": "",  # regulationFile은 URL이 아니라 파일명이라 링크로 못 씀
            "data_source": "UNCTAD TRAINS",
        })
    return rows

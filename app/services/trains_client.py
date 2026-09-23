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
이 클라이언트는 나라 ID를 몰라도 되도록 **"전체 국가 선택"을 브라우저에서
직접 해보고 캡처한 실제 요청**을 그대로 흉내낸다: "allImposingCountries":
true만 보내면 400이 나고, 실제로는 UNCTAD가 아는 모든 나라 ID를
"imposingCountries" 배열에 통째로 채워서 보내야 한다 (ALL_IMPOSING_COUNTRY_IDS,
아래 참고). 그 결과에서 응답에 이미 문자열로 들어있는 countryImposingNTMs
값으로 우리 쪽에서 국가를 매칭한다.

"affectedCountries"는 한국(117) + World(999, EU/World 같은 그룹 ID로 추정)로
고정. "products"도 "전체 상품" 대신, 사부작 제품군(약과/유과 등)에 해당하는
"Bread, gingerbread and the like, sweet biscuits..." 카테고리(HS 1905 계열)
ID를 그대로 고정 필터로 쓴다 - 마침 이게 우리가 필요한 카테고리와 일치해서,
어차피 국가 전체 규정 중 식품 관련만 추리던 예전 방식보다 오히려 더 정확한
필터링이 된다.
"""

from urllib.parse import quote

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
# 하나만 알면 됨.) 999는 "Select All" 캡처 시 같이 딸려온 ID로, World/EU 같은
# 그룹을 가리키는 것으로 추정 - 그대로 포함해서 흉내낸다.
AFFECTED_COUNTRY_IDS = [117, 999]

# "Economies applying the NTMs"에서 "Select All"을 눌렀을 때 실제로 전송된
# 전체 국가(+그룹) ID 목록. allImposingCountries=true만 보내면 400이 나서,
# "전체 선택"을 흉내내려면 이 목록을 그대로 같이 보내야 한다.
ALL_IMPOSING_COUNTRY_IDS = [
    1, 2, 4, 8, 10, 16, 11, 12, 9, 13, 14, 15, 17, 34, 18, 59, 21, 22, 23, 25,
    30, 31, 242, 33, 38, 35, 36, 37, 42, 43, 44, 48, 49, 51, 53, 54, 55, 56,
    57, 58, 110, 52, 60, 61, 63, 234, 64, 68, 215, 66, 279, 72, 73, 75, 80,
    82, 81, 84, 85, 88, 90, 93, 94, 95, 99, 100, 101, 102, 103, 104, 107,
    108, 109, 111, 112, 114, 113, 115, 87, 277, 118, 119, 120, 123, 121, 122,
    124, 127, 128, 131, 132, 134, 135, 168, 137, 138, 139, 167, 142, 143,
    145, 146, 32, 148, 149, 150, 151, 158, 159, 160, 161, 162, 233, 164, 147,
    170, 169, 83, 171, 172, 173, 174, 175, 177, 178, 182, 184, 185, 186, 247,
    197, 198, 199, 200, 202, 203, 205, 28, 207, 117, 209, 41, 213, 216, 217,
    219, 239, 220, 180, 221, 223, 224, 226, 230, 227, 231, 225, 240, 243,
    157, 245, 204, 249, 208, 999,
]

# "Products affected"에서 "Bread, gingerbread and the like, sweet biscuits..."
# 카테고리(HS 1905 계열 - 약과/유과 등 사부작 제품군과 일치)를 선택했을 때
# 실제로 전송된 UNCTAD 내부 상품 ID 목록. "전체 상품"이 아니라 이 카테고리로
# 고정해서 쓴다 (오히려 우리 제품군에 딱 맞는 필터가 됨).
SNACK_PRODUCT_IDS = [2451798, 2451799, 2451800, 2451802, 2451803, 2451804, 2451805]

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
        "imposingCountries": ALL_IMPOSING_COUNTRY_IDS,
        "allImposingCountries": True,
        "internationalStandardsImposing": False,
        "affectedCountries": AFFECTED_COUNTRY_IDS,
        "allAffectedCountries": False,
        "products": SNACK_PRODUCT_IDS,
        "allProducts": False,
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


def fetch_all_measures_affecting_korea(page_size: int = 20, max_pages: int = 100) -> list:
    """한국에 영향을 주는 전세계 비관세조치(NTM)를 전부 가져온다 (페이지네이션 처리).

    국가 ID를 몰라도 되도록 전세계(allImposingCountries=true)를 조회하고,
    각 행의 countryImposingNTMs(국가명 문자열)로 나중에 걸러서 쓴다.
    응답 형식이 예상과 다르면(리스트가 아니면) 명확한 예외를 던진다.

    page_size 기본값 20: 실제로 500을 보내면 서버가 400 Bad Request로
    거부하는 걸 확인함 (브라우저가 실제로 쓰는 값인 20으로 검증됨). 더 큰
    값이 어디까지 허용되는지 확인 안 됐으니 함부로 올리지 말 것."""
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


def fetch_regulations_for_country(country_iso3: str, page_size: int = 20) -> list:
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


# 식품/농산물 수출과 관련 있을 법한 규정을 상위로 올리는 키워드
# (app/services/hscode.py의 _FOOD_RELEVANCE_KEYWORDS와 같은 기준)
_FOOD_RELEVANCE_KEYWORDS = [
    "food", "animal", "plant", "fish", "meat", "agricultur", "consumer",
    "biological", "sanitary", "phytosanitary", "veterinary", "poultry",
    "livestock", "seafood", "beverage", "packaging", "labell", "labeling",
    "import", "export", "custom",
]


def _relevance_score(reg: dict) -> int:
    text = " ".join([
        reg.get("regulationTitle") or "",
        reg.get("measureDescription") or "",
        reg.get("ntmDescription") or "",
    ]).lower()
    return sum(1 for kw in _FOOD_RELEVANCE_KEYWORDS if kw in text)


def top_relevant_regulations(regulations: list, limit: int = 6) -> list:
    """식품/농산물 관련도가 높은 순으로 상위 N개만 남긴다 (전체를 다 저장하면
    화면도 지저분해지고 AI 요약 비용도 커지므로, 정말 중요한 것만 추림)."""
    return sorted(regulations, key=_relevance_score, reverse=True)[:limit]


def summarize_regulation_ko(title: str, description: str) -> str:
    """영문 규정 제목/설명을 한국 식품 수출 담당자가 바로 이해할 수 있게
    한국어 1~2문장으로 요약. OpenAI 키가 없거나 호출이 실패하면 원문을
    그냥 짧게 잘라서 대체한다 (기능이 완전히 멈추지 않도록)."""
    try:
        from app.services.openai_client import get_client

        prompt = (
            "다음은 어떤 나라가 수입 식품에 대해 시행 중인 법령/비관세조치(NTM) 설명입니다. "
            "한국 식품 수출업체 담당자가 실무에서 바로 참고할 수 있도록, "
            "핵심만 한국어 1~2문장으로 요약하세요. 다른 설명 없이 요약 문장만 출력하세요.\n\n"
            f"제목: {title or '(제목 없음)'}\n"
            f"설명: {(description or '')[:2000]}"
        )
        response = get_client().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = (response.choices[0].message.content or "").strip()
        if summary:
            return summary
    except Exception:
        pass

    # 폴백: 원문 앞부분만 잘라서라도 보여준다 (AI 요약 실패해도 완전히 비진 않게)
    fallback = (description or title or "").strip()
    return (fallback[:200] + "…") if len(fallback) > 200 else fallback


def to_ntm_measure_rows(country_iso3: str, product_key: str, regulations: list, summarize: bool = True) -> list:
    """denormalisedMeasures 응답 dict 리스트 -> NtmMeasure(**row)에 바로 넣을 dict 리스트.
    summarize=True면 각 항목을 한국어 1~2문장으로 요약해서 저장한다 (호출부에서
    이미 top_relevant_regulations로 최대 6개까지 추린 뒤에 넘기는 걸 권장 -
    그래야 AI 요약 호출 횟수도 6번으로 제한됨)."""
    rows = []
    for reg in regulations:
        title = reg.get("regulationTitle") or reg.get("ntmDescription") or ""
        description = reg.get("measureDescription") or ""
        summary_ko = summarize_regulation_ko(title, description) if summarize else description

        regulation_file = reg.get("regulationFile")
        web_link = (
            f"{BASE}/get-regulation-file?filename={quote(regulation_file)}"
            if regulation_file
            else ""
        )

        rows.append({
            "reporter": country_iso3,
            "partner": "KOR",
            "product": product_key,
            "measure_code": reg.get("ntmCode") or "",
            "measure_section": reg.get("ntmType") or "",
            "measure_title": title,
            "measure_summary": summary_ko,
            "legislation_title": title,
            "legislation_summary": summary_ko,
            "implementation_authority": reg.get("issuingAgency") or "",
            "start_date": reg.get("implementationDate") or "",
            "end_date": reg.get("repealDate") or "",
            "web_link": web_link,
            "data_source": "UNCTAD TRAINS",
        })
    return rows

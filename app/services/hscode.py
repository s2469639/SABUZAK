"""
HS코드 & 수출 주의사항 탭용 서비스.

관세율: app/services/tariff_lookup.py가 농림축산식품부 "농축산물 FTA
협정세율 현황"(공공데이터포털) 실데이터를 HS코드+국가로 조회해준다.
예전엔 사람이 손으로 입력한 고정표(TARIFF_PROFILES)를 썼는데, 존재하지
않는 협정을 있는 것처럼 보여주는 오류가 있어서 실데이터로 교체했다.

비관세장벽(NTM): UNCTAD TRAINS Online 내부 API(app/services/trains_client.py)에서
가져온 실데이터를 쓴다. macmap.org는 Cloudflare로 완전히 막혀서 포기하고,
macmap이 원래 참조하는 원본 데이터 출처인 TRAINS Online으로 교체했다.

주의: TRAINS Online의 "Explore Regulations" 내보내기는 실제로 테스트해보니
product(HS코드) 필터와 무관하게 그 나라의 전체 무역 규정 목록을 그대로
반환한다 (HS Codes 컬럼도 대부분 비어있음). 즉 이건 "이 HS코드에 해당하는
규정"이 아니라 "이 나라의 수출입 관련 법령 전체 목록"이다. 그래서 제품별로
쪼개서 캐싱하지 않고 국가 하나당 한 번만 조회하고, 식품/농산물 관련 키워드로
관련도를 매겨 상위 몇 개만 보여주는 방식으로 처리한다.

페이지 로드마다 직접 부르지 않고, scripts/market/sync_ntm_cache.py 또는 상세
페이지의 "지금 실제 데이터 가져오기" 버튼이 NtmMeasure 테이블에 채워둔 캐시를
읽기만 한다. 캐시가 아직 없는 국가는 DEFAULT_REGULATION_NOTES로 폴백한다.

NtmMeasure.reporter 컬럼은 ISO3(예: "SGP")를 저장하고, product 컬럼은
국가 단위 조회라 "ALL" 고정값을 쓴다.
"""

from app.models import NtmMeasure
from app.services import tariff_lookup
from app.services import trains_client

try:
    import pycountry
except ImportError:
    pycountry = None

# 법령 제목/요약 텍스트로 필수/정보/주의 등급을 대략 나누는 키워드
_MANDATORY_KEYWORDS = [
    "registration", "mandatory", "requirement", "authorization", "license",
    "certificat", "must", "prohibit", "ban",
]
_CAUTION_KEYWORDS = ["labelling", "labeling", "tbt", "sps", "inspection", "testing", "residue"]

# 국가 전체 규정 목록 중 식품/농산물 수출과 관련 있을 법한 것만 상위로 올리는 키워드
_FOOD_RELEVANCE_KEYWORDS = [
    "food", "animal", "plant", "fish", "meat", "agricultur", "consumer",
    "biological", "sanitary", "phytosanitary", "veterinary", "poultry",
    "livestock", "seafood", "beverage", "packaging", "labell", "labeling",
    "import", "export", "custom",
]

# 국가명(Exhibition.country, 영문) -> ISO3 코드
COUNTRY_ISO_MAP = {
    "united states": "USA", "usa": "USA", "united states of america": "USA",
    "china": "CHN", "japan": "JPN", "vietnam": "VNM",
    "germany": "DEU", "france": "FRA", "united kingdom": "GBR", "uk": "GBR",
    "mexico": "MEX", "australia": "AUS", "india": "IND", "brazil": "BRA",
    "saudi arabia": "SAU", "canada": "CAN", "italy": "ITA", "spain": "ESP",
    "netherlands": "NLD", "united arab emirates": "ARE", "uae": "ARE",
    "thailand": "THA", "indonesia": "IDN", "singapore": "SGP",
    "malaysia": "MYS", "philippines": "PHL", "south korea": "KOR",
    "poland": "POL", "morocco": "MAR", "turkey": "TUR", "russia": "RUS",
    "south africa": "ZAF", "egypt": "EGY", "new zealand": "NZL",
    "hong kong": "HKG", "taiwan": "TWN", "qatar": "QAT", "kuwait": "KWT",
    "belgium": "BEL", "switzerland": "CHE", "sweden": "SWE",
    "austria": "AUT", "portugal": "PRT", "czech republic": "CZE",
    "greece": "GRC", "denmark": "DNK", "norway": "NOR", "finland": "FIN",
    "chile": "CHL", "argentina": "ARG", "colombia": "COL", "peru": "PER",
}

# 국가별 수출 주의사항 카드 (필수/정보/주의)
REGULATION_NOTES = {
    "USA": [
        {
            "level": "필수",
            "title": "FDA 식품 시설 등록",
            "desc": "미국 수출 전 FDA 시설 등록 필수. 2년마다 갱신.",
            "ref": "FDA 21 CFR 1.225",
        },
        {
            "level": "필수",
            "title": "FSMA 준수 (식품안전현대화법)",
            "desc": "공급망 위해요소 관리 계획(HARPC) 수립 의무.",
            "ref": "FSMA 2011",
        },
        {
            "level": "정보",
            "title": "KORUS FTA 무관세 혜택",
            "desc": "한-미 FTA로 대부분 식품류 무관세. 원산지 증명 필수.",
            "ref": "KORUS FTA Schedule",
        },
    ],
    "CHN": [
        {
            "level": "필수",
            "title": "중국 해관 수출입 식품 등록(CIFER)",
            "desc": "해외 식품 생산기업 등록 필수. 미등록 시 통관 불가.",
            "ref": "GACC 총局令 248호",
        },
        {
            "level": "필수",
            "title": "중문 라벨 사전 심사",
            "desc": "중문 라벨·성분표 표기 규정 준수 필요.",
            "ref": "중국 식품안전국가표준 GB 7718",
        },
        {
            "level": "정보",
            "title": "한-중 FTA 관세 인하",
            "desc": "품목별 단계적 관세 인하 적용 중. 원산지 증명서 필요.",
            "ref": "한-중 FTA",
        },
    ],
    "JPN": [
        {
            "level": "필수",
            "title": "식품위생법 수입 신고",
            "desc": "일본 후생노동성 식품 수입 신고 및 검역 절차 필요.",
            "ref": "일본 식품위생법",
        },
        {
            "level": "정보",
            "title": "RCEP 관세 혜택",
            "desc": "RCEP 협정 적용 시 단계적 관세 인하.",
            "ref": "RCEP 협정문",
        },
    ],
}

DEFAULT_REGULATION_NOTES = [
    {
        "level": "필수",
        "title": "현지 식품 수입 규정 확인",
        "desc": "수입국 식품 관련 인증·통관 요건은 국가별로 상이합니다. KOTRA/현지 대사관 확인 권장.",
        "ref": "국가별 상이",
    },
    {
        "level": "정보",
        "title": "원산지 증명서(C/O) 준비",
        "desc": "FTA 체결국의 경우 원산지 증명서로 관세 혜택을 받을 수 있습니다.",
        "ref": "관세청",
    },
]

# 필요 인증 (국가별, 식품 여부에 따라)
CERT_RULES = {
    "USA": ["FDA", "HACCP"],
    "CHN": ["CIFER", "HACCP"],
    "JPN": ["HACCP"],
    "DEU": ["HACCP", "EU 식품등록"],
    "FRA": ["HACCP", "EU 식품등록"],
}
DEFAULT_CERTS_FOOD = ["HACCP"]
DEFAULT_CERTS_NONFOOD = []


def resolve_country_iso(country_name):
    if not country_name:
        return None

    key = country_name.strip().lower()
    # 흔한 약칭/표기 차이는 먼저 직접 매핑 (pycountry가 못 잡는 것들: USA, UK 등)
    if key in COUNTRY_ISO_MAP:
        return COUNTRY_ISO_MAP[key]

    if pycountry is not None:
        try:
            country = pycountry.countries.get(name=country_name.strip())
            if country:
                return country.alpha_3
            matches = pycountry.countries.search_fuzzy(country_name.strip())
            if matches:
                return matches[0].alpha_3
        except LookupError:
            pass

    return None


def get_tariff_regimes(hs_code, country_iso):
    """HS코드+국가별 실제 협정 관세율 목록. [{regime, tariff_ave, display}, ...].
    app/services/tariff_lookup.py가 농림축산식품부 실데이터에서 찾아준다.
    표에 없는 국가/HS코드 조합이면 빈 리스트를 반환한다."""
    return tariff_lookup.get_tariff_regimes(hs_code, country_iso)


def get_best_regime(hs_code, country_iso):
    """가장 유리한(최저) 관세 협정 하나. 데이터가 없으면 None."""
    return tariff_lookup.get_best_regime(hs_code, country_iso)


def _classify_ntm_level(measure):
    text = " ".join([
        measure.legislation_title or "",
        measure.legislation_summary or "",
        measure.measure_title or "",
    ]).lower()
    if any(kw in text for kw in _MANDATORY_KEYWORDS):
        return "필수"
    if any(kw in text for kw in _CAUTION_KEYWORDS):
        return "주의"
    return "정보"


def _relevance_score(measure):
    text = " ".join([
        measure.legislation_title or "",
        measure.legislation_summary or "",
    ]).lower()
    return sum(1 for kw in _FOOD_RELEVANCE_KEYWORDS if kw in text)


def classify_regulation_strictness(notes):
    """이 나라·제품의 수출 주의사항 목록(get_country_regulations 결과, 각
    항목에 level="필수"/"주의"/"정보"가 이미 붙어있음)을 보고 전체적으로
    얼마나 까다로운지 3단계로 요약한다. "필수"(등록/인증/금지 등 강제
    사항)가 많을수록 까다로운 것으로 본다.
    - 데이터가 아예 없으면 None (호출부에서 "정보 없음"으로 표시)
    - 필수 2건 이상 -> "주의요함"
    - 필수 1건 또는 주의 2건 이상 -> "보통"
    - 그 외 -> "낮음"
    """
    if not notes:
        return None
    mandatory_count = sum(1 for n in notes if n["level"] == "필수")
    caution_count = sum(1 for n in notes if n["level"] == "주의")
    if mandatory_count >= 2:
        return "주의요함"
    if mandatory_count >= 1 or caution_count >= 2:
        return "보통"
    return "낮음"


def get_country_regulations(country_iso, hs_code, limit=6):
    """NTM 캐시(NtmMeasure)에서 국가(ISO3) + 이 제품의 hs_code로 조회했던
    규정만 가져와, 식품/농산물 관련도가 높은 순으로 정렬해 상위 N개만
    반환한다.

    반환값으로 세 가지 상태를 구분한다:
    - None: 이 조합으로 아직 한 번도 TRAINS를 조회한 적이 없음
      (호출부에서 정적 예시 데이터로 폴백해야 함)
    - [] (빈 리스트): 조회는 했는데 관련 규정이 진짜 0건이었음
      (trains_client.NO_MATCH_MARKER 마커 행으로 구분 - 폴백하면 안 되고
      "규정 없음"을 그대로 보여줘야 함)
    - [...]: 실제 규정 목록
    """
    if not country_iso or not hs_code:
        return None

    measures = (
        NtmMeasure.query.filter(NtmMeasure.reporter == country_iso, NtmMeasure.product == hs_code)
        .order_by(NtmMeasure.fetched_at.desc())
        .all()
    )
    if not measures:
        return None

    if len(measures) == 1 and measures[0].measure_title == trains_client.NO_MATCH_MARKER:
        return []

    measures.sort(key=_relevance_score, reverse=True)

    notes = []
    for m in measures[:limit]:
        notes.append({
            "level": _classify_ntm_level(m),
            "title": m.legislation_title or m.measure_title or "비관세 조치",
            "desc": m.legislation_summary or m.measure_summary or "",
            "ref": m.implementation_authority or m.data_source or "UNCTAD TRAINS",
            "web_link": m.web_link,
        })
    return notes


def get_regulation_notes(country_iso, ntm_notes=None):
    """TRAINS 캐시에서 가져온 실데이터(ntm_notes)가 있으면 그걸 우선 쓰고,
    없으면 정적 기본 예시(REGULATION_NOTES/DEFAULT_REGULATION_NOTES)로 폴백."""
    if ntm_notes:
        return ntm_notes
    return REGULATION_NOTES.get(country_iso, DEFAULT_REGULATION_NOTES)


def get_required_certs(country_iso, food_yn):
    if country_iso in CERT_RULES:
        return CERT_RULES[country_iso]
    return DEFAULT_CERTS_FOOD if food_yn else DEFAULT_CERTS_NONFOOD


def build_hscode_context(expo, products):
    """detail.html의 HS코드 탭에 필요한 데이터 전부를 만들어서 반환.
    관세율은 제품별 HS코드 + 수출국으로 실데이터 표에서 조회한다 (국가 하나에
    고정된 값이 아니라 제품마다 다를 수 있음 - 예전엔 국가만 보고 모든 제품에
    같은 값을 보여주는 버그가 있었다)."""
    country_iso = resolve_country_iso(expo.country)
    has_country_data = tariff_lookup.has_country_data(country_iso) if country_iso else False

    product_rows = []
    for product in products:
        regimes = get_tariff_regimes(product.hs_code, country_iso) if country_iso else []
        best = None
        numeric_regimes = [r for r in regimes if r["tariff_ave"] is not None]
        if numeric_regimes:
            best = min(numeric_regimes, key=lambda r: r["tariff_ave"])
        for r in regimes:
            r["is_best"] = (r is best) if best else False
        has_range = any(r.get("is_range") for r in regimes)
        subitems = (
            tariff_lookup.get_subitem_breakdown(product.hs_code, country_iso)
            if (country_iso and has_range) else []
        )
        # 이 제품의 hs_code로 캐시된 규정만 가져온다 (제품마다 HS코드가 다르므로
        # 국가 전체가 아니라 제품별로 따로 조회/표시함). None=아직 조회 안 함,
        # []=조회했는데 진짜 0건, [...]=실제 규정 목록 - 세 상태를 구분해야
        # "아직 안 눌러봄"과 "눌러봤는데 없음"을 다르게 보여줄 수 있다.
        product_regulations = get_country_regulations(country_iso, product.hs_code)
        is_synced = product_regulations is not None
        no_match_after_sync = is_synced and not product_regulations
        regulation_notes = product_regulations if is_synced else get_regulation_notes(country_iso, None)

        product_rows.append({
            "product": product,
            "regimes": regimes,
            "best_regime": best,
            "has_data": bool(regimes),
            "has_range": has_range,
            "subitems": subitems,
            "certs": get_required_certs(country_iso, expo.food_yn),
            "regulation_notes": regulation_notes,
            "regulation_notes_is_live": is_synced,
            "regulation_no_match": no_match_after_sync,
            # 실데이터일 때만 계산 (정적 예시 데이터 기준으로는 나라별 까다로움을
            # 판단할 수 없으므로)
            "regulation_strictness": classify_regulation_strictness(product_regulations) if product_regulations else None,
        })

    # 등록된 제품들 전체에서 가장 유리한 관세 조합 하나 추천 (데이터 있는 것만 대상)
    overall_best = None
    rows_with_best = [r for r in product_rows if r["best_regime"] is not None]
    if rows_with_best:
        overall_best = min(rows_with_best, key=lambda r: r["best_regime"]["tariff_ave"])

    return {
        "country_iso": country_iso,
        "has_country_data": has_country_data,
        "product_rows": product_rows,
        "overall_best": overall_best,
    }

"""
HS코드 & 수출 주의사항 탭용 서비스.

관세율: scripts/market/tariff_advisor.py 의 협정별 관세율 프로필(MFN/FTA/RCEP)
로직을 그대로 가져왔다 (정적 프로필, 주요국 외에는 추정치).

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

# 국가별 협정 관세율 프로필 (tariff_advisor.py 그대로)
TARIFF_PROFILES = {
    "CHN": {"fta_name": "한-중 FTA", "mfn": 12.0, "fta": 0.0, "rcep": 5.0},
    "USA": {"fta_name": "한-미 FTA (KORUS)", "mfn": 6.4, "fta": 0.0, "rcep": 6.4},
    "VNM": {"fta_name": "한-베트남 FTA / RCEP", "mfn": 15.0, "fta": 0.0, "rcep": 5.0},
    "JPN": {"fta_name": "RCEP / 양자 간 협정", "mfn": 8.0, "fta": 2.5, "rcep": 3.0},
    "BRA": {"fta_name": "일반관세 (MERCOSUR 연계)", "mfn": 35.0, "fta": 32.0, "rcep": 35.0},
    "MEX": {"fta_name": "일반관세 (FTA 미체결)", "mfn": 20.0, "fta": 20.0, "rcep": 20.0},
    "DEU": {"fta_name": "한-EU FTA", "mfn": 14.2, "fta": 0.0, "rcep": 14.2},
    "FRA": {"fta_name": "한-EU FTA", "mfn": 14.2, "fta": 0.0, "rcep": 14.2},
    "AUS": {"fta_name": "한-호주 FTA", "mfn": 10.0, "fta": 0.0, "rcep": 4.0},
    "SAU": {"fta_name": "한-사우디 일반 협정", "mfn": 15.0, "fta": 5.0, "rcep": 10.0},
}

DEFAULT_PROFILE = {"fta_name": "일반 협정 (추정치)", "mfn": 15.0, "fta": 5.0, "rcep": 10.0}

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


def get_tariff_regimes(country_iso):
    """국가별 협정 관세율 목록. [{regime, tariff_ave}, ...]"""
    profile = TARIFF_PROFILES.get(country_iso, DEFAULT_PROFILE)
    return [
        {"regime": "MFN (기본세율)", "tariff_ave": profile["mfn"]},
        {"regime": profile["fta_name"], "tariff_ave": profile["fta"]},
        {"regime": "RCEP (역내)", "tariff_ave": profile["rcep"]},
    ]


def get_best_regime(country_iso):
    """가장 유리한(최저) 관세 협정 하나."""
    regimes = get_tariff_regimes(country_iso)
    return min(regimes, key=lambda r: r["tariff_ave"])


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


def get_country_regulations(country_iso, limit=6):
    """NTM 캐시(NtmMeasure)에서 국가(ISO3) 전체 규정을 가져와, 식품/농산물
    관련도가 높은 순으로 정렬해 상위 N개만 반환한다. TRAINS Online이 HS코드
    단위로는 필터링을 안 해주기 때문에(국가 전체 목록을 항상 반환) 여기서
    직접 관련도를 매긴다. 캐시가 비어있으면 빈 리스트(호출부에서 정적 기본값 폴백)."""
    if not country_iso:
        return []

    measures = (
        NtmMeasure.query.filter(NtmMeasure.reporter == country_iso)
        .order_by(NtmMeasure.fetched_at.desc())
        .all()
    )
    if not measures:
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
    """detail.html의 HS코드 탭에 필요한 데이터 전부를 만들어서 반환."""
    country_iso = resolve_country_iso(expo.country)
    is_estimated = country_iso not in TARIFF_PROFILES

    product_rows = []
    for product in products:
        regimes = get_tariff_regimes(country_iso)
        best = min(regimes, key=lambda r: r["tariff_ave"])
        for r in regimes:
            r["is_best"] = r is best
        product_rows.append({
            "product": product,
            "regimes": regimes,
            "best_regime": best,
            "certs": get_required_certs(country_iso, expo.food_yn),
        })

    # 등록된 제품들 전체에서 가장 유리한 관세 조합 하나 추천
    overall_best = None
    if product_rows:
        overall_best = min(product_rows, key=lambda r: r["best_regime"]["tariff_ave"])

    # 국가 전체 규정 중 식품/농산물 관련도 높은 순 상위 N개 (TRAINS는 HS코드로
    # 필터링이 안 되고 국가 전체 목록을 반환하므로, 여기서 관련도를 매겨 추림)
    country_regulations = get_country_regulations(country_iso)

    return {
        "country_iso": country_iso,
        "is_estimated": is_estimated,
        "product_rows": product_rows,
        "overall_best": overall_best,
        "regulation_notes": get_regulation_notes(country_iso, country_regulations),
        "regulation_notes_is_live": bool(country_regulations),
    }

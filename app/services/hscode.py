"""
HS코드 & 수출 주의사항 탭용 서비스.

관세율: scripts/market/tariff_advisor.py 의 협정별 관세율 프로필(MFN/FTA/RCEP)
로직을 그대로 가져왔다 (정적 프로필, 주요국 외에는 추정치).

비관세장벽(NTM): macmap.org 내부 API(scripts/market/macmap_api.py 로직,
app/services/macmap_client.py로 이식)에서 가져온 실데이터를 쓴다. 다만 macmap은
페이지 로드마다 직접 부르지 않고, scripts/market/sync_ntm_cache.py가 배치로
NtmMeasure 테이블에 채워둔 캐시를 읽기만 한다. 캐시가 아직 없는 국가/HS코드는
DEFAULT_REGULATION_NOTES로 폴백한다.
"""

from app.models import NtmMeasure

# ISO3 -> UN M49 숫자코드 (macmap reporter 파라미터에 사용)
ISO3_TO_M49 = {
    "USA": "842", "CHN": "156", "JPN": "392", "VNM": "704", "DEU": "276",
    "FRA": "250", "GBR": "826", "MEX": "484", "AUS": "36", "IND": "356",
    "BRA": "76", "SAU": "682", "CAN": "124", "ITA": "380", "ESP": "724",
    "NLD": "528", "ARE": "784", "THA": "764", "IDN": "360", "SGP": "702",
    "MYS": "458", "PHL": "608", "KOR": "410", "POL": "616", "MAR": "504",
    "TUR": "792", "RUS": "643", "ZAF": "710", "EGY": "818", "NZL": "554",
    "HKG": "344", "TWN": "158", "QAT": "634", "KWT": "414", "BEL": "56",
    "CHE": "756", "SWE": "752", "AUT": "40", "PRT": "620", "CZE": "203",
    "GRC": "300", "DNK": "208", "NOR": "578", "FIN": "246", "CHL": "152",
    "ARG": "32", "COL": "170", "PER": "604",
}

# macmap MeasureSection/legislation 텍스트로 필수/정보/주의 등급을 대략 나누는 키워드
_MANDATORY_KEYWORDS = [
    "registration", "mandatory", "requirement", "authorization", "license",
    "certificat", "must", "prohibit", "ban",
]
_CAUTION_KEYWORDS = ["labelling", "labeling", "tbt", "sps", "inspection", "testing", "residue"]

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
    return COUNTRY_ISO_MAP.get(country_name.strip().lower())


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


def get_ntm_notes_for_product(country_iso, hs_code, limit=5):
    """macmap NTM 캐시(NtmMeasure)에서 국가+HS코드에 맞는 비관세장벽 항목을 가져온다.
    캐시가 비어있으면 빈 리스트를 반환 (호출부에서 정적 기본값으로 폴백)."""
    m49 = ISO3_TO_M49.get(country_iso)
    if not m49 or not hs_code:
        return []

    normalized_hs = hs_code.replace(".", "")
    hs6 = normalized_hs[:6]

    measures = (
        NtmMeasure.query.filter(
            NtmMeasure.reporter == m49,
            NtmMeasure.product.like(f"{hs6}%"),
        )
        .order_by(NtmMeasure.fetched_at.desc())
        .limit(limit)
        .all()
    )

    notes = []
    for m in measures:
        notes.append({
            "level": _classify_ntm_level(m),
            "title": m.legislation_title or m.measure_title or "비관세 조치",
            "desc": m.legislation_summary or m.measure_summary or "",
            "ref": m.implementation_authority or m.data_source or "macmap.org",
            "web_link": m.web_link,
        })
    return notes


def get_regulation_notes(country_iso, ntm_notes=None):
    """macmap 캐시에서 가져온 실데이터(ntm_notes)가 있으면 그걸 우선 쓰고,
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
    all_ntm_notes = []
    seen_titles = set()
    for product in products:
        regimes = get_tariff_regimes(country_iso)
        best = min(regimes, key=lambda r: r["tariff_ave"])
        for r in regimes:
            r["is_best"] = r is best
        ntm_notes = get_ntm_notes_for_product(country_iso, product.hs_code)
        product_rows.append({
            "product": product,
            "regimes": regimes,
            "best_regime": best,
            "certs": get_required_certs(country_iso, expo.food_yn),
            "ntm_notes": ntm_notes,
        })
        for note in ntm_notes:
            if note["title"] not in seen_titles:
                seen_titles.add(note["title"])
                all_ntm_notes.append(note)

    # 등록된 제품들 전체에서 가장 유리한 관세 조합 하나 추천
    overall_best = None
    if product_rows:
        overall_best = min(product_rows, key=lambda r: r["best_regime"]["tariff_ave"])

    return {
        "country_iso": country_iso,
        "is_estimated": is_estimated,
        "product_rows": product_rows,
        "overall_best": overall_best,
        "regulation_notes": get_regulation_notes(country_iso, all_ntm_notes),
        "regulation_notes_is_live": bool(all_ntm_notes),
    }

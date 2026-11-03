"""싱가포르(SGP) x 스위트 비스킷(HS 1905.31) 전용 공식 규제 지식팩.

적용 범위를 이 조합 하나로 엄격히 제한한다 — 같은 "가공식품"이라도 수산물/
육류(각각 SFA 별도 체계, 할랄 등)나 음료/주류는 완전히 다른 요건 집합이라
여기 끼워 넣으면 틀린 안내가 된다. 다른 품목으로 넓히려면 그 품목만의
지식팩을 별도로 또 조사해서 새 파일로 추가해야 한다 (이 파일을 수정해서
조건만 느슨하게 풀면 안 됨).

각 항목은 아래 필드를 전부 채운다:
    - official_source_url : 실제로 열어서 확인한 공식 URL
    - applies_when / exceptions : 이 조합(SGP, 스위트 비스킷, 상업 수입)에
      한정해 판단한 조건. 다른 조합에는 그대로 재사용하지 않는다.
    - checked_at : 이 내용을 실제로 조사·대조한 날짜
    - verification_status : "reviewed"는 공식 출처를 열어 문구를 직접
      대조한 항목만. 출처는 찾았지만 조건이나 예외까지 명확히 확인하지
      못했으면 "pending_review"로 남겨 과장하지 않는다.

주의: 이 내용은 2026-11 기준 조사 결과이며 법령·행정 기준은 수시로 바뀔 수
있다. 실제 수출 전에는 반드시 공식 사이트에서 최신 내용을 재확인해야 한다.
"""

COUNTRY = "SGP"
HS_CODE_PREFIXES = ("190531",)  # 190531 = 스위트 비스킷(코코아 포함/미포함 모두)
PRODUCT_CATEGORY = "sweet_biscuit"

REQUIREMENTS = [
    {
        "country": "SGP",
        "product_category": PRODUCT_CATEGORY,
        "requirement_id": "sfa_importer_registration",
        "title": "SFA 가공식품 수입업자 등록",
        "applies_when": {"commercial_import": True},
        "exceptions": "개인 휴대 반입 등 비상업적 반입에는 적용 안 됨",
        "requirement_summary": (
            "가공식품(육류·수산물·생과일채소 제외)을 상업적으로 수입하려면 "
            "싱가포르 식품청(SFA)에 수입업자로 사전 등록해야 한다. 등록 "
            "없이는 통관 자체가 불가하다."
        ),
        "official_source_url": "https://www.gobusiness.gov.sg/browse-all-licences/singapore-food-agency-(sfa)/registration-to-import-processed-food-products-and-food-appliances",
        "checked_at": "2026-11-03",
        "verification_status": "reviewed",
    },
    {
        "country": "SGP",
        "product_category": PRODUCT_CATEGORY,
        "requirement_id": "tradenet_import_permit",
        "title": "TradeNet 수입허가(Cargo Clearance Permit)",
        "applies_when": {"commercial_import": True},
        "exceptions": "없음 — 상업 수입이면 매 건(consignment)마다 필요",
        "requirement_summary": (
            "상업적으로 수입되는 모든 식품 건(consignment)마다 싱가포르 "
            "관세청 TradeNet 시스템으로 수입허가를 신청해야 한다. 신청 시 "
            "SFA 수입업자 등록번호가 필요하다."
        ),
        "official_source_url": "https://www.customs.gov.sg/businesses/national-single-window/tradenet/competent-authorities-requirements/sfa-processed-food",
        "checked_at": "2026-11-03",
        "verification_status": "reviewed",
    },
    {
        "country": "SGP",
        "product_category": PRODUCT_CATEGORY,
        "requirement_id": "food_regulations_labelling",
        "title": "포장식품 표시 기준(Food Regulations 일반 라벨링)",
        "applies_when": {"commercial_import": True, "packaged": True},
        "exceptions": "영양강조표시(저당·고단백 등)를 전혀 안 쓰면 영양정보패널은 의무 아님",
        "requirement_summary": (
            "싱가포르에서 판매되는 모든 포장식품은 Food Regulations의 "
            "일반 라벨링 기준(제품명, 원재료, 알레르기 성분, 제조·유통기한, "
            "원산지 등)을 따라야 한다. 영양강조표시를 하는 경우에만 별도 "
            "영양정보패널 표기가 추가로 요구된다."
        ),
        "official_source_url": "https://www.sfa.gov.sg/food-information/labelling-packaging-information/labelling-guidelines-for-food-importers-manufacturers",
        "checked_at": "2026-11-03",
        "verification_status": "reviewed",
    },
    {
        "country": "SGP",
        "product_category": PRODUCT_CATEGORY,
        "requirement_id": "food_additive_ingredient_standard",
        "title": "원재료·식품첨가물 기준",
        "applies_when": {"commercial_import": True},
        "exceptions": "식품첨가물을 쓰지 않는 단순 배합 제품은 해당 조항이 사실상 적용 안 될 수 있음 — 배합표 확인 필요",
        "requirement_summary": (
            "사용된 식품첨가물·원재료가 싱가포르 Food Regulations에서 "
            "허용하는 기준(허용 물질·허용량)을 넘지 않아야 한다. 구체적 "
            "적용 여부는 실제 배합표가 있어야 판단 가능해 일괄 '필수/비해당' "
            "으로 단정하지 않는다."
        ),
        "official_source_url": "https://www.sfa.gov.sg/food-information/labelling-packaging-information",
        "checked_at": "2026-11-03",
        "verification_status": "pending_review",
    },
    {
        "country": "SGP",
        "product_category": PRODUCT_CATEGORY,
        "requirement_id": "haccp_certification",
        "title": "HACCP 인증",
        # 일반 수입만으로는 법적 의무 근거가 없고, 바이어/유통사가 거래
        # 조건으로 요구하는지에 달려 있다. 이 값은 기본 프로필에 없는
        # 키라 matcher가 "모르는 조건"으로 보고 항상 '추가 확인 필요'로
        # 남긴다 (비스킷이라고 일괄 '비해당'으로 단정하지도 않음).
        "applies_when": {"buyer_requires_haccp": True},
        "exceptions": (
            "일반 포장 비스킷을 '수입'만 하는 경우 SFA 공식 자료에서 "
            "HACCP을 일괄 의무로 명시한 근거를 찾지 못했다. HACCP/ISO 22000은 "
            "주로 '제조업체' 인허가나 특정 거래처(대형 유통사·바이어)가 "
            "요구하는 경우에 필요해진다."
        ),
        "requirement_summary": (
            "싱가포르 SFA가 일반 가공식품 '수입업자'에게 HACCP을 법적으로 "
            "일괄 요구한다는 공식 근거는 확인되지 않았다. 바이어·유통사가 "
            "거래 조건으로 요구할 수 있어 '조건부 확인 필요' 항목으로만 "
            "남긴다."
        ),
        "official_source_url": "https://www.sfa.gov.sg/food-manufacturers/overview-of-food-establishments-in-singapore",
        "checked_at": "2026-11-03",
        "verification_status": "pending_review",
    },
]


def matches_scope(country_iso, hs_code):
    """이 지식팩이 이 (국가, HS코드) 조합에 적용 가능한지."""
    if country_iso != COUNTRY:
        return False
    if not hs_code:
        return False
    normalized = str(hs_code).replace(".", "").replace(" ", "")
    return normalized.startswith(HS_CODE_PREFIXES)

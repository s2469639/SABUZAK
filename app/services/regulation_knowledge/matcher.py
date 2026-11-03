"""지식팩 항목을 제품 프로필과 대조해 상태(적용 확인/추가 확인 필요/비해당)를
판정한다.

이번 MVP는 싱가포르 x 스위트 비스킷 지식팩 하나뿐이라 복잡한 룰 엔진 없이
applies_when 딕셔너리를 제품 프로필과 단순 비교하는 수준으로 둔다. 지식팩이
늘어나면 그때 가서 더 일반화한다(지금 과하게 일반화하면 검증 안 된 조합까지
같은 코드 경로를 타게 될 위험이 크다).
"""

from app.services.regulation_knowledge import sgp_sweet_biscuits

_PACKS = [sgp_sweet_biscuits]

STATUS_CONFIRMED = "적용 확인"
STATUS_NEEDS_CHECK = "추가 확인 필요"
STATUS_NOT_APPLICABLE = "비해당"

# 상업용 포장 가공식품(비스킷) 수입이라는 이번 시나리오의 기본 제품 프로필.
# applies_when에 없는 키는 평가하지 않는다(모르는 조건을 함부로 단정하지 않음).
DEFAULT_PRODUCT_PROFILE = {
    "commercial_import": True,
    "packaged": True,
    "manufacturer_license_required": False,  # 수입만 하고 싱가포르 현지 제조는 안 함
}


def _evaluate_status(requirement, product_profile):
    """verification_status가 pending_review면 공식 근거가 불충분하다는
    뜻이므로, applies_when이 True로 나와도 '적용 확인'까지는 못 가고
    '추가 확인 필요'로 머무른다 (근거 불충분 상태에서 확정 판정 금지)."""
    applies_when = requirement.get("applies_when") or {}
    is_reviewed = requirement.get("verification_status") == "reviewed"

    matched = True
    known = False
    for key, expected in applies_when.items():
        if key not in product_profile:
            continue
        known = True
        if product_profile[key] != expected:
            matched = False
            break

    if not known:
        return STATUS_NEEDS_CHECK
    if not matched:
        return STATUS_NOT_APPLICABLE
    if is_reviewed:
        return STATUS_CONFIRMED
    return STATUS_NEEDS_CHECK


def get_official_requirements(country_iso, hs_code, product_profile=None):
    """이 (국가, HS코드) 조합에 적용 가능한 지식팩이 있으면, 각 항목에
    상태를 매겨서 반환한다. 해당하는 지식팩이 없으면 None을 반환해
    호출부가 기존 TRAINS 흐름으로 자연스럽게 폴백하게 한다."""
    profile = {**DEFAULT_PRODUCT_PROFILE, **(product_profile or {})}

    for pack in _PACKS:
        if not pack.matches_scope(country_iso, hs_code):
            continue
        results = []
        for req in pack.REQUIREMENTS:
            status = _evaluate_status(req, profile)
            results.append({**req, "status": status})
        return results

    return None

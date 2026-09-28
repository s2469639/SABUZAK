import re

from app.services.openai_client import get_client


def _parse_subject_body(text: str) -> tuple[str, str]:
    match = re.search(r"SUBJECT:\s*(.+?)\nBODY:\s*(.*)", text, re.DOTALL)
    if not match:
        raise ValueError("LLM 응답 형식을 해석할 수 없습니다.")
    return match.group(1).strip(), match.group(2).strip()


def _ask(prompt: str) -> tuple[str, str]:
    response = get_client().chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_subject_body(response.choices[0].message.content)


def _business_context(sender_company: str, product_description: str) -> str:
    company = sender_company.strip() if sender_company else "이 회사"
    if product_description and product_description.strip():
        return f"당신은 '{company}'의 해외영업 담당자입니다. 이 회사는 {product_description.strip()} 을(를) 판매합니다.\n"
    return f"당신은 '{company}'의 해외영업 담당자입니다.\n"


# 사용자가 목적/방향에 아래 키워드를 넣으면, AI 해석에 맡기지 않고 그 단계에 맞는
# 규칙을 프롬프트에 직접 강제로 박아넣는다 (LLM이 알아서 판단하게 두면 톤/지시가
# 흐릿해질 때가 있어서, 명확한 키워드가 있으면 결정적으로 처리).
# 공백 유무·대소문자에 안 흔들리도록 매칭 전에 정규화한다.
_STAGE1_KEYWORDS = ["감사메일", "감사인사", "감사레터", "땡큐레터", "땡큐메일", "thankyou"]
_STAGE2_KEYWORDS = [
    "2차팔로업", "2차메일", "2차이메일", "회신답장", "거래조건", "인코텀즈", "incoterms", "협상조건",
]

_STAGE1_RULES = (
    "- [1차 메일 확정] 이 메일은 1차(당일/직후 발송) 감사 메일입니다. 부스 방문에 대한 "
    "짧고 정중한 감사 인사만 담으세요.\n"
    "- 가격, MOQ, 리드타임, 결제조건, Incoterms(인코텀즈) 등 어떠한 거래 조건도 이 메일에는 "
    "절대 넣지 마세요. 거래 조건 얘기는 다음 메일(2차 팔로업)에서 다룰 내용입니다.\n"
    "- 분량은 3~6문장 정도로 짧게 쓰고, 조만간 카탈로그/견적 등으로 다시 연락드리겠다는 "
    "짧은 언급 정도만 덧붙이세요.\n"
)

_STAGE2_RULES = (
    "- [2차 메일 확정] 이 메일은 2차 팔로업(거래 조건 제시/협상) 메일입니다. 1차 감사 인사는 "
    "이미 보냈다고 가정하고, 감사 인사를 반복하지 말고 곧바로 실질적인 거래 진행 내용으로 "
    "들어가세요.\n"
    "- 아래 거래 조건을 반드시 불릿으로 구체적인 예시 수치와 함께 명시하세요: 단가/가격대, "
    "MOQ, 리드타임, 결제조건, Incoterms(예: FOB Busan, CIF 목적항 등 구체적인 조건 하나를 "
    "명시), 견적 유효기간. 사용자가 실제 수치를 몰라도 되도록 업계 평균 감으로 그럴듯한 "
    "예시 수치를 넣고, 나중에 숫자만 바꿔 쓰면 되게 하세요.\n"
)


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _detect_stage_rules(purpose: str) -> str:
    """목적/방향 문구에 1차·2차를 가리키는 확정 키워드가 있으면 그 단계 규칙을,
    없으면 빈 문자열을 반환한다 (기존의 느슨한 자유 해석 방식으로 넘어감)."""
    normalized = _normalize_for_match(purpose)
    if any(keyword in normalized for keyword in _STAGE2_KEYWORDS):
        return _STAGE2_RULES
    if any(keyword in normalized for keyword in _STAGE1_KEYWORDS):
        return _STAGE1_RULES
    return ""


def revise_email_template(
    instruction: str,
    current_subject: str = "",
    current_body: str = "",
    sender_company: str = "",
    product_description: str = "",
) -> tuple[str, str]:
    has_existing = bool(current_subject or current_body)
    existing_block = (
        f"현재 템플릿:\nSUBJECT: {current_subject}\nBODY:\n{current_body}\n\n" if has_existing else ""
    )

    purpose = instruction.strip() or (
        "박람회에서 만난 바이어들에게 부스 방문 감사와 샘플/카탈로그/견적 후속 논의를 "
        "제안하는 표준 1차 팔로업 이메일 (기본값 - 사용자가 별도 목적을 안 밝혔을 때)"
    )
    prompt = (
        _business_context(sender_company, product_description)
        + "박람회에서 만난 바이어들에게 공통으로 보낼 회사 표준 이메일 템플릿을 "
        f"{'수정' if has_existing else '작성'}하세요. 어느 박람회에서 만났든 이 템플릿 하나를 재사용합니다.\n\n"
        f"{existing_block}"
        f"이 이메일의 목적/방향: {purpose}\n\n"
        "조건:\n"
        "- 위에서 밝힌 목적에 맞는 내용으로 작성하세요 (예: 감사 인사, 샘플/견적 제안, 협상 조건 제시, "
        "단순 리마인드 등 - 목적이 다르면 내용도 완전히 달라져야 합니다. 목적에 없는 내용은 임의로 넣지 마세요)\n"
        + _detect_stage_rules(purpose)
        + (
            "- 위 '현재 템플릿'은 참고용 서식일 뿐입니다. 새 목적/방향이 현재 템플릿과 다른 "
            "종류의 이메일(예: 감사 인사 ↔ 협상/팔로업 ↔ 리마인드)을 요구한다면, 기존 문구를 "
            "재활용하거나 일부만 다듬지 말고 그 목적에 맞게 구조와 분량, 내용을 처음부터 완전히 "
            "새로 작성하세요. 새 목적과 같은 종류일 때만 기존 표현을 유지·다듬으세요.\n"
            if has_existing else ""
        )
        + "- 목적이 거래 조건(가격, MOQ, 리드타임, 결제조건, 유효기간, 인증 등)을 제시/협상하는 것이라면, "
        "'please let me know your requirements', 'feel free to reach out' 같은 애매하고 상투적인 "
        "표현으로 뭉개지 말고, 실제 그 업계에서 흔히 쓰이는 구체적인 조건을 항목별로(불릿) 직접 "
        "제시하세요. 사용자가 실제 수치를 몰라도 되도록, 업계 평균 감으로 그럴듯한 예시 수치를 넣어서 "
        "쓰고, 사용자가 나중에 숫자만 바꿔 쓰면 되게 하세요 (예: \"- MOQ: 1 pallet\", \"- Payment: 30% "
        "deposit, 70% before shipment\" 처럼 실제 협상 이메일 형식)\n"
        "- 박람회명 자리에는 반드시 {{exhibition}}, 바이어 이름 자리에는 반드시 {{name}}, "
        "회사명 자리에는 반드시 {{company}} 를 그대로 남겨두세요 (실제 값은 발송 시 자동 치환됩니다)\n"
        "- 영어로 작성 (국제 박람회 바이어 공통 발송이므로)\n"
        "- 톤: 위 목적/방향에 캐주얼하게, 격식없이, 친근하게, 단호하게 등 특정 톤에 대한 "
        "언급이 있다면 그 톤을 반드시 우선 반영하세요. 특별한 톤 언급이 없을 때만 기본값으로 "
        "정중하고 간결한 비즈니스 이메일 톤으로 작성하세요\n"
        "- 일반 텍스트 이메일이라 마크다운이 화면에 그대로 굵은 글씨로 안 보입니다. "
        "**굵게** 같은 마크다운 문법을 쓰지 말고 일반 텍스트로만 작성하세요 (불릿은 \"- \"만 사용)\n"
        "- 본문 맨 끝에는 발신자 서명을 넣되, 이름 자리에 {{sender_name}}, 직급 자리에 "
        "{{sender_position}}, 회사명 자리에 {{sender_company}} 를 그대로 남겨두세요\n"
        "- 서명 맨 마지막 줄에 발송 날짜를 나타내는 {{date}} 를 그대로 넣으세요 (본문 다른 곳에는 넣지 마세요)\n"
        "- 아래 형식을 반드시 지켜서 출력 (다른 설명은 붙이지 말 것)\n\n"
        "SUBJECT: <제목>\n"
        "BODY:\n"
        "<본문>\n"
    )
    return _ask(prompt)


def revise_individual_email(
    instruction: str,
    current_subject: str,
    current_body: str,
    sender_company: str = "",
    product_description: str = "",
) -> tuple[str, str]:
    """특정 바이어 한 명에게 보낼, 이미 이름/회사 등이 채워진 이메일 한 통을 수정한다."""
    prompt = (
        _business_context(sender_company, product_description)
        + "아래는 특정 바이어에게 보낼 팔로업 이메일 초안입니다. 사용자의 요청에 맞게 수정하세요.\n\n"
        f"현재 이메일:\nSUBJECT: {current_subject}\nBODY:\n{current_body}\n\n"
        f"사용자가 요청한 수정 방향: {instruction or '(특별한 요청 없음, 자연스럽게 다듬어주세요)'}\n\n"
        "조건:\n"
        "- 이미 채워진 실제 이름·회사명·날짜 등은 그대로 유지하세요 (자리표시자로 바꾸지 마세요)\n"
        + _detect_stage_rules(instruction)
        + "- 영어로 작성\n"
        "- 일반 텍스트 이메일이라 **굵게** 같은 마크다운 문법을 쓰지 마세요 (불릿은 \"- \"만 사용)\n"
        "- 아래 형식을 반드시 지켜서 출력 (다른 설명은 붙이지 말 것)\n\n"
        "SUBJECT: <제목>\n"
        "BODY:\n"
        "<본문>\n"
    )
    return _ask(prompt)

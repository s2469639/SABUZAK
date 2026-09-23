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

    prompt = (
        _business_context(sender_company, product_description)
        + "박람회에서 만난 바이어들에게 공통으로 보낼 회사 표준 사후 팔로업 이메일 템플릿을 "
        f"{'수정' if has_existing else '작성'}하세요. 어느 박람회에서 만났든 이 템플릿 하나를 재사용합니다.\n\n"
        f"{existing_block}"
        f"사용자가 요청한 수정 방향: {instruction or '(특별한 요청 없음, 기본 톤으로 작성)'}\n\n"
        "조건:\n"
        "- 박람회명 자리에는 반드시 {{exhibition}}, 바이어 이름 자리에는 반드시 {{name}}, "
        "회사명 자리에는 반드시 {{company}} 를 그대로 남겨두세요 (실제 값은 발송 시 자동 치환됩니다)\n"
        "- 영어로 작성 (국제 박람회 바이어 공통 발송이므로)\n"
        "- 정중하고 간결한 비즈니스 이메일 톤 (사용자의 수정 방향이 있다면 그에 맞게 조정)\n"
        "- 부스 방문에 대한 감사 인사와 샘플/카탈로그/견적 후속 논의 제안을 포함\n"
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
        "- 영어로 작성\n"
        "- 아래 형식을 반드시 지켜서 출력 (다른 설명은 붙이지 말 것)\n\n"
        "SUBJECT: <제목>\n"
        "BODY:\n"
        "<본문>\n"
    )
    return _ask(prompt)

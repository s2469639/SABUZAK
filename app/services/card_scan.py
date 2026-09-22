import base64
import json
import re

from app.services.openai_client import get_client


def scan_business_card(image_bytes: bytes, mimetype: str) -> dict:
    encoded = base64.b64encode(image_bytes).decode()
    data_url = f"data:{mimetype};base64,{encoded}"

    prompt = (
        "다음 명함 이미지에서 정보를 추출해서 JSON 객체 하나로만 응답하세요. 다른 설명은 붙이지 마세요.\n"
        '형식: {"name": "", "company": "", "email": "", "position": "", "phone": "", "address": ""}\n'
        "- name: 사람 이름\n"
        "- company: 회사명\n"
        "- email: 이메일 주소\n"
        "- position: 소속 팀/부서 + 직급 (예: 해외영업팀 대리)\n"
        "- phone: 전화번호 (여러 개면 세미콜론으로 구분)\n"
        "- address: 회사 주소\n"
        "값을 찾을 수 없으면 빈 문자열로 두세요."
    )

    response = get_client().chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    )
    text = response.choices[0].message.content or ""

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("명함 인식 결과를 해석할 수 없습니다.")

    data = json.loads(match.group(0))
    return {
        "name": (data.get("name") or "").strip(),
        "company": (data.get("company") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "position": (data.get("position") or "").strip(),
        "phone": (data.get("phone") or "").strip(),
        "address": (data.get("address") or "").strip(),
    }

"""플로팅 챗봇 위젯의 백엔드. OpenAI(gpt-4o-mini, 가장 저렴한 모델)에게
사이트 사용 가이드를 답해주게 하고, "이 제품 HS코드가 뭐야?" 같은 질문은
function calling으로 hs0code_master(관세청 HS코드 마스터)를 직접 검색해서
답하게 한다 (LLM이 코드를 지어내지 않도록)."""

import json

from flask import Blueprint, jsonify, request
from flask_login import login_required

from app.models import HsCodeMaster
from app.routes.mypage import _hs_master_query_available
from app.services.openai_client import get_client

bp = Blueprint("chatbot", __name__, url_prefix="/chatbot")

MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """당신은 식품 수출 박람회 준비 플랫폼 "FairMate"의 업무 지원 챗봇입니다.
실무자를 대상으로 정중하고 간결한 존댓말로, 핵심만 답하세요. 불필요한 수사나 이모지는 쓰지 않습니다.

아래 [FairMate 사용 가이드]는 이 챗봇이 답변에 실제로 사용할 지식입니다. 사용자가 "웹사이트/사이트
이용 방법", "어떻게 써야 하는지", 특정 기능(대시보드, 박람회 상세, 마이페이지, 부스 컨셉, 바이어 관리 등)의
위치나 사용법을 물으면, 아래 가이드 내용을 근거로 반드시 답변하세요. 이런 질문을 범위 밖으로 판단해
거절하면 안 됩니다.

[FairMate 사용 가이드]
- 대시보드: 대륙/국가별 박람회 목록을 보고 필터링(식품 여부, 규모, 참관대상, 날짜, 검색어)할 수 있습니다.
- 박람회 상세 페이지: "박람회 개요", "시장 개요"(UN Comtrade/관세청 교역통계), "트렌드 조사"(구글 트렌드·리테일 분석),
  "HS코드 & 수출 주의사항"(관세율, 비관세장벽) 탭으로 구성됩니다.
- 내 제품 관리(마이페이지): 제품을 등록하면 HS코드를 검색해 붙일 수 있고, "유망시장 조사"로 국가별 매트릭스 분석을 볼 수 있습니다.
- 부스 컨셉 기획: 박람회 상세 페이지에서 "부스 컨셉 기획 →" 버튼으로 AI가 부스 테마·이벤트·3D 이미지 프롬프트를 생성해줍니다.
- 바이어 관리: 명함을 스캔해 바이어를 등록하고, 메일 템플릿으로 일괄 발송할 수 있습니다.

예시:
사용자: "웹사이트 이용 방법을 안내해주세요"
챗봇: "FairMate는 대시보드에서 박람회를 조건별로 찾아보고, 박람회 상세 페이지에서 시장·트렌드·HS코드
정보를 확인한 뒤, 마이페이지에서 제품을 등록해 유망시장 조사와 부스 컨셉 기획까지 진행하실 수 있습니다.
바이어 관리 메뉴에서는 명함 스캔과 메일 발송도 가능합니다."

[HS코드 검색]
사용자가 특정 제품의 HS코드를 물으면 lookup_hscode 함수를 반드시 호출해서 실제 관세청 데이터로 답하세요.
직접 코드를 추측해서 말하지 마세요. 검색 결과가 없으면 "정확한 품목명을 알려주시면 다시 확인해드리겠습니다."처럼
정중하게 안내하세요.

[답변 범위]
FairMate 서비스나 이 화면에 관련된 질문이면 폭넓게 답하세요. 위 가이드에 정확히 나온 내용이 아니어도,
박람회 준비·수출 실무·이 웹사이트에 있는 기능/데이터와 관련이 있다고 판단되면 아는 범위에서 성실하게
답하거나 합리적으로 추론해서 답하세요. 모르면 모른다고 솔직히 말하되, 무리해서 거절부터 하지 마세요.

FairMate·이 웹사이트와 정말로 무관한 질문(일반 상식, 날씨, 다른 회사 서비스, 이 서비스와 무관한 코딩 질문 등)
에만 "해당 문의는 이 챗봇이 도와드릴 수 있는 범위를 벗어납니다."라고 짧게 안내하세요. 애매하면 거절하지 말고
답변을 시도하세요.

답변은 3~4문장 이내로 간결하게, 실무 보고체로 작성하세요."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_hscode",
            "description": "제품명(한글)으로 관세청 HS코드 마스터 데이터를 검색한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색할 제품명 (예: 유과, 약과, 김)"},
                },
                "required": ["query"],
            },
        },
    }
]


def _lookup_hscode(query):
    if not query or not _hs_master_query_available():
        return []
    like = f"%{query.strip()}%"
    rows = (
        HsCodeMaster.query.filter(
            (HsCodeMaster.name_ko.ilike(like)) | (HsCodeMaster.hsk_name.ilike(like))
        )
        .limit(8)
        .all()
    )
    return [{"hscode": r.hscode, "name_ko": r.name_ko or r.hsk_name} for r in rows]


@bp.route("/message", methods=["POST"])
@login_required
def message():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    history = data.get("history") or []  # [{role, content}, ...] 최근 몇 턴만 프런트에서 잘라 보냄

    if not user_message:
        return jsonify({"error": "메시지를 입력해주세요."}), 400

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    client = get_client()
    try:
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, max_tokens=400,
        )
        choice = response.choices[0].message

        if choice.tool_calls:
            messages.append(choice.model_dump(exclude_none=True))
            for call in choice.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                results = _lookup_hscode(args.get("query", ""))
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(results, ensure_ascii=False),
                })
            response = client.chat.completions.create(model=MODEL, messages=messages, max_tokens=400)
            choice = response.choices[0].message

        return jsonify({"reply": choice.content or "죄송해요, 답변을 만들지 못했어요."})
    except Exception as e:
        return jsonify({"error": f"챗봇 응답 중 오류가 발생했습니다: {e}"}), 500

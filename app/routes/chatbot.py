"""플로팅 챗봇 위젯의 백엔드. OpenAI(gpt-4o-mini, 가장 저렴한 모델)에게
사이트 사용 가이드를 답해주게 하고, 아래 3가지는 LLM이 지어내지 않도록
function calling으로 실제 DB/서비스를 직접 조회해서 답하게 한다:
  - lookup_hscode: 관세청 HS코드 마스터 검색
  - search_exhibitions: 조건에 맞는 박람회 검색 (+ 상세 페이지 바로가기 링크)
  - lookup_tariff: 제품+국가의 관세율(FTA 협정세율/MFN 기본세율) 조회
"""

import json

from flask import Blueprint, jsonify, request, url_for
from flask_login import login_required
from sqlalchemy import or_

from app import format_kdate_range
from app.models import Exhibition, HsCodeMaster
from app.routes.mypage import _hs_master_query_available
from app.services import tariff_lookup
from app.services.hscode import resolve_country_iso
from app.services.openai_client import get_client

bp = Blueprint("chatbot", __name__, url_prefix="/chatbot")

MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """당신은 식품 수출 박람회 준비 플랫폼 "FairMate"의 업무 지원 챗봇입니다.
실무자를 대상으로 정중하고 간결한 존댓말로, 핵심만 답하세요. 불필요한 수사나 이모지는 쓰지 않습니다.

아래 [FairMate 사용 가이드]는 이 챗봇이 답변에 실제로 사용할 지식입니다. 사용자가 "웹사이트/사이트
이용 방법", "어떻게 써야 하는지", 특정 기능(대시보드, 박람회 상세, 마이페이지, 부스 컨셉, 바이어 관리 등)의
위치나 사용법을 물으면, 아래 가이드 내용을 근거로 반드시 답변하세요. 이런 질문을 범위 밖으로 판단해
거절하면 안 됩니다. 관련 페이지 링크가 있으면 답변에 그대로 포함하세요 (프런트에서 클릭 가능한 링크로
자동 변환됩니다).

[FairMate 사용 가이드]
- 대시보드(/dashboard/): 대륙/국가별 박람회 목록을 보고 필터링(식품 여부, 규모, 참관대상, 날짜, 검색어)할 수 있습니다.
- 박람회 상세 페이지: "박람회 개요", "시장 개요"(UN Comtrade/관세청 교역통계), "트렌드 조사"(구글 트렌드·리테일 분석),
  "HS코드 & 수출 주의사항"(관세율, 비관세장벽) 탭으로 구성됩니다.
- 내 제품 관리(/mypage/): 제품을 등록하면 HS코드를 검색해 붙일 수 있고, "유망시장 조사"로 국가별 매트릭스 분석을 볼 수 있습니다.
- 부스 컨셉 기획: 박람회 상세 페이지에서 "부스 컨셉 기획 →" 버튼으로 AI가 부스 테마·이벤트·3D 이미지 프롬프트를 생성해줍니다.
- 바이어 관리: 명함을 스캔해 바이어를 등록하고, 메일 템플릿으로 일괄 발송할 수 있습니다.

예시:
사용자: "웹사이트 이용 방법을 안내해주세요"
챗봇: "FairMate는 대시보드에서 박람회를 조건별로 찾아보고, 박람회 상세 페이지에서 시장·트렌드·HS코드
정보를 확인한 뒤, 마이페이지에서 제품을 등록해 유망시장 조사와 부스 컨셉 기획까지 진행하실 수 있습니다.
바이어 관리 메뉴에서는 명함 스캔과 메일 발송도 가능합니다."

[HS코드 검색]
사용자가 특정 제품의 HS코드를 물으면 lookup_hscode 함수를 반드시 호출해서 실제 관세청 데이터로 답하세요.
직접 코드를 추측해서 말하지 마세요.

검색 결과가 없을 때는 아래 순서로 대응하세요:
1) 먼저 "약과", "한과"처럼 더 구체적인/일반적인 다른 표현으로 한 번 더 lookup_hscode를 시도해보세요.
2) 그래도 결과가 없고, 유과·약과·한과처럼 한국 고유 식품이라 관세청 품목명에 정확히 없는 경우라면,
   아는 일반 지식으로 가장 가까울 것으로 보이는 상위 분류(예: 과자류는 HS 1905류)를 참고용으로
   제시하되, 반드시 "정확한 코드로 매칭된 결과가 아니며, 실제 신고 전 관세사·관세청 확인이
   필요하다"는 점을 함께 명시하세요. 없는 코드를 마치 정확한 코드인 것처럼 단정하지 마세요.
3) 정말 아무 단서도 없으면 "정확한 품목명을 알려주시면 다시 확인해드리겠습니다."처럼 정중히 안내하세요.

[박람회 검색]
"다음 달 유럽 박람회 뭐 있어?", "베트남 식품 박람회 찾아줘"처럼 박람회를 찾거나 추천해달라는 질문에는
search_exhibitions 함수를 호출해서 실제 DB 결과로 답하세요. 결과에 포함된 link는 그대로 답변에 적어서
바로 클릭해 들어갈 수 있게 하세요. 결과가 없으면 검색 조건을 좁혀서(국가/키워드) 다시 시도하도록 안내하세요.

[관세율 조회]
"OO 미국 수출할 때 관세율이 얼마야?"처럼 특정 제품+국가의 관세율을 물으면 lookup_tariff 함수를 호출해서
FTA 협정세율(있는 경우)과 관세청 기본세율(MFN)을 실제 데이터로 답하세요. 데이터가 없는 국가/품목이면
정확한 수치를 지어내지 말고 없다고 안내하세요.

[답변 범위]
FairMate 서비스나 이 화면에 관련된 질문이면 폭넓게 답하세요. 위 가이드에 정확히 나온 내용이 아니어도,
박람회 준비·수출 실무·이 웹사이트에 있는 기능/데이터와 관련이 있다고 판단되면 아는 범위에서 성실하게
답하거나 합리적으로 추론해서 답하세요. 모르면 모른다고 솔직히 말하되, 무리해서 거절부터 하지 마세요.

FairMate·이 웹사이트와 정말로 무관한 질문(일반 상식, 날씨, 다른 회사 서비스, 이 서비스와 무관한 코딩 질문 등)
에만 "해당 문의는 이 챗봇이 도와드릴 수 있는 범위를 벗어납니다."라고 짧게 안내하세요. 애매하면 거절하지 말고
답변을 시도하세요.

답변은 3~5문장 이내로 간결하게, 실무 보고체로 작성하세요."""

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
    },
    {
        "type": "function",
        "function": {
            "name": "search_exhibitions",
            "description": "조건에 맞는 박람회를 FairMate DB에서 검색한다 (최신 일정순 최대 5건).",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "박람회명에 포함될 키워드 (예: Food, Bakery)"},
                    "country": {"type": "string", "description": "국가명 (한글 또는 영문, 예: 베트남, Vietnam)"},
                    "food_only": {"type": "boolean", "description": "식품 관련 박람회만 볼지 여부"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_tariff",
            "description": "제품명 + 수출 대상국으로 관세율(FTA 협정세율, 관세청 기본세율(MFN))을 조회한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "제품명 (예: 유과, 김)"},
                    "country": {"type": "string", "description": "수출 대상국 (한글 또는 영문, 예: 미국, Vietnam)"},
                },
                "required": ["product", "country"],
            },
        },
    },
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


def _search_exhibitions(keyword=None, country=None, food_only=None):
    query = Exhibition.query.filter(Exhibition.is_active == 1)
    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(Exhibition.name.ilike(like), Exhibition.city.ilike(like))
        )
    if country:
        like = f"%{country.strip()}%"
        query = query.filter(
            or_(Exhibition.country.ilike(like), Exhibition.country_ko.ilike(like))
        )
    if food_only:
        query = query.filter(Exhibition.food_yn == 1)

    rows = query.order_by(Exhibition.start_date.asc()).limit(5).all()
    return [
        {
            "name": expo.name,
            "country": expo.country_ko or expo.country,
            "city": expo.city,
            "date": format_kdate_range(expo.start_date, expo.end_date),
            "scale": expo.scale or "미상",
            "link": url_for("exhibition.detail", expo_id=expo.id),
        }
        for expo in rows
    ]


def _lookup_tariff(product, country):
    iso3 = resolve_country_iso(country) if country else None
    if not iso3:
        return {"error": f"'{country}' 국가를 인식하지 못했습니다. 국가명을 다시 확인해주세요."}

    matches = _lookup_hscode(product)
    if not matches:
        return {"error": f"'{product}'에 해당하는 HS코드를 찾지 못했습니다. 품목명을 조금 더 구체적으로 알려주세요."}

    hscode_val = matches[0]["hscode"]
    best = tariff_lookup.get_best_regime(hscode_val, iso3)
    mfn = tariff_lookup.get_mfn_rate(hscode_val, iso3)

    if not best and not mfn:
        return {
            "hscode": hscode_val,
            "product_name": matches[0]["name_ko"],
            "country": country,
            "error": "이 국가/품목 조합의 관세율 데이터가 없습니다.",
        }

    return {
        "hscode": hscode_val,
        "product_name": matches[0]["name_ko"],
        "country": country,
        "mfn_rate": mfn["display"] if mfn else None,
        "best_fta_regime": best["regime"] if best else None,
        "best_fta_rate": best["display"] if best else None,
    }


_TOOL_FUNCS = {
    "lookup_hscode": lambda args: _lookup_hscode(args.get("query", "")),
    "search_exhibitions": lambda args: _search_exhibitions(
        keyword=args.get("keyword"), country=args.get("country"), food_only=args.get("food_only"),
    ),
    "lookup_tariff": lambda args: _lookup_tariff(args.get("product", ""), args.get("country", "")),
}


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
            model=MODEL, messages=messages, tools=TOOLS, max_tokens=500,
        )
        choice = response.choices[0].message

        if choice.tool_calls:
            messages.append(choice.model_dump(exclude_none=True))
            for call in choice.tool_calls:
                args = json.loads(call.function.arguments or "{}")
                func = _TOOL_FUNCS.get(call.function.name)
                results = func(args) if func else {"error": "알 수 없는 기능입니다."}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(results, ensure_ascii=False),
                })
            response = client.chat.completions.create(model=MODEL, messages=messages, max_tokens=500)
            choice = response.choices[0].message

        return jsonify({"reply": choice.content or "죄송해요, 답변을 만들지 못했어요."})
    except Exception as e:
        return jsonify({"error": f"챗봇 응답 중 오류가 발생했습니다: {e}"}), 500

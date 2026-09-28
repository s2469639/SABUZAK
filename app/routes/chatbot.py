"""플로팅 챗봇 위젯의 백엔드. OpenAI(gpt-4o-mini, 가장 저렴한 모델)에게
사이트 사용 가이드를 답해주게 하고, 아래 3가지는 LLM이 지어내지 않도록
function calling으로 실제 DB/서비스를 직접 조회해서 답하게 한다:
  - lookup_hscode: 관세청 HS코드 마스터 검색
  - search_exhibitions: 조건에 맞는 박람회 검색 (+ 상세 페이지 바로가기 링크)
  - lookup_tariff: 제품+국가의 관세율(FTA 협정세율/MFN 기본세율) 조회
"""

import json
import re

from flask import Blueprint, jsonify, request, url_for
from flask_login import login_required
from sqlalchemy import func, or_

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

항상 0단계로, 사용자가 말한 제품명 그대로 먼저 한 번 검색하세요("식혜"처럼 일상 단어가 공식
품목명과 정확히 같은 경우도 꽤 있어서, 지레짐작으로 건너뛰면 오히려 놓칩니다).

그 검색이 비었을 때만 아래처럼 넓혀가세요. 관세청 마스터 데이터의 품목명은 종종 "즉석밥"/"햇반"이
아니라 "찌거나 삶은 쌀"처럼 가공 상태·원재료 중심의 딱딱한 공식 용어로 되어 있어서, 사용자가 흔히
쓰는 제품명 그대로는 안 나올 수 있습니다.

검색 결과가 없을 때는 아래 순서로 재시도하세요 (lookup_hscode를 여러 번 호출해도 됩니다):
1) 먼저 제품명에서 핵심 원재료만 뽑아 검색하세요. 예: "즉석밥"/"햇반" → "쌀", "냉동만두" → "만두"
   또는 "밀가루", "조미김" → "김", "라면" → "면". 그래도 안 되면 그 원재료의 다른 표현(가공 상태,
   예: "삶은", "찐", "건조한", "냉동한" 등)을 조합해서 한두 번 더 시도해보세요.
2) 원재료로도 안 나오면, "이 식품이 관세청 분류상 실제로 어느 대분류에 속할지"를 스스로 판단해서
   그 대분류 키워드로 검색하세요. 원재료가 무엇이든 관세 분류는 완제품의 성격(음료/과자·베이커리/
   조미료/유제품 등)을 따르는 경우가 많습니다. 예: "식혜"는 쌀이 재료지만 완제품은 음료라서
   "쌀"로는 절대 안 나오고 "음료" 또는 "청량음료"로 검색해야 나옵니다("2202.99" 계열). 마찬가지로
   "수정과"→"음료", "조청"→"당" 또는 "시럽", "육포"→"건조" 또는 "육류가공품"처럼, 완제품이
   실제로 속할 상위 카테고리를 추론해서 검색어를 바꿔보세요.
   특히 제품명이 "OO부각"(튀긴 것), "OO튀김", "OO강정", "OO칩", "OO스낵"처럼 가공 형태를 나타내는
   접미사로 끝나면, 원재료 자체(예: "김부각"의 "김")로만 검색한 결과는 원재료 원물(예: 냉동/건조
   상태의 김)일 뿐 실제로는 무관한 후보일 가능성이 높습니다. 이런 경우 원재료 검색과 별도로 반드시
   "과자" 또는 "스낵"으로도 한 번 더 검색해서(예: "김부각" → "과자"), 두 결과를 비교해 실제
   완제품(조미·가공 과자류, HS 19류·20류 등)에 더 가까운 후보를 우선 제시하세요. 원재료 원물
   후보(예: "2005.99 김치"처럼 단순 글자 일치로 걸린 것, 또는 가공 안 된 원물 김)는 완제품과
   무관하면 답변에서 제외하세요.
3) 그래도 결과가 없고, 유과·약과·한과처럼 한국 고유 식품이라 관세청 품목명에 정확히 없는 경우라면,
   아는 일반 지식으로 가장 가까울 것으로 보이는 상위 분류(예: 과자류는 HS 1905류)를 참고용으로
   제시하되, 반드시 "정확한 코드로 매칭된 결과가 아니며, 실제 신고 전 관세사·관세청 확인이
   필요하다"는 점을 함께 명시하세요. 없는 코드를 마치 정확한 코드인 것처럼 단정하지 마세요.
4) 정말 아무 단서도 없으면 "정확한 품목명을 알려주시면 다시 확인해드리겠습니다."처럼 정중히 안내하세요.

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


def _bigrams(s):
    """유사도 계산용 2-gram 집합. 한 글자짜리 단어도 빈 집합이 되지 않게
    그 글자 자체를 넣어준다."""
    s = re.sub(r"\s+", "", s)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _bigram_similarity(a, b):
    """Dice 계수 기반 문자열 유사도(0~1). 관세청 공식 품목명은 어순/표현이
    실제 제품명과 달라 ILIKE 부분일치로는 못 잡는 경우가 많아서, 이 유사도로
    "표현은 다르지만 겹치는 글자가 많은" 후보를 찾아낸다."""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return 2 * len(A & B) / (len(A) + len(B))


# 0.28은 "냉동만두" -> "냉동 연육"류처럼 흔한 단어 하나만 겹쳐도 통과하는
# 오탐이 실측 확인됐다 (관세청 마스터 11,499건 기준 재현). 0.35에서는 그
# 오탐과 "고추장" -> "고추다진양념" 같은 경계선 노이즈가 사라지면서도,
# 실제 정답 매치(식혜/라면/김치/고추장/된장/간장/과자/홍삼/미역 등)는 전부
# 그대로 유지됨을 같은 데이터로 확인했다.
_SIMILARITY_THRESHOLD = 0.35


def _search_hscode_by_similarity(query, limit=20):
    """ILIKE 검색이 비었을 때의 최후 수단. 전체 마스터(약 1만 건)를 유사도
    점수로 스캔해서 상위 후보를 돌려준다. 테이블이 작아서(1만여 건) 매 요청
    풀스캔해도 챗봇 응답속도에 문제되지 않는 수준이다."""
    candidates = []
    for r in HsCodeMaster.query.all():
        name = r.name_ko or r.hsk_name or ""
        if not name:
            continue
        score = max(_bigram_similarity(query, name), _bigram_similarity(query, r.hsk_name or ""))
        if score >= _SIMILARITY_THRESHOLD:
            candidates.append((score, r))
    candidates.sort(key=lambda t: t[0], reverse=True)

    # 완전 일치(1.0)가 하나라도 있으면 그걸로 검색어가 이미 해결된 것이므로,
    # "소주" -> "채소 주스"(0.5)처럼 단어 안에 우연히 끼어든 부분일치 노이즈를
    # 같이 보여줄 이유가 없다. 점수가 정렬돼 있으니 맨 앞이 1.0인지만 보면 된다.
    if candidates and candidates[0][0] >= 1.0:
        candidates = [c for c in candidates if c[0] >= 1.0]

    return [r for _, r in candidates[:limit]]


def _lookup_hscode(query):
    """제품명으로 관세청 마스터를 검색한다. name_ko는 공식 품목명이라 "냉동
    손만두"처럼 실제 제품명을 통째로 넣으면 거의 매칭이 안 된다 (실제로는
    "만두 냉동한 것"처럼 순서/표현이 다름). 그래서 문구 전체로 먼저
    시도하고, 안 걸리면 단어 단위로 쪼개서 OR 검색하고, 그래도 안 걸리면
    유사도 기반 검색으로 넓힌다."""
    if not query or not _hs_master_query_available():
        return []
    query = query.strip()

    def _search(like_terms):
        conditions = [
            HsCodeMaster.name_ko.ilike(f"%{t}%") | HsCodeMaster.hsk_name.ilike(f"%{t}%")
            for t in like_terms
        ]
        # 검색어를 "쌀"처럼 원재료 단위로 넓히면 관련 없는 것까지 수십 건씩
        # 걸리는데, limit을 너무 낮게 잡으면(예전 8건) 정작 맞는 품목(예:
        # "찌거나 삶은 쌀")이 순서상 뒤에 있어 응답에 아예 안 실렸다.
        # 이름이 짧을수록 더 일반적인/핵심적인 품목일 가능성이 높아서 그걸
        # 우선 보여주고, 건수도 20건까지 넉넉하게 준다.
        return (
            HsCodeMaster.query.filter(or_(*conditions))
            .order_by(func.length(HsCodeMaster.name_ko))
            .limit(20)
            .all()
        )

    rows = _search([query])
    if not rows:
        words = [w for w in re.split(r"\s+", query) if len(w) >= 2]
        if words:
            rows = _search(words)
    if not rows:
        rows = _search_hscode_by_similarity(query)
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

        # 최대 3라운드까지 tool을 반복 호출할 수 있게 한다. 이전엔 tool 결과를
        # 받은 뒤 마지막 응답 요청에 tools를 안 넘겨서, 검색이 비었을 때
        # "다른 키워드로 다시 검색해보라"는 지침이 있어도 모델이 실제로는
        # 두 번째 검색을 시도할 방법이 없었다 (그래서 계속 "못 찾음"만 반복).
        for _ in range(4):
            if not choice.tool_calls:
                break
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
            response = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS, max_tokens=500,
            )
            choice = response.choices[0].message

        return jsonify({"reply": choice.content or "죄송해요, 답변을 만들지 못했어요."})
    except Exception as e:
        return jsonify({"error": f"챗봇 응답 중 오류가 발생했습니다: {e}"}), 500

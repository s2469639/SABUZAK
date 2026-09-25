"""v12 오프라인 테스트용 가짜 응답 (trend_usp_v1·tavily_v9 테스트에서 복사).

- 섹션 1: 가짜 Google 트렌드(FakeTrends)·OpenAI JSON 응답(fake_chat_json)
- 섹션 3·4: 가짜 Tavily(FakeTavily)·OpenAI(FakeOpenAI, fake_ask_json)
"""

import json
import re
from types import SimpleNamespace

import research  # noqa: F401  (복사한 코드가 참조)
import trend_usp  # noqa: F401

PRODUCT = {
    "name": "약과",
    "strengths": "조청 흡수가 적어 손에 안 묻는 식감, 개별 포장",
    "ingredients": "밀가루, 꿀, 참기름",
    "certifications": "HACCP",
    "price": "200g 소매가 6~7달러",
}
PITCH_PRODUCT = {**PRODUCT, "shelf_life": "상온 12개월", "pack_format": "개별 포장 30g × 10입"}


def weekly_series(base: float, recent: float, weeks: int = 260) -> list:
    """앞부분은 base, 마지막 13주는 recent인 주간 시계열."""
    return [base] * (weeks - 13) + [recent] * 13


def q(query, value):
    return {"query": query, "value": value}


RELATED = {
    "yakgwa": {
        "top": [q("yakgwa recipe", 100), q("costco yakgwa", 40), q("korean honey cookie", 60), q("yakgwa", 50)],
        "rising": [q("buy yakgwa near me", 340), q("yakgwa ice cream", 9000), q("baklava vs yakgwa", 120)],
    },
    "korean honey cookie": {
        "top": [q("Yakgwa  Recipe", 40), q("honey pastry biscuit", 20)],
        "rising": [q("kpop demon hunters snack", 250)],
    },
    "korean dessert": {
        "top": [q("bingsu", 80), q("hotteok", 60), q("korean dessert near me", 50), q("yakgwa with coffee", 30)],
        "rising": [],
    },
}
TOPICS = {"yakgwa": {"top": [{"query": "Baklava", "value": 50, "topic_type": "Dessert"}], "rising": []}}

SERIES = {
    "yakgwa": weekly_series(10, 10),                 # 기준점(anchor)
    "yakgwa recipe": weekly_series(40, 34),          # -15%
    "buy yakgwa near me": weekly_series(0, 0),       # 증감 불가 → 급상승 배지로 대체
    "costco yakgwa": weekly_series(5, 22),           # +340%
    "yakgwa ice cream": weekly_series(10, 20),       # +100%
    "baklava vs yakgwa": weekly_series(0, 3),        # 증감 불가, 급상승 없음 → 배지 없음(아니면 급상승)
    "honey pastry biscuit": weekly_series(20, 29),   # +45%
    "yakgwa with coffee": weekly_series(10, 10),     # 0%
    "Baklava": weekly_series(30, 30),
    "kdrama yakgwa": weekly_series(2, 6),            # 탐색 후보 → 검색량 있음 → 유지
    "yakgwa tiktok": weekly_series(0, 0),            # 탐색 후보 → 검색량 없음 → 제거
    "baklava": weekly_series(30, 30),                # 경쟁 제품: 우리 대비 ×3.0
    "biscoff": weekly_series(50, 50),                # 경쟁 제품: 우리 대비 ×5.0
    "ghost brand xyz": weekly_series(0, 0),          # 경쟁 제품: 검색 흔적 없음
}


def _ids_from_listing(prompt: str) -> dict:
    ids = {}
    for line in prompt.splitlines():
        m = re.match(r"^\[(\d+)\] (.*?)( \(급상승\))?( \(연관 주제.*\))?$", line)
        if m:
            ids[m.group(2)] = int(m.group(1))
    return ids


def fake_chat_json(system_prompt, user_prompt, temperature, strategy=False):
    p = user_prompt
    if "Google 트렌드 조사용 프로필" in p:
        return {"geo": "PE", "name_ko": "페루", "languages": ["Spanish"], "hl": "es-419",
                "buyer_language": "Spanish", "reliability": "high", "reliability_note_ko": ""}
    if "Google에 실제로 입력하는 검색어를 만드세요" in p:
        assert not strategy
        return {"seeds": [{"keyword": "yakgwa", "lang": "English", "ko": "약과"},
                          {"keyword": "korean honey cookie", "lang": "English", "ko": "한국 꿀과자"},
                          {"keyword": "YAKGWA", "lang": "English", "ko": "중복"}],
                "categories": [{"keyword": "korean dessert", "lang": "English", "ko": "한국 디저트"}],
                "english_name": "Yakgwa"}
    if "추정해야 합니다" in p:
        return {"keywords": ["yakgwa recipe", "buy yakgwa online", "yakgwa vs baklava", "yakgwa with tea"]}
    if "[현지 연관 검색어·연관 주제 목록]" in p:
        ids = _ids_from_listing(p)

        def ref(kw, **extra):
            return {"id": ids.get(kw, 999), "ko": f"{kw} 해석", **extra}

        return {"clusters": {
            "culture_trigger": {"items": [], "summary_ko": "", "tag_ko": "", "insight_ko": ""},
            "intent_funnel": {"items": [ref("buy yakgwa near me", stage="purchase"),
                                        ref("yakgwa recipe", stage="consideration"),
                                        ref("costco yakgwa", stage="purchase"),
                                        {"id": 999, "ko": "지어낸 검색어"},
                                        ref("yakgwa ice cream")],  # 아래 habit과 중복 → 먼저 온 쪽만
                              "summary_ko": "구매 전환", "tag_ko": "구매 단계 전환", "insight_ko": "완제품 타깃"},
            "category_perception": {"items": [ref("Baklava"), ref("baklava vs yakgwa"), ref("honey pastry biscuit")],
                                    "summary_ko": "대체재 비교", "tag_ko": "경쟁 브랜드", "insight_ko": "차별화"},
            "consumption_habit": {"items": [ref("yakgwa with coffee"), ref("yakgwa ice cream")],
                                  "summary_ko": "커피 페어링", "tag_ko": "취식 페어링", "insight_ko": "번들 제안"},
        }, "excluded": [{"id": ids.get("hotteok", 999), "reason_ko": "다른 음식"}]}
    if "신호가 부족했습니다" in p:
        return {"probes": {"culture_trigger": [{"keyword": "kdrama yakgwa", "ko": "드라마 약과"},
                                               {"keyword": "yakgwa tiktok", "ko": "틱톡 약과"},
                                               {"keyword": "Yakgwa Recipe", "ko": "이미 있는 검색어"}]}}
    if "buyer_checkpoints" in p:
        assert strategy
        return {"competitors": [
            {"name": "Baklava", "name_ko": "바클라바", "search_term": "baklava", "features_ko": "시럽이 많음",
             "price_local": "$8.99 / 12oz", "channel_ko": "마트", "confidence": "high"},
            {"name": "Korean Snacks", "name_ko": "한국 과자", "search_term": "korean snacks", "confidence": "high"},
            {"name": "Biscoff Cookies", "name_ko": "비스코프", "search_term": "biscoff", "features_ko": "캐러멜 쿠키",
             "price_local": "", "channel_ko": "마트", "confidence": "medium"},
            {"name": "Ghost Brand Pastry", "name_ko": "유령", "search_term": "ghost brand xyz", "confidence": "low"},
        ], "buyer_checkpoints": [{"item_ko": "유통기한", "why_ko": "수입 리드타임"},
                                 {"item_ko": "영문 라벨", "why_ko": "FDA 표시 규정"}]}
    if "USP 행을 만드세요" in p:
        assert strategy
        if "[재작성 요청]" in p:
            return {"rows": [
                {"competitor_id": "C1", "consumer_pain_ko": "시럽이 끈적임", "our_fix_ko": "손에 안 묻는 식감",
                 "evidence_fields": ["strengths"], "benefit_phrase": "no sticky syrup",
                 "pitch_headline": "No sticky syrup: honey pastry that stays clean", "pitch_headline_ko": "끈적임 없는 꿀과자"},
                {"competitor_id": "C2", "consumer_pain_ko": "너무 달다", "our_fix_ko": "개별 포장으로 간편",
                 "evidence_fields": ["strengths"], "benefit_phrase": "individually wrapped",
                 "pitch_headline": "Individually wrapped honey bites for on-the-go", "pitch_headline_ko": "개별 포장"},
            ]}
        return {"rows": [
            {"competitor_id": "C1", "consumer_pain_ko": "시럽이 끈적임", "our_fix_ko": "손에 안 묻는 식감",
             "evidence_fields": ["strengths", "unknown_field"], "benefit_phrase": "no sticky syrup",
             "pitch_headline": "Experience the Unique Taste of Yakgwa!", "pitch_headline_ko": "독특한 맛"},
            {"competitor_id": "C2", "consumer_pain_ko": "너무 달다", "our_fix_ko": "비건 인증 전통 레시피",
             "evidence_fields": ["certifications"], "benefit_phrase": "individually wrapped",
             "pitch_headline": "Individually wrapped vegan bites", "pitch_headline_ko": "개별 포장 비건"},
            {"competitor_id": "C9", "consumer_pain_ko": "없는 행", "our_fix_ko": "", "evidence_fields": [],
             "benefit_phrase": "", "pitch_headline": "", "pitch_headline_ko": ""},
        ]}
    if "박람회 부스 카드를 만드세요" in p:
        assert strategy
        return {
            "headline_slogan": {"title": "Heritage Honey Lounge", "title_ko": "헤리티지 라운지",
                                "slogan": "Sweet Heritage, Zero Sticky Fingers", "slogan_ko": "끈적임 없는 전통 단맛",
                                "sub_copy": "Pairs with your coffee", "sub_copy_ko": "커피와 함께",
                                "key_visual_ko": "커피잔 옆 약과", "refs": ["K1", "X9", "input:strengths"]},
            "sampling_strategy": {"title": "Baklava vs Yakgwa Bar", "title_ko": "비교 시식 바", "compare_with": "U1",
                                  "serving_ko": "한입 크기", "staff_line": "Try it — no sticky hands!",
                                  "staff_line_ko": "손에 안 묻어요", "collect_ko": "명함", "refs": ["U1"]},
            "pitching_wall": {"title": "Buyer Facts", "title_ko": "바이어 팩트", "refs": ["input:shelf_life"], "blocks": [
                {"headline": "Shelf life", "headline_ko": "유통기한", "value": "12 months", "source_field": "shelf_life"},
                {"headline": "Shelf life", "headline_ko": "유통기한", "value": "24 months", "source_field": "shelf_life"},
                {"headline": "MOQ", "headline_ko": "최소 주문", "value": "1000 boxes", "source_field": "moq_price"},
                {"headline": "Retail price", "headline_ko": "소매가", "value": "$6-7", "source_field": "price"},
            ]},
            "packaging_display": {"title": "Grab & Go Line", "title_ko": "그랩앤고", "layout_ko": ["눈높이 진열", "커피 옆 번들"],
                                  "pop_copy": "No sticky fingers", "pop_copy_ko": "손에 안 묻어요",
                                  "refs": ["input:shelf_life", "K2"]},
        }
    raise AssertionError(f"예상하지 못한 프롬프트: {p[:200]}")


class FakeTrends:
    fail_related = False
    fail_iot = False
    sparse = False
    calls = []

    def __init__(self, hl, use_cache=True):
        self.hl = hl

    def related(self, keywords, geo, timeframe):
        FakeTrends.calls.append(("related", tuple(keywords), geo, timeframe))
        if FakeTrends.fail_related:
            raise RuntimeError("429 Too Many Requests")
        if FakeTrends.sparse:
            n = len([c for c in FakeTrends.calls if c[0] == "related"])
            return {"queries": {"yakgwa": {"top": [q(f"yakgwa level{n} q{i}", 10 + i) for i in range(4)], "rising": []}},
                    "topics": {}}
        return {"queries": {kw: RELATED.get(kw, {"top": [], "rising": []}) for kw in keywords},
                "topics": {kw: TOPICS[kw] for kw in keywords if kw in TOPICS}}

    def interest_over_time(self, keywords, geo):
        FakeTrends.calls.append(("iot", tuple(keywords), geo))
        if FakeTrends.fail_iot:
            raise RuntimeError("429 Too Many Requests")
        return {kw: SERIES.get(kw, weekly_series(0, 0)) for kw in keywords}




# ---- tavily_v9 ----

def article(qid, domain, sentence, extra=""):
    """가짜 검색 결과. 제목 앞의 [Q번호]로 가짜 발췌기가 질문을 정한다."""
    body = f"{sentence} {extra}".strip()
    return {"title": f"[{qid}] {domain} article", "url": f"https://www.{domain}/2026/{abs(hash(sentence)) % 10000}",
            "content": body, "raw_content": body, "published_date": "2026-05-01"}


def fake_search_results(query, params):
    domains = params.get("include_domains") or []
    if params.get("search_depth") == "basic":  # 용어 검증 검색
        return [article("Q1", "blog-a.com", "Yakgwa is a Korean honey cookie loved by many."),
                article("Q1", "blog-b.com", "Where to buy yakgwa in the United States.")]
    if "nytimes.com" in domains:  # Q1 1차 (언론): 국가명 없는 기사도 주요 사이트면 대상 국가로 인정돼야 함
        return [article("Q1", "nytimes.com", "Shoppers say yakgwa is less sticky than baklava and easy to carry."),
                article("Q1", "eater.com", "Young diners buy yakgwa as a coffee pairing snack in American cafes.")]
    if "walmart.com" in domains:  # Q2 1차 (유통·업계지): 출처 1곳뿐 → 코드 기준 미달
        return [article("Q2", "walmart.com", "Honey cookies from local brands sell for $4.99 per pack in the United States.")]
    if "fda.gov" in domains:  # Q3 1차 (업계지·공공): 발췌는 충분하지만 필수 측면(인증 요건)은 없음 → AI 판정 미달
        return [article("Q3", "fooddive.com", "US grocery buyers prefer korean dessert brands with retail-ready packaging."),
                article("Q3", "supermarketnews.com", "American importers of korean dessert favor distributors with cold chain.")]
    if domains == research.KR_PUBLIC_DOMAINS or "anuga.com" in domains or "specialtyfood.com" in domains:
        return []
    # 2차 일반 웹
    if "honey cookies" in query.lower() or "brands" in query.lower() or "price" in query.lower():
        return [article("Q2", "koreanfoodnews.com", "In the United States, yakgwa gift boxes compete with baklava at $12 each."),
                article("Q2", "snackblog.org", "American shoppers compare honey cookies brands like Biscoff on price.")]
    if "fda" in query.lower() or "certification" in query.lower() or "importers" in query.lower():
        return [article("Q3", "importguide.com", "US importers require FDA registration for korean dessert products.")]
    return []


RESEARCH_CALLS = []


def web_research_response():
    body = json.dumps({"notes": [
        {"topic": "competitor", "text": "Bibigo mandu is sold at Costco for $14.99.", "source_url": "https://www.costco.com/bibigo",
         "source_title": "Costco Bibigo"},
        {"topic": "exhibition", "text": "Winter Fancy Faire는 샌디에이고에서 열리는 B2B 전용 행사다.",
         "source_url": "https://made-up.example.com/wff", "source_title": ""},
        {"topic": "consumer", "text": "냉동 만두는 간편 식사로 소비된다.", "source_url": ""},
        {"topic": "unknown_topic", "text": "토픽이 이상하면 trend로"},
        {"topic": "buyer"},
    ]})
    cite = SimpleNamespace(type="url_citation", url="https://www.costco.com/bibigo", title="Costco Bibigo")
    return SimpleNamespace(output_text="검색 결과입니다.\n```json\n" + body + "\n```",
                           output=[SimpleNamespace(type="web_search_call"),
                                   SimpleNamespace(type="message", content=[SimpleNamespace(annotations=[cite])])])


class FakeResponses:
    fail = False

    def create(self, **kwargs):
        RESEARCH_CALLS.append(kwargs)
        if FakeResponses.fail:
            raise RuntimeError("web_search not supported for this model")
        return web_research_response()


class FakeOpenAI:
    def __init__(self):
        self.responses = FakeResponses()


class FakeTavily:
    def __init__(self):
        self.calls = []

    def search(self, query, include_raw_content=True, **params):
        self.calls.append({"query": query, **params})
        return {"results": fake_search_results(query, params)}


BOOTH_CALLS = []
# 가짜 채점 결과. 테스트에서 바꿔 "기준 통과 / 수정" 경로를 고른다
REVIEW_SCORES = {"insight": 5, "single_minded": 3, "buyer_value": 4, "specificity": 4, "distinctiveness": 5,
                 "feasibility": 4}


def booth_payload(stage):
    """가짜 부스 기획안. stage별로 요약만 다르게 해서 어떤 단계 결과가 쓰였는지 확인한다."""
    return {
        "summary": f"{stage}: 휴대성과 커피 페어링을 앞세운 약과 부스",
        "positioning": {"target_buyer": "스페셜티 식료품 바이어", "core_message": "손에 안 묻는 한국 꿀과자"},
        "main_visual": {"concept_en": "Honey Heritage, No Sticky Fingers", "concept_ko": "끈적임 없는 꿀 전통",
                        "key_message": "테이크아웃 커피 옆 한입 간식",
                        "bullets": [{"text": "커피잔 옆 약과 클로즈업 백월", "basis": ["R2", "R99", "E1"]},
                                    {"text": "우드톤 카페 무드", "basis": ["기획"]}]},
        "slogan": {"main_en": "Sweet Heritage, Zero Sticky Fingers", "main_ko": "끈적임 없는 전통 단맛",
                   "sub_en": "Your coffee's new best friend", "sub_ko": "커피의 새 단짝",
                   "bullets": [{"text": "강점(손에 안 묻음)을 전면에", "basis": ["기업:강점"]}]},
        "signature_pairing": {"item": "아메리카노", "intent": "카페 페어링 수요",
                              "bullets": [{"text": "에스프레소 샷과 한입 약과", "basis": ["R2"]}]},
        "demonstration": {"title": "10초 언박싱 시연", "bullets": [{"text": "개별 포장 뜯어 바로 시식", "basis": ["기업:없는항목"]}]},
        "packaging": {"direction": "Grab & Go", "bullets": "문자열 불릿도 받아야 함"},
        "merchandising": {"zones": [{"name": "Hero Zone", "position": "중앙", "purpose": "대표 제품", "basis": ["R1"]},
                                   {"name": "", "position": "우측", "purpose": "이름 없는 존은 버림"}],
                          "bullets": [{"text": "눈높이 진열", "basis": []}]},
        "key_actions": [{"title": "흰 장갑 시식으로 끈적임 없음 증명",
                         "detail": "10월 2일까지 운영 담당이 흰 장갑 200켤레와 시식 동선을 확정하고, 첫날 오전 리허설로 10초 안에 시식이 끝나는지 확인한다. 근거: R2·R3, 기획.",
                         "basis": ["R2", "기업:강점"]},
                        {"title": "커피 페어링 바 운영", "detail": "아메리카노 옆 한입 약과", "basis": ["R2"]},
                        "케이스 단가표로 상담 전환"],
        "visitor_flow": {"3s": {"headline": "흰 장갑 백월로 시선 고정", "goal": "통로 방문객 멈추기",
                                "visitor": ["5m 밖에서 No Sticky Fingers 문구가 보임"], "staff": ["눈 마주치면 샘플 권유"],
                                "props": ["흰 장갑", "꿀 방울 백월"], "message": "손에 안 묻는 꿀과자"},
                         "30s": "커피와 한입 시식",      # 예전 형식(문장 하나)도 받아야 함
                         "3min": {"headline": "원페이저 상담", "staff": "케이스 단가·MOQ 안내"}},
        "kpis": [{"metric": "유효 바이어 상담", "target": "80건", "how": "명함을 받고 3분 이상 상담한 바이어 수를 부스 태블릿에 기록해 매일 저녁 집계한다."},
                 "샘플 요청 20건"],
        "risks": [{"text": "화기 사용 허가 확인", "basis": []}],
        "questions": ["유통기한은 몇 개월인가요?"],
        "applied": ["시연을 10초 언박싱으로 단축"] if stage == "revised" else [],
    }


def fake_ask_json(client, prompt, temperature=0.0, model=None, system=None):
    p = prompt
    if "화면에 먼저 보여줄 짧은 요약" in p:
        items = json.loads(p[p.index("["):p.index("\n\nJSON:")])
        return {"items": [{"id": it["id"], "short": "요약: " + it["text"][:12]} for it in items]}
    if "알고 있는 지식으로 정리하세요" in p:
        BOOTH_CALLS.append(("knowledge", model, system))
        return {"notes": [{"topic": "consumer", "text": "모델 지식 메모", "source_url": "https://should-be-dropped"}]}
    if "스킬의 1~4단계" in p:
        BOOTH_CALLS.append(("brief", model, system))
        return {"insights": [{"fact": "덜 끈적이는 간식 선호", "insight": "손 더럽히지 않는 한입", "implication": "끈적임 비교 시식",
                              "basis": ["R1"]},
                             {"fact": "", "insight": "", "implication": "인사이트 없는 항목은 버림"}],
                "target_buyers": [{"priority": 1, "type": "스페셜티 리테일 MD", "job": "차별성·소량 발주"}],
                "big_idea": {"line_en": "Honey pastry that won't stick to your fingers", "line_ko": "손에 안 묻는 꿀과자",
                             "why": "강점과 소비자 불만이 맞닿음", "basis": ["기업:강점", "R1"]},
                "rtb": [{"text": "조청 흡수가 적은 공정", "basis": ["기업:강점"]}]}
    if "부스 컨셉 기획안을 작성하세요" in p:
        BOOTH_CALLS.append(("draft", model, system))
        assert "빅 아이디어" in p and "Honey pastry that won't stick" in p  # 전략 뼈대가 초안에 전달됨
        return booth_payload("draft")
    if "채점표의 각 항목" in p:
        BOOTH_CALLS.append(("review", model, system))
        return {"scores": {k: {"score": v, "reason": f"{k} 이유"} for k, v in REVIEW_SCORES.items()} | {"unknown": {"score": 1}},
                "overall": "가격 정보가 약함",
                "comments": [{"section": "demonstration", "issue": "시연이 길다", "suggestion": "10초 안에"}]}
    if "채점표로 평가되었습니다" in p:
        BOOTH_CALLS.append(("revise", model, system))
        return booth_payload("revised")
    if "식품 수출 시장조사용 검색어를 준비합니다" in p:
        return {"product_terms": ["yakgwa", "korean honey cookie"], "category_terms": ["korean dessert", "honey cookies"],
                "kfood_terms": ["korean food"], "country_names": ["American", "US market"], "country_ko": "미국",
                "category_ko": "한과", "words": {}, "region_en": "North America", "region_ko": "북미",
                "category_en": "korean dessert"}
    if "주요 웹사이트를 고릅니다" in p:
        return {"media": ["elcomercio.pe", "https://www.larepublica.pe/news", "facebook.com", "made-up-news.pe"],
                "trade": ["not a domain"], "retail": ["plazavea.com.pe"], "public": ["kotra.or.kr", "digesa.minsa.gob.pe"]}
    if "'충분한 답'이 되려면" in p:
        return {
            "Q1": [{"id": "a", "label_ko": "구매 이유", "essential": True, "search_hint": "why buy"},
                   {"id": "b", "label_ko": "취식 상황", "essential": False, "search_hint": "coffee pairing"},
                   {"id": "c", "label_ko": "불만", "essential": False, "search_hint": "sticky"}],
            "Q2": [{"id": "a", "label_ko": "경쟁 브랜드", "essential": True, "search_hint": "brands"},
                   {"id": "b", "label_ko": "판매 가격", "essential": True, "search_hint": "price"},   # 필수 2개 → 1개로
                   {"id": "c", "label_ko": "판매 메시지", "essential": False, "search_hint": "가격"}],  # 한글 힌트 제거
            "Q3": [{"id": "a", "label_ko": "수입 인증 요건", "essential": True, "search_hint": "FDA certification"},
                   {"id": "b", "label_ko": "유통 채널", "essential": False, "search_hint": "distributors"},
                   {"id": "c", "label_ko": "패키지 선호", "essential": False, "search_hint": "packaging"}],
            "Q4": [{"id": "a", "label_ko": "박람회 트렌드", "essential": True, "search_hint": "trends"}],  # 1개 → 기본 측면
        }
    if "측면(aspects) 목록과 원문 발췌" in p:
        payload = json.loads(p[p.index("{"):p.index("\n\n1) coverage")])
        out = {}
        for qid, item in payload.items():
            ids = [q["id"] for q in item["quotes"]]
            aspects = [a["id"] for a in item["aspects"]]
            if qid == "Q1":   # 모든 측면 충족 (없는 E99는 무시돼야 함)
                out[qid] = {"coverage": {aspects[0]: [ids[0], "E99"], aspects[1]: [ids[1]], aspects[2]: [ids[0]]},
                            "followup_queries": []}
            elif qid == "Q3":  # 필수 측면(인증) 미충족
                out[qid] = {"coverage": {aspects[1]: [ids[1]], aspects[2]: [ids[0]]},
                            "followup_queries": [{"aspect_id": aspects[0], "query": "FDA certification korean dessert US"},
                                                 {"aspect_id": aspects[0], "query": "site:fda.gov import rules"}]}
        return out
    if "자료 스크랩을 돕는 보조자" in p:
        docs = json.loads(p[p.index("[원문]") + 4:p.index("[원문 끝]")])
        sources = []
        for d in docs:
            qid = re.match(r"\[(Q\d)\]", d["title"]).group(1)
            sentence = d["text"].split("\n")[0].split(".")[0] + "."
            sources.append({"source_id": d["source_id"], "market": "country",
                            "quotes": [{"question": qid, "quote": sentence, "translation_ko": "번역"}]})
        return {"sources": sources}
    if "해외시장조사 보고서를 쓰는 애널리스트" in p:
        ids = re.findall(r'"id": "(E\d+)"', p)
        return {"conclusion": "요약 결론", "conclusion_ids": ids[:1],
                "points": [{"text": "핵심 사실", "quote_ids": ids[:1]}], "interpretation": "해석", "gaps": None}
    raise AssertionError(f"예상하지 못한 프롬프트: {p[:120]}")



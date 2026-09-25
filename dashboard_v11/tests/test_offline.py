"""네트워크 없이 v11 대시보드(4개 섹션 + Claude 마케팅 에이전트 부스 기획)와 화면을 검증하는 오프라인 테스트.

- 섹션 1: trend_usp_v1 테스트의 가짜 Google 트렌드·OpenAI 응답
- 섹션 2: j_test analyze_retail_market 결과 형식의 가짜 응답
- 섹션 3: tavily_v9 테스트의 가짜 Tavily·OpenAI 응답 (OpenAI 부스 기획은 돌지 않아야 함)
- 섹션 4: 가짜 Anthropic 클라이언트 (웹 검색 결과 블록·pause_turn·거절 흉내)
    python -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pipeline  # noqa: E402  (trend_usp_v1 → claude_booth·tavily_v9 순서로 불러옴)
import trend_adapter  # noqa: E402
import claude_booth  # noqa: E402


def _load_fakes(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trend_fakes = _load_fakes("trend_fakes", os.path.join(ROOT, "trend_usp_v1", "tests", "test_offline.py"))
tavily_fakes = _load_fakes("tavily_fakes", os.path.join(ROOT, "tavily_v9", "tests", "test_offline.py"))
# 위 테스트 모듈들이 자기 폴더를 sys.path 맨 앞에 넣으므로, 이 폴더의 app.py가 가려지지 않게 되돌린다
for d in (os.path.join(ROOT, "trend_usp_v1"), os.path.join(ROOT, "tavily_v9")):
    while d in sys.path[:sys.path.index(HERE) + 1]:
        sys.path.remove(d)
sys.modules.pop("app", None)

RETAIL_CALLS = []


def fake_retail(product_name, country, strengths, raw_materials, target_price):
    RETAIL_CALLS.append((product_name, country, strengths, raw_materials, target_price))
    return {
        "kw_seed": {},
        "target_product": {"title": "Sanbanto Noodle Kit (산반토 생면 키트)", "specs": "400g, 밀키트, 멸치 육수와 생면 포함",
                           "complaints": "육수가 너무 진하지 않다는 불만"},
        "retail_price": {"price": "4.2 ~ 8 MYR", "usd_price": "$1 ~ $1.8 USD", "krw_price": "약 1,350 ~ 2,430원",
                         "badge": "타깃 세그먼트 추정가", "badge_desc": "입력 가격 기준 ±15% 역산", "unit_price": ""},
        "sales_channels": {"channels": ["lazada.com.my", "shopee.com.my"], "shelf": "밀키트 코너 인근 냉장 매대"},
        "price_strategy": {"pitch": "진한 멸치 육수와 부드러운 생면", "positioning": "현지 물가 대비 프리미엄/기능성 타깃 포지셔닝"},
        "booth_solution": {"main_slogan": "j_test 부스 슬로건 (v11에서는 쓰지 않음)"},
    }


FORM = {"name": "약과", "country": "미국", "strengths": "손에 안 묻는 식감", "ingredients": "밀가루, 꿀",
        "certifications": "HACCP", "price": "200g 소매가 6~7달러", "exhibition_name": "Summer Fancy Food Show 2027",
        "exhibition_website": ""}

# ---------------------------------------------------------------------------
# 가짜 Anthropic 클라이언트
# ---------------------------------------------------------------------------

URL_OK = "https://www.hmart.com/yakgwa"
URL_FAKE = "https://example.com/not-searched"

COMPETITIVE = {
    "market_snapshot": "미국에서 약과는 K-디저트로 한인 마트를 넘어 일반 유통으로 확산 중.",
    "notes": [
        {"id": "R1", "topic": "competitor", "text": "H Mart에서 Samlip Yakgwa가 8.99달러에 판매된다.",
         "source_url": URL_OK, "source_title": "H Mart"},
        {"id": "R2", "topic": "consumer", "text": "Z세대가 틱톡에서 약과를 '할매니얼' 간식으로 소개한다.",
         "source_url": URL_FAKE, "source_title": ""},
        {"id": "R3", "topic": "exhibition", "text": "Summer Fancy Food Show는 스페셜티 리테일 바이어가 많다.",
         "source_url": "", "source_title": ""},
    ],
    "competitors": [
        {"name": "Samlip Yakgwa", "owner": "SPC Samlip", "type": "direct", "price": "$8.99 / 400g",
         "channels": "H Mart, Amazon", "positioning": "대용량 가성비 약과", "key_message": "Traditional Korean Honey Cookie",
         "strengths": "인지도", "weaknesses": "손에 끈적임이 남는다는 리뷰", "basis": ["R1"]},
        {"name": "Biscoff", "owner": "Lotus", "type": "indirect", "price": "$3.99", "channels": "월마트",
         "positioning": "커피 곁들임 쿠키", "key_message": "", "strengths": "", "weaknesses": "", "basis": []},
    ],
    "common_claims": ["Traditional", "Authentic Korean"],
    "white_space": {"text": "손에 안 묻는 프리미엄 한입 약과", "why": "경쟁 제품 리뷰에 끈적임 불만이 반복된다.",
                    "basis": ["R1", "기업:강점"]},
    "our_edge": [{"text": "손에 안 묻는 식감", "against": "Samlip의 끈적임", "basis": ["기업:강점"]}],
    "objections": [{"objection": "유통기한이 짧지 않나?", "answer": "상온 6개월 (확인 필요)", "basis": []}],
}

PLAN = {"brief": {"insights": [{"fact": "끈적임 불만", "insight": "깔끔하게 먹고 싶다", "implication": "손 닦는 연출 제거",
                                "basis": ["R1"]}],
                  "target_buyers": [{"priority": 1, "type": "스페셜티 리테일", "job": "차별 스토리"}],
                  "big_idea": {"line_en": "Honey Without the Mess", "line_ko": "손에 안 묻는 꿀과자", "why": "빈틈",
                               "basis": ["R1", "기업:강점"]},
                  "rtb": [{"text": "HACCP", "basis": ["기업:인증"]}]},
        "plan": {"summary": "초안 요약", "positioning": {"target_buyer": "스페셜티 리테일", "core_message": "No sticky fingers"},
                 "main_visual": {"concept_en": "Clean Hands, Golden Honey", "concept_ko": "깨끗한 손, 황금 꿀",
                                 "bullets": [{"text": "흰 장갑 비주얼", "basis": ["R2"]}]},
                 "slogan": {"main_en": "Honey Without the Mess", "main_ko": "손에 안 묻는 꿀과자",
                            "bullets": [{"text": "빈틈을 그대로 약속", "basis": ["기업:강점"]}]},
                 "signature_pairing": {"item": "Cold brew", "bullets": ["콜드브루와 페어링"]},
                 "demonstration": {"title": "흰 장갑 시식", "bullets": [{"text": "흰 장갑 끼고 시식", "basis": ["기획"]}]},
                 "packaging": {"direction": "개별 포장", "bullets": []},
                 "merchandising": {"zones": [{"name": "시식존", "position": "통로 앞", "purpose": "멈춤", "basis": []}],
                                   "bullets": []},
                 "visitor_flow": {"3s": "흰 장갑", "30s": "시식", "3min": "상담"},
                 "kpis": ["샘플 요청 30건"], "risks": [], "questions": ["상온 유통기한?"]}}
REVIEW = {"scores": {"insight": {"score": 4, "reason": "좋음"}, "single_minded": {"score": 5, "reason": ""},
                     "buyer_value": {"score": 3, "reason": "가격 정보 부족"}, "specificity": {"score": 4, "reason": ""},
                     "distinctiveness": {"score": 5, "reason": ""}, "feasibility": {"score": 4, "reason": ""}},
          "overall": "차별성은 좋으나 바이어 정보 부족", "comments": [{"section": "merchandising", "issue": "가격표 없음",
                                                            "suggestion": "케이스 단가 표시"}]}
REVISED = {**PLAN["plan"], "summary": "최종 요약 (수정본)", "applied": ["케이스 단가 표시"]}


def msg(content, stop_reason="end_turn", model="claude-opus-5"):
    return SimpleNamespace(content=content, stop_reason=stop_reason, model=model, stop_details=None,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=10,
                                                 cache_creation_input_tokens=0,
                                                 server_tool_use=SimpleNamespace(web_search_requests=2)))


def text(s):
    return SimpleNamespace(type="text", text=s, citations=None)


def research_messages():
    """웹 검색 조사: 1차 응답은 pause_turn으로 멈추고, 이어서 JSON 최종 답변."""
    first = msg([SimpleNamespace(type="thinking", thinking=""), text("검색해 보겠습니다 {잡음}"),
                 SimpleNamespace(type="server_tool_use", id="s1", name="web_search", input={"query": "yakgwa price"}),
                 SimpleNamespace(type="web_search_tool_result", tool_use_id="s1",
                                 content=[SimpleNamespace(type="web_search_result", url=URL_OK, title="H Mart Yakgwa")])],
                stop_reason="pause_turn")
    second = msg([SimpleNamespace(type="web_search_tool_result", tool_use_id="s2",
                                  content=SimpleNamespace(type="web_search_tool_result_error", error_code="max_uses_exceeded")),
                  text("```json\n" + json.dumps(COMPETITIVE, ensure_ascii=False) + "\n```")])
    return [first, second]


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    def stream(self, **kwargs):
        self.owner.calls.append(kwargs)
        system = kwargs["system"][0]["text"]
        user = kwargs["messages"][0]["content"]
        if kwargs.get("tools"):
            if self.owner.fail_web:
                raise RuntimeError("web search not enabled")
            step = "research"
            queue = self.owner.research_queue
            if not queue:
                queue.extend(research_messages())
            reply = queue.pop(0)
        elif "경쟁 브리프) 1~5단계" in user:
            step, reply = "knowledge", msg([text(json.dumps({**COMPETITIVE, "notes": COMPETITIVE["notes"][:2]},
                                                            ensure_ascii=False))])
        elif "포지셔닝 빈틈을 빅 아이디어로" in user:
            step = "plan"
            if self.owner.refuse:
                reply = msg([], stop_reason="refusal")
            else:
                reply = msg([text(json.dumps(PLAN, ensure_ascii=False))])
        elif "# 채점표" in system:
            step, reply = "review", msg([text(json.dumps(REVIEW, ensure_ascii=False))])
        elif "채점표로 평가되었습니다" in user:
            step, reply = "revise", msg([text(json.dumps(REVISED, ensure_ascii=False))])
        else:
            raise AssertionError(f"알 수 없는 호출: {user[:80]}")
        self.owner.steps.append(step)
        return FakeStream(reply)


class FakeAnthropic:
    def __init__(self, fail_web=False, refuse=False):
        self.calls, self.steps, self.research_queue = [], [], []
        self.fail_web, self.refuse = fail_web, refuse
        self.beta = SimpleNamespace(messages=FakeMessages(self))


BOOTH_INPUTS = {**FORM, "country_en": "United States"}


class ClaudeBoothTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "booth.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_flow_request_shape_and_result(self):
        fake = FakeAnthropic()
        b = claude_booth.plan_booth(BOOTH_INPUTS, db_path=self.db, client=fake)
        # 경쟁 브리프(웹 검색, pause_turn 1회 이어서) → 초안 → 채점 → 수정(3점 항목)
        self.assertEqual(fake.steps, ["research", "research", "plan", "review", "revise"])
        first = fake.calls[0]
        self.assertEqual(first["model"], "claude-opus-5")
        self.assertEqual(first["thinking"], {"type": "adaptive"})
        self.assertEqual(first["output_config"], {"effort": "high"})
        self.assertEqual(first["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(first["fallbacks"], "default")
        self.assertEqual(first["system"][0]["cache_control"], {"type": "ephemeral"})
        tool = first["tools"][0]
        self.assertEqual((tool["type"], tool["name"]), ("web_search_20260209", "web_search"))
        self.assertEqual(tool["user_location"], {"type": "approximate", "country": "US"})
        self.assertIn("competitive-brief", first["system"][0]["text"])          # 마케팅 에이전트 스킬 문서
        # pause_turn 뒤에는 지금까지의 답변을 assistant로 돌려준다 (추가 user 메시지 없음)
        resumed = fake.calls[1]["messages"]
        self.assertEqual([m["role"] for m in resumed], ["user", "assistant"])
        self.assertEqual(fake.calls[3]["output_config"], {"effort": "medium"})    # 채점
        self.assertIn("박람회 부스 컨셉 기획 스킬", fake.calls[2]["system"][0]["text"])  # booth_marketing 스킬

        self.assertEqual(b["source_mode"], "claude_marketing_agent")
        self.assertEqual(b["stage"], "revised")
        self.assertEqual(b["summary"], "최종 요약 (수정본)")
        self.assertEqual(b["applied"], ["케이스 단가 표시"])
        notes = {n["id"]: n["source_status"] for n in b["research"]["notes"]}
        self.assertEqual(notes, {"R1": "웹 출처", "R2": "출처 미확인", "R3": "AI 지식"})
        self.assertEqual(b["research"]["method"], "web_search")
        self.assertEqual(b["research"]["search_errors"], ["max_uses_exceeded"])
        cp = b["competitive"]
        self.assertEqual(cp["competitors"][0]["quote_ids"], ["R1"])
        self.assertEqual(cp["competitors"][1]["type_label"], "간접 경쟁")
        self.assertEqual(cp["white_space"]["company"], ["강점"])
        self.assertEqual(b["brief"]["big_idea"]["line_en"], "Honey Without the Mess")
        self.assertEqual(b["sections"]["main_visual"]["bullets"][0]["quote_ids"], ["R2"])
        self.assertTrue(b["sections"]["demonstration"]["bullets"][0]["is_idea"])
        self.assertEqual(b["usage"]["web_search_requests"], 10)
        self.assertFalse(b["from_cache"])

        # 같은 입력은 저장된 결과를 쓴다
        again = claude_booth.plan_booth(BOOTH_INPUTS, db_path=self.db, client=FakeAnthropic())
        self.assertTrue(again["from_cache"])
        self.assertEqual(again["summary"], b["summary"])

    def test_web_search_failure_falls_back_to_knowledge(self):
        fake = FakeAnthropic(fail_web=True)
        b = claude_booth.plan_booth(BOOTH_INPUTS, db_path=self.db, client=fake)
        self.assertEqual(fake.steps[0], "knowledge")
        self.assertEqual(b["research"]["method"], "knowledge")
        self.assertIn("web search not enabled", b["research"]["error"])
        self.assertTrue(all(n["source_status"] == "AI 지식" for n in b["research"]["notes"]))

    def test_refusal_raises(self):
        with self.assertRaises(claude_booth.ClaudeRefusal):
            claude_booth.plan_booth(BOOTH_INPUTS, db_path=self.db, client=FakeAnthropic(refuse=True))

    def test_missing_key(self):
        with mock.patch.object(claude_booth, "load_env"), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                claude_booth.get_client()

    def test_agent_skill_folder_swap(self):
        skill = claude_booth.load_agent_skill("없는_스킬")
        self.assertEqual(skill["folder"], "competitive_brief")
        self.assertTrue(skill["warnings"])


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        trend_fakes.FakeTrends.fail_related = False
        trend_fakes.FakeTrends.fail_iot = False
        trend_fakes.FakeTrends.sparse = False
        tavily_fakes.BOOTH_CALLS.clear()
        tavily_fakes.RESEARCH_CALLS.clear()
        RETAIL_CALLS.clear()
        self.claude = FakeAnthropic()
        research = pipeline.tavily_research
        self.run_research = mock.MagicMock(side_effect=research.run_research)
        self.patches = [
            # 섹션 1
            mock.patch.object(trend_adapter.trend_usp, "_chat_json", side_effect=trend_fakes.fake_chat_json),
            mock.patch.object(trend_adapter.trend_usp, "TrendsClient", trend_fakes.FakeTrends),
            # 섹션 2
            mock.patch.object(trend_adapter, "_retail", return_value=SimpleNamespace(analyze_retail_market=fake_retail)),
            # 섹션 3
            mock.patch.object(research, "get_clients", return_value=(tavily_fakes.FakeOpenAI(), tavily_fakes.FakeTavily())),
            mock.patch.object(research, "_ask_json", side_effect=tavily_fakes.fake_ask_json),
            mock.patch.object(research, "domain_exists", side_effect=lambda d: True),
            mock.patch.object(pipeline, "RESEARCH_DB_PATH", os.path.join(self.tmp.name, "c.db")),
            mock.patch.object(research, "run_research", self.run_research),
            # 섹션 4
            mock.patch.object(claude_booth, "get_client", return_value=self.claude),
            mock.patch.object(claude_booth, "DEFAULT_DB_PATH", os.path.join(self.tmp.name, "b.db")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_all_sections(self):
        d = pipeline.run_dashboard(FORM)
        for k in ("section1_error", "section2_error", "research_error", "booth_error"):
            self.assertIsNone(d[k], k)
        self.assertEqual([c["key"] for c in d["section1"]["clusters"]],
                         ["culture_trigger", "intent_funnel", "category_perception", "consumption_habit"])
        self.assertEqual(RETAIL_CALLS[0][1], "미국")
        self.assertNotIn("booth_solution", d["section2"])
        # 섹션 3: Tavily 조사만, tavily_v9 안의 OpenAI 부스 기획은 돌지 않음
        self.assertEqual(self.run_research.call_args.args[1], "United States")
        self.assertIsNone(d["research"]["booth"])
        self.assertEqual(tavily_fakes.BOOTH_CALLS, [])
        self.assertEqual(tavily_fakes.RESEARCH_CALLS, [])
        # 섹션 4: Claude 마케팅 에이전트 (Tavily 결과를 받지 않음)
        self.assertEqual(d["booth"]["source_mode"], "claude_marketing_agent")
        self.assertNotIn("E1", json.dumps(self.claude.calls[2]["messages"], ensure_ascii=False))
        self.assertEqual(set(d["view"]["articles"]), {"Q1", "Q2", "Q3", "Q4"})

    def test_booth_failure_isolated(self):
        self.claude.refuse = True
        d = pipeline.run_dashboard(FORM)
        self.assertIsNone(d["booth"])
        self.assertIn("Claude가 요청을 처리하지 않았습니다", d["booth_error"])
        self.assertIsNotNone(d["research"])
        self.assertIsNotNone(d["section1"])

    def test_research_failure_isolated(self):
        self.run_research.side_effect = RuntimeError("tavily down")
        d = pipeline.run_dashboard(FORM)
        self.assertIsNone(d["research"])
        self.assertIn("tavily down", d["research_error"])
        self.assertIsNotNone(d["booth"])            # 부스 기획은 Tavily와 무관하게 나옴

    def test_missing_inputs(self):
        with self.assertRaises(ValueError):
            pipeline.run_dashboard({"name": "", "country": "미국"})

    def test_render_dashboard(self):
        import app as web
        self.assertTrue(web.__file__.startswith(HERE))
        self.assertEqual(web.PORT, 5066)
        html = web.app.test_client().post("/", data=FORM).get_data(as_text=True)
        for s in ["● 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링", "CULTURE TRIGGER",
                  "● 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석", "Sanbanto Noodle Kit",
                  "● 3. 현지 웹 자료 조사 요약", "TRADE SHOW &amp; BOOTH", 'data-tab="Q1" data-target="E1"', 'id="art-E1"',
                  "● 4. 부스 컨셉 기획", "Claude 마케팅 에이전트", "① 경쟁 브리프", "④ 수정",
                  "COMPETITIVE BRIEF", "Samlip Yakgwa", "간접 경쟁", "WHITE SPACE", "손에 안 묻는 프리미엄 한입 약과",
                  "경쟁사가 다 하는 말", "바이어 반론 대응", "BIG IDEA", "Honey Without the Mess", "MAIN VISUAL", "VISITOR FLOW",
                  'data-tab="memo" data-target="R1"', 'id="art-R1"', "Claude 조사 메모 (3)", "웹 출처", "출처 미확인",
                  "claude-opus-5 (effort high)", "웹 검색 10회"]:
            self.assertIn(s, html, s)
        self.assertNotIn("OpenAI 단독 기획", html)
        self.assertNotIn("j_test 부스 슬로건", html)
        self.assertEqual(web.app.test_client().get("/").status_code, 200)

    def test_render_without_research_keeps_memo_drawer(self):
        import app as web
        self.run_research.side_effect = RuntimeError("tavily down")
        with mock.patch.object(pipeline, "run_section2", side_effect=RuntimeError("retail down")):
            html = web.app.test_client().post("/", data=FORM).get_data(as_text=True)
        self.assertIn("리테일 벤치마킹을 불러오지 못했습니다. retail down", html)
        self.assertIn("웹 자료 조사를 불러오지 못했습니다. tavily down", html)
        self.assertIn('id="drawer"', html)                   # 부스 조사 메모가 있으면 사이드바 유지
        self.assertIn("Claude 조사 메모 (3)", html)
        self.assertNotIn('data-panel="Q1"', html)

    def test_render_booth_failure(self):
        import app as web
        self.claude.refuse = True
        html = web.app.test_client().post("/", data=FORM).get_data(as_text=True)
        self.assertIn("부스 컨셉을 만들지 못했습니다. Claude가 요청을 처리하지 않았습니다", html)


class UnitTest(unittest.TestCase):
    def test_korean_country(self):
        self.assertEqual(trend_adapter.korean_country("Malaysia"), "말레이시아")
        self.assertEqual(trend_adapter.korean_country("USA"), "미국")

    def test_required_keys_include_anthropic(self):
        self.assertIn("ANTHROPIC_API_KEY", pipeline.tavily_env.REQUIRED_KEYS)

    def test_real_client_uses_safe_headers(self):
        with mock.patch.object(claude_booth, "load_env"), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
            client = claude_booth.get_client()
        self.assertEqual(client._custom_headers.get("Accept-Encoding"), "gzip, deflate")


if __name__ == "__main__":
    unittest.main()

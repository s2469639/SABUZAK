"""네트워크 없이 v10 대시보드(4개 섹션 결합)와 화면을 검증하는 오프라인 테스트.

- 섹션 1: trend_usp_v1 테스트의 가짜 Google 트렌드·OpenAI 응답
- 섹션 2: j_test analyze_retail_market 결과 형식의 가짜 응답
- 섹션 3·4: tavily_v9 테스트의 가짜 Tavily·OpenAI 응답
    python -m unittest discover -s tests -v
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import pipeline  # noqa: E402  (trend_usp_v1 → tavily_v9 순서로 불러옴)
import trend_adapter  # noqa: E402


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
        "booth_solution": {"main_slogan": "j_test 부스 슬로건 (v10에서는 쓰지 않음)"},
    }


FORM = {"name": "약과", "country": "미국", "strengths": "손에 안 묻는 식감", "ingredients": "밀가루, 꿀",
        "certifications": "HACCP", "price": "200g 소매가 6~7달러", "exhibition_name": "Summer Fancy Food Show 2027",
        "exhibition_website": ""}


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        trend_fakes.FakeTrends.fail_related = False
        trend_fakes.FakeTrends.fail_iot = False
        trend_fakes.FakeTrends.sparse = False
        tavily_fakes.BOOTH_CALLS.clear()
        tavily_fakes.RESEARCH_CALLS.clear()
        RETAIL_CALLS.clear()
        research = pipeline.tavily_research
        self.run_research = mock.MagicMock(side_effect=research.run_research)
        self.patches = [
            # 섹션 1
            mock.patch.object(trend_adapter.trend_usp, "_chat_json", side_effect=trend_fakes.fake_chat_json),
            mock.patch.object(trend_adapter.trend_usp, "TrendsClient", trend_fakes.FakeTrends),
            # 섹션 2
            mock.patch.object(trend_adapter, "_retail", return_value=SimpleNamespace(analyze_retail_market=fake_retail)),
            # 섹션 3·4
            mock.patch.object(research, "get_clients", return_value=(tavily_fakes.FakeOpenAI(), tavily_fakes.FakeTavily())),
            mock.patch.object(research, "_ask_json", side_effect=tavily_fakes.fake_ask_json),
            mock.patch.object(research, "domain_exists", side_effect=lambda d: True),
            mock.patch.object(research, "DEFAULT_DB_PATH", os.path.join(self.tmp.name, "c.db")),
            mock.patch.object(research, "run_research", self.run_research),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_all_sections_and_country_conversion(self):
        d = pipeline.run_dashboard(FORM)
        self.assertIsNone(d["section1_error"])
        self.assertIsNone(d["section2_error"])
        self.assertIsNone(d["research_error"])
        # 섹션 1: 클러스터 4개, 탐색 검증 검색어 포함
        self.assertEqual([c["key"] for c in d["section1"]["clusters"]],
                         ["culture_trigger", "intent_funnel", "category_perception", "consumption_habit"])
        self.assertEqual(d["section1"]["geo"], "US")
        # 섹션 2: j_test에는 한국어 국가명, 부스 제안은 제거
        self.assertEqual(RETAIL_CALLS[0][1], "미국")
        self.assertEqual(RETAIL_CALLS[0][3], "밀가루, 꿀")
        self.assertNotIn("booth_solution", d["section2"])
        # 섹션 3·4: Tavily 조사에는 영문 국가명, 부스는 OpenAI 자체 조사
        self.assertEqual(self.run_research.call_args.args[1], "United States")
        self.assertEqual(self.run_research.call_args.kwargs["company_profile"]["price_range"], FORM["price"])
        self.assertEqual(d["research"]["booth"]["source_mode"], "openai_self_research")
        self.assertEqual(set(d["view"]["articles"]), {"Q1", "Q2", "Q3", "Q4"})
        self.assertTrue(all("url" in a for a in d["view"]["articles"]["Q1"]))

    def test_english_country_input(self):
        pipeline.run_dashboard({**FORM, "country": "Malaysia"})
        self.assertEqual(RETAIL_CALLS[0][1], "말레이시아")
        self.assertEqual(self.run_research.call_args.args[1], "Malaysia")

    def test_section_failure_isolated(self):
        with mock.patch.object(trend_adapter, "_retail", side_effect=RuntimeError("retail down")), \
             mock.patch.object(pipeline, "run_section2", side_effect=RuntimeError("retail down")):
            d = pipeline.run_dashboard(FORM)
        self.assertIsNone(d["section2"])
        self.assertIn("retail down", d["section2_error"])
        self.assertIsNotNone(d["section1"])
        self.assertIsNotNone(d["research"])

    def test_research_failure_isolated(self):
        self.run_research.side_effect = RuntimeError("tavily down")
        d = pipeline.run_dashboard(FORM)
        self.assertIsNone(d["research"])
        self.assertIsNone(d["view"])
        self.assertIn("tavily down", d["research_error"])
        self.assertIsNotNone(d["section1"])

    def test_missing_inputs(self):
        with self.assertRaises(ValueError):
            pipeline.run_dashboard({"name": "", "country": "미국"})

    def test_render_dashboard(self):
        import app as web
        self.assertTrue(web.__file__.startswith(HERE))
        html = web.app.test_client().post("/", data=FORM).get_data(as_text=True)
        for text in ["● 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링", "CULTURE TRIGGER", "kdrama yakgwa",
                     "● 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석", "Sanbanto Noodle Kit", "4.2 ~ 8 MYR",
                     "타깃 세그먼트 추정가", "lazada.com.my",
                     "● 3. 현지 웹 자료 조사 요약", "CONSUMER", "TRADE SHOW &amp; BOOTH", "기사 2건 보기 →",
                     'data-tab="Q1" data-target="E1"', 'id="art-E1"', "원문 열기",
                     "● 4. 부스 컨셉 기획", "OpenAI 단독 기획", "BIG IDEA", "MAIN VISUAL", "VISITOR FLOW",
                     'data-tab="memo" data-target="R2"', 'id="art-R2"', "OpenAI 조사 메모 (4)", "Bibigo mandu"]:
            self.assertIn(text, html, text)
        self.assertNotIn("j_test 부스 슬로건", html)          # j_test booth_solution은 표시하지 않음
        self.assertEqual(web.app.test_client().get("/").status_code, 200)

    def test_render_with_failed_sections(self):
        import app as web
        self.run_research.side_effect = RuntimeError("tavily down")
        with mock.patch.object(pipeline, "run_section2", side_effect=RuntimeError("retail down")):
            html = web.app.test_client().post("/", data=FORM).get_data(as_text=True)
        self.assertIn("리테일 벤치마킹을 불러오지 못했습니다. retail down", html)
        self.assertIn("웹 자료 조사를 불러오지 못했습니다. tavily down", html)
        self.assertIn("부스 컨셉을 만들지 못했습니다", html)
        self.assertNotIn('id="drawer"', html)                # 조사 결과가 없으면 사이드바도 없음
        self.assertIn("CULTURE TRIGGER", html)


class UnitTest(unittest.TestCase):
    def test_korean_country(self):
        self.assertEqual(trend_adapter.korean_country("Malaysia"), "말레이시아")
        self.assertEqual(trend_adapter.korean_country("USA"), "미국")
        self.assertEqual(trend_adapter.korean_country("말레이시아"), "말레이시아")
        self.assertEqual(trend_adapter.korean_country("Peru"), "페루")
        self.assertEqual(trend_adapter.korean_country("Atlantis"), "Atlantis")

    def test_real_j_test_module_loads_with_safe_client(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "x", "TAVILY_API_KEY": "y"}):
            trend_adapter._retail_module = None
            module = trend_adapter._retail()
        self.assertTrue(module.__file__.endswith(os.path.join("j_test", "retail_research.py")))
        self.assertEqual(module.openai_client._custom_headers.get("Accept-Encoding"), "gzip, deflate")


if __name__ == "__main__":
    unittest.main()

"""네트워크 없이 v12 대시보드(4개 섹션 + 진행률 + 화면)를 검증하는 오프라인 테스트.
    cd v12 && python -m unittest discover -s tests -v
"""

import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx
import openai

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: E402
import model_upgrade  # noqa: E402
import pipeline  # noqa: E402
import research  # noqa: E402
import retail_research  # noqa: E402
import sections  # noqa: E402
import trend_usp  # noqa: E402

FORM = {"name": "약과", "country": "미국", "strengths": "손에 안 묻는 식감", "ingredients": "밀가루, 꿀",
        "certifications": "HACCP", "price": "200g 소매가 6~7달러", "exhibition_name": "Summer Fancy Food Show 2027",
        "exhibition_website": ""}


# ---------------------------------------------------------------------------
# 섹션 2용 가짜 OpenAI·Tavily
# ---------------------------------------------------------------------------

ANALYSIS = {"primary_category": "디저트", "kw3": "Samlip Yakgwa", "retail_domains": ["hmart.com", "wegmans.com"],
            "category_anchors": "yakgwa", "negative_anchors": "", "min_price": 6.0, "max_price": 7.0,
            "currency_symbol": "USD", "competitor_product": "Samlip Yakgwa (삼립 약과)", "competitor_specs": "400g",
            "consumer_complaints": "손에 끈적임", "shelf_location": "Asian Snack Aisle", "value_pitch": "개별 포장 한입 약과",
            "booth_solution": {"main_slogan": "쓰지 않는 부스 제안"}}


class RetailFake:
    """mode: tavily(가격 찾음) / web(Tavily 실패 → 웹 검색 성공) / uncited(웹 검색 URL이 인용에 없음) / none"""

    def __init__(self, mode):
        self.mode, self.web_calls = mode, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.responses = SimpleNamespace(create=self._web)

    def _chat(self, **kw):
        prompt = kw["messages"][0]["content"]
        if "검색 텍스트에서" in prompt:
            data = {"is_valid": True, "price_range": "8.99 USD (400g)"} if self.mode == "tavily" else {"is_valid": False}
        else:
            data = ANALYSIS
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(data)))])

    def _web(self, **kw):
        self.web_calls.append(kw)
        if self.mode == "none":
            body = {"found": False}
        else:
            body = {"found": True, "price_range": "$7.49 ~ $9.99 (400g)", "source_urls": ["https://www.hmart.com/yakgwa"]}
        cited = "https://www.hmart.com/yakgwa" if self.mode == "web" else "https://other.example.com"
        ann = SimpleNamespace(type="url_citation", url=cited, title="H Mart Yakgwa")
        return SimpleNamespace(output_text=json.dumps(body),
                               output=[SimpleNamespace(content=[SimpleNamespace(annotations=[ann])])])


class RetailTavily:
    def __init__(self, found=True):
        self.found = found

    def search(self, **kw):
        return {"results": [{"content": "Samlip Yakgwa $8.99", "url": "https://www.hmart.com/p/1", "title": "H Mart"}]
                if self.found else []}


def fake_ask_json(client, prompt, temperature=0.0, model=None, system=None):
    out = fakes.fake_ask_json(client, prompt, temperature, model, system)
    if "해외시장조사 보고서를 쓰는 애널리스트" in prompt:   # 화면 확인용: 확인 필요 문구, 'AI 해석:' 접두어
        out = {**out, "gaps": "가격 비교 자료 부족", "interpretation": "AI 해석: 시식 연출이 유효"}
    return out


class Base(unittest.TestCase):
    retail_mode = "tavily"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fakes.FakeTrends.fail_related = False
        fakes.FakeTrends.fail_iot = False
        fakes.FakeTrends.sparse = False
        fakes.BOOTH_CALLS.clear()
        fakes.RESEARCH_CALLS.clear()
        self.retail = RetailFake(self.retail_mode)
        self.patches = [
            mock.patch.object(trend_usp, "_chat_json", side_effect=fakes.fake_chat_json),
            mock.patch.object(trend_usp, "TrendsClient", fakes.FakeTrends),
            mock.patch.object(retail_research, "get_clients",
                              return_value=(self.retail, RetailTavily(found=self.retail_mode == "tavily"))),
            mock.patch.object(research, "get_clients", return_value=(fakes.FakeOpenAI(), fakes.FakeTavily())),
            mock.patch.object(research, "_ask_json", side_effect=fake_ask_json),
            mock.patch.object(research, "domain_exists", side_effect=lambda d: True),
            mock.patch.object(pipeline, "CACHE_DB_PATH", os.path.join(self.tmp.name, "cache.db")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class DashboardTest(Base):
    def test_all_sections_and_progress(self):
        progress = pipeline.Progress()
        d = pipeline.run_dashboard(FORM, progress=progress)
        for k in ("section1_error", "section2_error", "research_error", "booth_error"):
            self.assertIsNone(d[k], (k, d[k]))
        self.assertEqual([c["key"] for c in d["section1"]["clusters"]],
                         ["culture_trigger", "intent_funnel", "category_perception", "consumption_habit"])
        self.assertEqual(d["section1"]["buyer_language"], "English")
        self.assertNotIn("booth_solution", d["section2"])
        # 섹션 3에서는 부스를 만들지 않고, 섹션 4가 따로 만든다 (OpenAI 자체 조사 1회 + 기획 단계)
        self.assertIsNone(d["research"]["booth"])
        self.assertEqual(d["booth"]["source_mode"], "openai_self_research")
        self.assertEqual(len(fakes.RESEARCH_CALLS), 1)
        self.assertEqual(d["models"]["booth"], "gpt-6-astra")
        snap = progress.snapshot()
        self.assertEqual(snap["percent"], 100)
        self.assertTrue(all(s["done"] and not s["failed"] for s in snap["sections"]))
        # 단계 수가 진행률 설정과 맞는지 (단계를 추가하면 SECTIONS의 단계 수도 맞춰야 함)
        for key, s in progress.sections.items():
            self.assertLessEqual(s["started"], s["total"], key)
            self.assertGreaterEqual(s["started"], s["total"] - 1, key)

        # 부스는 저장해 두고 다시 쓴다
        n_calls = len(fakes.BOOTH_CALLS)
        again = pipeline.run_dashboard(FORM)
        self.assertTrue(again["booth"]["from_cache"])
        self.assertEqual(len(fakes.BOOTH_CALLS), n_calls)

    def test_section_failure_isolated(self):
        with mock.patch.object(research, "run_research", side_effect=RuntimeError("tavily down")):
            progress = pipeline.Progress()
            d = pipeline.run_dashboard(FORM, progress=progress)
        self.assertIn("tavily down", d["research_error"])
        self.assertIsNotNone(d["booth"])
        self.assertIsNotNone(d["section1"])
        self.assertEqual(progress.percent(), 100)
        self.assertTrue(next(s for s in progress.snapshot()["sections"] if s["key"] == "research")["failed"])

    def test_missing_inputs(self):
        with self.assertRaises(ValueError):
            pipeline.run_dashboard({"name": "", "country": "미국"})


class ProgressTest(unittest.TestCase):
    def test_percent_counts_finished_steps(self):
        p = pipeline.Progress()
        self.assertEqual(p.percent(), 0)
        report = p.reporter("trend")          # 비중 20, 6단계
        report("a")
        self.assertEqual(p.percent(), 0)      # 첫 단계 시작 = 아직 끝난 단계 없음
        report("b")
        report("c")
        self.assertEqual(p.percent(), int(20 * 2 / 6))
        self.assertIn("검색어 트렌드 · c", p.snapshot()["message"])
        p.finish("trend")
        self.assertEqual(p.percent(), 20)


class RetailPriceTest(Base):
    def price(self):
        return sections.run_section2({**FORM, "country_en": "United States"})["retail_price"]


class TavilyPrice(RetailPriceTest):
    retail_mode = "tavily"

    def test_tavily_price(self):
        rp = self.price()
        self.assertEqual((rp["method"], rp["badge"]), ("tavily", "실측가 (Tavily)"))
        self.assertEqual(rp["price"], "8.99 USD (400g)")
        self.assertEqual(rp["usd_price"], "$9 USD")
        self.assertEqual(self.retail.web_calls, [])          # 찾았으면 웹 검색은 하지 않음


class WebPrice(RetailPriceTest):
    retail_mode = "web"

    def test_openai_web_price(self):
        rp = self.price()
        self.assertEqual((rp["method"], rp["badge"]), ("openai_web", "AI 웹 검색가"))
        self.assertEqual(rp["sources"], [{"url": "https://www.hmart.com/yakgwa", "title": "H Mart Yakgwa"}])
        self.assertEqual(rp["usd_price"], "$7.5 ~ $10 USD")
        self.assertEqual(self.retail.web_calls[0]["tools"], [{"type": "web_search"}])


class UncitedPrice(RetailPriceTest):
    retail_mode = "uncited"

    def test_uncited_web_price_falls_back_to_estimate(self):
        rp = self.price()
        self.assertEqual((rp["method"], rp["badge"]), ("estimate", "타깃 세그먼트 추정가"))
        self.assertEqual(rp["price"], "5.1 ~ 8 USD")


class AppTest(Base):
    def setUp(self):
        super().setUp()
        import app as web
        self.web = web
        self.client = web.app.test_client()

    def run_job(self):
        res = self.client.post("/start", data=FORM)
        self.assertEqual(res.status_code, 200)
        job_id = res.get_json()["job_id"]
        for _ in range(200):
            p = self.client.get(f"/progress/{job_id}").get_json()
            if p["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(p["status"], "done", p)
        self.assertEqual(p["percent"], 100)
        return self.client.get(f"/result/{job_id}").get_data(as_text=True)

    def test_job_flow_and_ui(self):
        html = self.run_job()
        for s in ["1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링", "대상 시장 <b>미국 (US)</b>", "검색 언어 <b>English",
                  "바이어 언어 <b>English</b>", 'class="lv-high"', "조회 <b>", '<span class="cluster-num">01</span>CULTURE TRIGGER',
                  '<span class="cluster-num">04</span>', 'class="cluster-grid"', 'class="callout"',
                  "2. 현지 리테일 벤치마킹", "실측가 (Tavily)", 'class="price-badge tavily"',
                  "3. 현지 시장 트렌드 분석", 'class="stat-pill"', "출처: <b>", "원문: <b>",
                  "자세히 보기", "⚠️ 확인 필요", "가격 비교 자료 부족", "<b>AI 해석</b> · 시식 연출이 유효",
                  'class="ref" type="button" data-tab="Q1" data-target="E1"', 'id="art-E1"',
                  "4. 부스 컨셉 기획", "OpenAI 단독 기획 · gpt-6-astra", "BIG IDEA", 'data-tab="memo"',
                  "박람회 준비부터 바이어 관리까지.", "페어메이트</span>와 함께", 'id="ring-bar"']:
            self.assertIn(s, html, s)
        for s in ["AI 추정</span>", "탐색 검증", "Tavily로", "3. 현지 웹 자료 조사 요약", "쓰지 않는 부스 제안",
                  "AI 해석 · AI 해석"]:
            self.assertNotIn(s, html, s)

    def test_start_validation_and_missing_job(self):
        res = self.client.post("/start", data={**FORM, "name": ""})
        self.assertEqual(res.status_code, 400)
        self.assertIn("제품명", res.get_json()["error"])
        self.assertEqual(self.client.get("/progress/nope").get_json()["status"], "missing")
        self.assertEqual(self.client.get("/result/nope").status_code, 404)

    def test_index_and_sync_fallback(self):
        self.assertIn("페어메이트", self.client.get("/").get_data(as_text=True))
        html = self.client.post("/", data=FORM).get_data(as_text=True)
        self.assertIn("3. 현지 시장 트렌드 분석", html)


class ModelUpgradeTest(unittest.TestCase):
    def setUp(self):
        model_upgrade._resolved.clear()
        model_upgrade._dropped.clear()

    tearDown = setUp

    def fake(self, missing=()):
        calls = []

        def create(**kw):
            calls.append(kw)
            if kw["model"] in missing:
                req = httpx.Request("POST", "https://api.openai.com/v1/x")
                raise openai.NotFoundError("no model", response=httpx.Response(404, request=req), body={})
            return SimpleNamespace(model=kw["model"])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                 responses=SimpleNamespace(create=create))
        return model_upgrade.wrap(client), calls

    def test_reasoning_params_and_fallback(self):
        client, calls = self.fake(missing={"gpt-6-astra"})
        client.chat.completions.create(model=model_upgrade.TASK_MODEL, temperature=0.3, messages=[])
        self.assertEqual(calls[0], {"model": "gpt-5.6-terra", "reasoning_effort": "low", "messages": []})
        r = client.chat.completions.create(model=model_upgrade.BOOTH_MODEL, temperature=0.6, messages=[])
        self.assertEqual(r.model, "gpt-5.6-sol")
        self.assertEqual(calls[-1]["reasoning_effort"], "medium")
        client.responses.create(model="gpt-6-astra", input="x")
        self.assertEqual(calls[-1]["model"], "gpt-5.6-sol")      # 한 번 대체되면 기억
        self.assertEqual(calls[-1]["reasoning"], {"effort": "medium"})


class LayoutTest(unittest.TestCase):
    def test_self_contained(self):
        """다른 폴더(trend_usp_v1, tavily_v9, j_test)를 불러오지 않는다."""
        for name in ("trend_usp", "research", "retail_research", "skill_loader", "env_setup", "http_compat"):
            self.assertTrue(sys.modules[name].__file__.startswith(HERE), name)
        self.assertTrue(research.ENV_PATH.endswith(".env"))


if __name__ == "__main__":
    unittest.main()

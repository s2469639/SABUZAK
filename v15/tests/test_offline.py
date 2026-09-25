"""네트워크 없이 v14(트렌드 조사 1~3번 · 부스 컨셉 4번 분리, 진행률, 화면)을 검증하는 오프라인 테스트.
    cd v14 && python -m unittest discover -s tests -v
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
import jobs  # noqa: E402
import services  # noqa: E402
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
            mock.patch.object(services, "CACHE_DB_PATH", os.path.join(self.tmp.name, "cache.db")),
            mock.patch.object(jobs, "RESULTS_DIR", os.path.join(self.tmp.name, "results")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


def check_steps(test, progress):
    """단계 수가 진행률 설정과 맞는지 (단계를 추가하면 services의 단계 수도 맞춰야 함)."""
    for key, s in progress.sections.items():
        test.assertLessEqual(s["started"], s["total"], key)
        test.assertGreaterEqual(s["started"], s["total"] - 1, key)


class TrendTest(Base):
    def test_trend_sections_only(self):
        progress = services.trend_progress()
        d = services.run_trend(FORM, progress=progress)
        for k in ("section1_error", "section2_error", "research_error"):
            self.assertIsNone(d[k], (k, d[k]))
        self.assertNotIn("booth", d)
        self.assertEqual([c["key"] for c in d["section1"]["clusters"]],
                         ["culture_trigger", "intent_funnel", "category_perception", "consumption_habit"])
        self.assertIsNone(d["research"]["booth"])       # 트렌드 조사에서는 부스를 만들지 않음
        self.assertEqual(fakes.BOOTH_CALLS, [])
        snap = progress.snapshot()
        self.assertEqual(snap["percent"], 100)
        self.assertEqual([c["name"] for c in snap["chips"]], ["검색 트렌드", "리테일 가격", "시장 자료"])
        self.assertTrue(all(c["done"] for c in snap["chips"]))
        check_steps(self, progress)

    def test_section_failure_isolated(self):
        with mock.patch.object(research, "run_research", side_effect=RuntimeError("tavily down")):
            progress = services.trend_progress()
            d = services.run_trend(FORM, progress=progress)
        self.assertIn("tavily down", d["research_error"])
        self.assertIsNotNone(d["section1"])
        self.assertEqual(progress.percent(), 100)
        self.assertTrue(next(c for c in progress.snapshot()["chips"] if c["name"] == "시장 자료")["failed"])

    def test_missing_inputs(self):
        with self.assertRaises(ValueError):
            services.run_trend({"name": "", "country": "미국"})


class BoothTest(Base):
    def test_booth_alone_and_cache(self):
        progress = services.booth_progress()
        d = services.run_booth(FORM, progress=progress)
        b = d["booth"]
        self.assertIsNone(d["booth_error"])
        self.assertEqual(b["source_mode"], "openai_self_research")
        self.assertEqual(len(fakes.RESEARCH_CALLS), 1)        # OpenAI 자체 조사
        self.assertEqual(b["key_actions"][0]["title"], "흰 장갑 시식으로 끈적임 없음 증명")
        self.assertNotIn("근거:", b["key_actions"][0]["detail"])           # 본문에 붙은 근거 표기는 떼어냄
        self.assertEqual(b["key_actions"][0]["quote_ids"], ["R2"])
        self.assertEqual(b["key_actions"][2]["title"], "케이스 단가표로 상담 전환")   # 예전 형식 호환
        self.assertEqual(b["kpis"][0]["target"], "80건")
        self.assertEqual(b["kpis"][1], {"metric": "샘플 요청 20건", "target": "", "how": ""})
        # 화면용 짧은 요약: 긴 문장만, 원문은 그대로
        self.assertTrue(b["short"]["action.0"].startswith("요약: "))
        self.assertIn("journey.3min.message", b["short"])
        self.assertNotIn("kpi.0", b["short"])                         # 80자 미만은 요약하지 않음
        self.assertEqual(b["visitor_flow"]["3min"]["headline"], "원페이저 상담")   # "3분:" 접두어 제거
        vf = b["visitor_flow"]
        self.assertEqual(vf["3s"]["props"], ["흰 장갑", "꿀 방울 백월"])
        self.assertEqual(vf["30s"]["headline"], "커피와 한입 시식")     # 예전 형식 호환
        self.assertEqual(vf["3min"]["staff"], ["케이스 단가·MOQ 안내"])
        snap = progress.snapshot()
        self.assertEqual(snap["percent"], 100)
        self.assertEqual([c["name"] for c in snap["chips"]], services.BOOTH_STAGE_CHIPS)
        self.assertTrue(all(c["done"] for c in snap["chips"]))
        check_steps(self, progress)
        n = len(fakes.BOOTH_CALLS)
        self.assertTrue(services.run_booth(FORM)["booth"]["from_cache"])
        self.assertEqual(len(fakes.BOOTH_CALLS), n)


class ProgressTest(unittest.TestCase):
    def test_friendly_messages_and_percent(self):
        p = services.trend_progress()
        self.assertEqual(p.percent(), 0)
        report = p.reporter("research")           # 비중 55, 10단계
        report("현지 검색어 준비")
        report("주요 사이트 검색 (Tavily)")
        snap = p.snapshot()
        self.assertEqual(snap["message"], "현지 시장 자료를 찾고 있어요")   # 도구 이름은 보이지 않음
        self.assertEqual(snap["percent"], int(55 * 1 / 10))
        p.finish("trend")
        self.assertEqual(p.percent(), 30 + int(55 * 1 / 10))

    def test_all_internal_labels_have_friendly_text(self):
        import inspect
        import re
        src = "".join(inspect.getsource(m) for m in (research, retail_research, sections))
        labels = set(re.findall(r'(?:step|progress)\("([^"]+)"', src))
        for a, b in re.findall(r'step\("([^"]+)" if [^\n]*? else "([^"]+)"\)', src):
            labels |= {a, b}
        missing = [x for x in labels if x not in jobs.FRIENDLY]
        self.assertEqual(missing, [])
        for text in jobs.FRIENDLY.values():
            for word in ("Tavily", "OpenAI", "Google", "pytrends", "API"):
                self.assertNotIn(word, text)

    def test_booth_stage_chips(self):
        p = services.booth_progress()
        r = p.reporter("booth")
        r("부스용 자체 웹 조사 (OpenAI)")
        r("전략 뼈대 (인사이트·빅 아이디어)")
        chips = p.snapshot()["chips"]
        self.assertEqual([(c["done"], c["active"]) for c in chips[:3]], [(True, False), (False, True), (False, False)])


class RetailPriceTest(Base):
    def price(self):
        return sections.run_section2({**FORM, "country_en": "United States"})["retail_price"]


class TavilyPrice(RetailPriceTest):
    retail_mode = "tavily"

    def test_tavily_price(self):
        rp = self.price()
        self.assertEqual((rp["method"], rp["badge"]), ("tavily", "실측가 (Tavily)"))
        self.assertEqual(rp["usd_price"], "$9 USD")
        self.assertEqual(self.retail.web_calls, [])


class WebPrice(RetailPriceTest):
    retail_mode = "web"

    def test_openai_web_price(self):
        rp = self.price()
        self.assertEqual((rp["method"], rp["badge"]), ("openai_web", "AI 웹 검색가"))
        self.assertEqual(rp["sources"], [{"url": "https://www.hmart.com/yakgwa", "title": "H Mart Yakgwa"}])


class UncitedPrice(RetailPriceTest):
    retail_mode = "uncited"

    def test_uncited_web_price_falls_back_to_estimate(self):
        rp = self.price()
        self.assertEqual((rp["method"], rp["badge"]), ("estimate", "타깃 세그먼트 추정가"))


class AppTest(Base):
    def setUp(self):
        super().setUp()
        import app as web
        self.client = web.app.test_client()

    def wait(self, kind, job_id):
        for _ in range(300):
            p = self.client.get(f"/api/{kind}/{job_id}/progress").get_json()
            if p["status"] != "running":
                return p
            time.sleep(0.03)
        self.fail("작업이 끝나지 않음")

    def test_trend_flow_prefetches_booth(self):
        ids = self.client.post("/api/trend/start", data=FORM).get_json()
        p = self.wait("trend", ids["job_id"])
        self.assertEqual((p["status"], p["percent"]), ("done", 100))
        self.assertEqual(p["booth_job_id"], ids["booth_job_id"])
        self.assertEqual(self.wait("booth", ids["booth_job_id"])["status"], "done")
        html = self.client.get(f"/trend/{ids['job_id']}").get_data(as_text=True)
        for s in ["<h1>트렌드 조사</h1>", f'href="/booth/{ids["booth_job_id"]}">부스 컨셉 기획 →',
                  "1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링", "cluster-num",
                  "2. 현지 리테일 벤치마킹", '<div class="k">제품 스펙</div>', '<span class="tag">400g</span>',
                  "소비자 페인 포인트", '<ul class="pain">', 'class="price-big"', 'class="pitch"', "추천 매대",
                  'data-tip="최근 3개월 ', "(Google 트렌드 상대 지수)", "급상승 지표)",
                  "3. 현지 시장 트렌드 분석", 'class="stat-pill"', "자세히 보기", 'id="art-E1"', 'data-title="근거 기사"',
                  "박람회 준비부터 바이어 관리까지."]:
            self.assertIn(s, html, s)
        for s in ["4. 부스 컨셉", "BIG IDEA", "원본 데이터", "우리 vs", "경쟁 제품 비교"]:
            self.assertNotIn(s, html, s)
        # 전체 결과는 파일로만 저장
        saved = os.listdir(os.path.join(self.tmp.name, "results"))
        self.assertIn(f"trend_{ids['job_id']}.json", saved)
        self.assertIn(f"booth_{ids['booth_job_id']}.json", saved)
        self.assertIn("scores", json.load(open(os.path.join(self.tmp.name, "results", f"booth_{ids['booth_job_id']}.json")))["booth"])

    def test_long_specs_as_list_and_empty_cluster_card(self):
        long_specs = "냉장 생면과 닭 육수 소스를 함께 구성한 약 2인분 라멘 키트다. 면은 유탕 건면이 아닌 냉장 생면이다."
        empty_first = lambda d: {**d, "section1": {**d["section1"], "clusters": [
            {**d["section1"]["clusters"][0], "keywords": []}] + d["section1"]["clusters"][1:]}}
        with mock.patch.dict(ANALYSIS, {"competitor_specs": long_specs}):
            d = empty_first(services.run_trend(FORM))
        import app as web
        with web.app.test_request_context():
            html = web._trend_page(FORM, d)
        self.assertIn('<ul class="fact-list">', html)
        self.assertIn("<li>면은 유탕 건면이 아닌 냉장 생면이다</li>", html)
        self.assertNotIn('<span class="tag">냉장 생면', html)
        self.assertIn('<div class="card empty">', html)                 # 검색어가 없어도 01 카드 유지
        self.assertIn('<span class="cluster-num">01</span>', html)
        self.assertEqual(html.count('<span class="cluster-num">'), 4)
        self.assertNotIn("검색 신호가 확인되지 않은 분류", html)

    def test_booth_page(self):
        job_id = self.client.post("/api/booth/start", data=FORM).get_json()["job_id"]
        self.wait("booth", job_id)
        html = self.client.get(f"/booth/{job_id}").get_data(as_text=True)
        for s in ["<h1 style=\"margin-top:6px\">부스 컨셉 기획</h1>", "약과 · 미국 · Summer Fancy Food Show 2027",
                  'class="slogan-hero"', "“Sweet Heritage, Zero Sticky Fingers”", "Executive Summary", "BIG IDEA",
                  "TARGET &amp; MESSAGE", 'data-mode="short"', 'data-view="short">요약</button>', 'data-view="full">원문</button>',
                  '<span class="short">', '<span class="full">', "전략 근거 · Fact → Insight → Implication",
                  "Execution Plan", 'class="ilist"', 'class="ev-side"', "“Honey Heritage, No Sticky Fingers”",
                  "Visitor Journey", '>3초</button>', '>3분</button>', '<div class="j-head">원페이저 상담</div>',
                  "🎯 목표", 'class="bubble"', "바이어에게 건넬 말", "👀 방문객 경험", "🙋 직원 행동", "🧰 소품·연출",
                  "운영 리스크 점검", "추가 확인 요청 사항", 'type="checkbox" data-check-key=',
                  'data-tab="memo" data-target="R2"', 'id="art-R2"', '<span class="ev company">기업: 강점</span>']:
            self.assertIn(s, html, s)
        for s in ["OpenAI 단독 기획", "gpt-6-astra", "바이어 채점", "원본 데이터", "Key Actions", "KEY ACTIONS",
                  '<div class="target">', "흰 장갑 시식으로 끈적임 없음 증명", "자세히", "more-inline", "3분: 원페이저",
                  "ev-toggle", "통로에서 멈춤", "근거: R2"]:
            self.assertNotIn(s, html, s)

    def test_booth_page_while_running_keeps_waiting(self):
        job_id = jobs.start("booth", lambda form, force, progress: time.sleep(0.3) or {"booth": None},
                            FORM, False, services.booth_progress())
        html = self.client.get(f"/booth/{job_id}").get_data(as_text=True)
        self.assertIn(f'data-running-job="{job_id}"', html)
        self.wait("booth", job_id)

    def test_start_validation_and_missing(self):
        res = self.client.post("/api/trend/start", data={**FORM, "name": ""})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.client.get("/api/booth/nope/progress").get_json()["status"], "missing")
        self.assertIn("찾지 못했습니다", self.client.get("/booth/nope").get_data(as_text=True))
        self.assertEqual(self.client.get("/trend/nope").status_code, 302)

    def test_sync_fallbacks_and_prefill(self):
        self.assertIn("트렌드 조사", self.client.get("/").get_data(as_text=True))
        self.assertIn('value="약과"', self.client.get("/booth?name=약과").get_data(as_text=True))
        self.assertIn("Executive Summary", self.client.post("/booth", data=FORM).get_data(as_text=True))
        self.assertIn("3. 현지 시장 트렌드 분석", self.client.post("/", data=FORM).get_data(as_text=True))

    def test_json_api(self):
        job_id = self.client.post("/api/booth/start", data=FORM).get_json()["job_id"]
        self.wait("booth", job_id)
        data = self.client.get(f"/api/booth/{job_id}").get_json()
        self.assertEqual(data["status"], "done")
        self.assertIn("visitor_flow", data["result"]["booth"])


class SearchErrorTest(Base):
    def test_credit_error_shown_in_sections_2_and_3(self):
        UsageLimitExceededError = type("UsageLimitExceededError", (Exception,), {})

        def boom(*a, **k):
            raise UsageLimitExceededError("This request exceeds your plan's set usage limit.")
        self.retail_mode = "none"
        with mock.patch.object(fakes.FakeTavily, "search", side_effect=boom), \
             mock.patch.object(RetailTavily, "search", side_effect=boom):
            d = services.run_trend(FORM, force=True)
        self.assertEqual(d["research"]["search_error"], "credits")
        self.assertEqual(d["research"]["stats"]["sources_found"], 0)
        self.assertEqual(d["section2"]["retail_price"]["search_error"], "credits")
        import app as web
        with web.app.test_request_context():
            html = web._trend_page(FORM, d)
        self.assertEqual(html.count("검색 API 크레딧이 만료되어 자료 검색에 실패했어요"), 2)
        # 0건 결과는 캐시에 남기지 않음
        import sqlite3
        conn = sqlite3.connect(services.CACHE_DB_PATH)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM search_cache WHERE v='[]'").fetchone()[0], 0)

    def test_error_kind(self):
        self.assertEqual(research.search_error_kind(RuntimeError("HTTP 432: usage limit exceeded")), "credits")
        self.assertEqual(research.search_error_kind(type("InvalidAPIKeyError", (Exception,), {})("bad")), "key")
        self.assertEqual(research.search_error_kind(RuntimeError("timeout")), "failed")


class PromptTest(unittest.TestCase):
    def test_retail_prompt_has_no_product_specific_examples(self):
        import inspect
        src = inspect.getsource(retail_research.analyze_retail_market)
        for word in ("칼국수", "생면", "Pan Mee", "미고랭", "noodle", "국물", "Noodle Zone"):
            self.assertNotIn(word, src, word)
        self.assertIn("같은 카테고리·같은 용도", src)

    def test_booth_skill_example_is_category_neutral(self):
        text = open(os.path.join(HERE, "skills", "booth_marketing", "SKILL.md"), encoding="utf-8").read()
        for word in ("밀키트", "배달", "15분"):
            self.assertNotIn(word, text, word)


class ModelUpgradeTest(unittest.TestCase):
    def setUp(self):
        model_upgrade._resolved.clear()
        model_upgrade._dropped.clear()

    tearDown = setUp

    def test_reasoning_params_and_fallback(self):
        calls = []

        def create(**kw):
            calls.append(kw)
            if kw["model"] == "gpt-6-astra":
                req = httpx.Request("POST", "https://api.openai.com/v1/x")
                raise openai.NotFoundError("no model", response=httpx.Response(404, request=req), body={})
            return SimpleNamespace(model=kw["model"])

        client = model_upgrade.wrap(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                                                    responses=SimpleNamespace(create=create)))
        client.chat.completions.create(model=model_upgrade.TASK_MODEL, temperature=0.3, messages=[])
        self.assertEqual(calls[0], {"model": "gpt-5.6-terra", "reasoning_effort": "low", "messages": []})
        self.assertEqual(client.chat.completions.create(model=model_upgrade.BOOTH_MODEL, messages=[]).model, "gpt-5.6-sol")


class LayoutTest(unittest.TestCase):
    def test_self_contained(self):
        """다른 폴더(trend_usp_v1, tavily_v9, j_test)를 불러오지 않는다."""
        for name in ("trend_usp", "research", "retail_research", "skill_loader", "env_setup", "http_compat"):
            self.assertTrue(sys.modules[name].__file__.startswith(HERE), name)


if __name__ == "__main__":
    unittest.main()

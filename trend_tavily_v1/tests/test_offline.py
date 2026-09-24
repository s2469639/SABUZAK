"""네트워크 없이 결합 로직과 화면 렌더링을 검증하는 오프라인 테스트.

trend_usp_v1의 가짜 Google 트렌드·OpenAI 응답과, 가짜 tavily_v5 결과를 사용한다.
    python -m unittest discover -s tests -v
"""

import functools
import importlib.util
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import combined  # noqa: E402
from combined import english_country_name, run_combined, trend_usp  # noqa: E402

# trend_usp_v1 테스트의 가짜 응답을 그대로 재사용
_spec = importlib.util.spec_from_file_location(
    "trend_fakes", os.path.join(combined.TREND_DIR, "tests", "test_offline.py"))
trend_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trend_fakes)
# 위 모듈이 trend_usp_v1 폴더를 sys.path 맨 앞에 넣으므로, 이 폴더의 app.py가 가려지지 않게 되돌린다
while combined.TREND_DIR in sys.path[:sys.path.index(HERE) + 1]:
    sys.path.remove(combined.TREND_DIR)
sys.path.append(combined.TREND_DIR)

PRODUCT = trend_fakes.PRODUCT


def fake_tavily_result(product_name, country, **kwargs):
    fake_tavily_result.calls.append({"product_name": product_name, "country": country, **kwargs})
    quotes = [
        {"id": "E1", "question": "Q2", "quote": "Baklava is sold at Costco for $8.99 per box in most US stores.",
         "translation_ko": "바클라바는 코스트코에서 박스당 8.99달러에 판매된다.", "market": "country",
         "market_label": "대상 국가", "year": 2026, "is_stale": False, "source_ids": ["S1"], "scope": "category"},
        {"id": "E2", "question": "Q1", "quote": "American snackers increasingly look for less sticky, portable sweets.",
         "translation_ko": "미국 소비자는 덜 끈적이고 휴대하기 쉬운 단 간식을 찾는다.", "market": "country",
         "market_label": "대상 국가", "year": 2025, "is_stale": False, "source_ids": ["S2"], "scope": "category"},
        {"id": "E3", "question": "Q3", "quote": "Importers require FDA-compliant labels and at least 9 months of shelf life.",
         "translation_ko": "수입사는 FDA 라벨과 최소 9개월 유통기한을 요구한다.", "market": "country",
         "market_label": "대상 국가", "year": 2026, "is_stale": False, "source_ids": ["S3"], "scope": "general"},
        {"id": "E4", "question": "Q1", "quote": "Lotus Biscoff remains a favorite coffee companion.",
         "translation_ko": "로투스 비스코프는 커피와 곁들이는 인기 간식이다.", "market": "region",
         "market_label": "권역 참고(북미)", "year": 2022, "is_stale": True, "source_ids": ["S2"], "scope": "category"},
    ]
    sources = [
        {"id": "S1", "title": "Costco baklava", "url": "https://example-news.com/baklava", "domain": "example-news.com"},
        {"id": "S2", "title": "Snack trends", "url": "https://snacks.example.org/trends", "domain": "snacks.example.org"},
        {"id": "S3", "title": "Import guide", "url": "https://kati.net/guide", "domain": "kati.net"},
    ]
    cards = [
        {"qid": "Q1", "title": "소비자", "points": [{"text": "덜 끈적이고 휴대 쉬운 간식 선호", "quote_ids": ["E2"]}]},
        {"qid": "Q2", "title": "경쟁 제품", "points": [{"text": "바클라바 박스당 8.99달러 판매", "quote_ids": ["E1"]}]},
        {"qid": "Q3", "title": "바이어·유통", "points": [{"text": "FDA 라벨·최소 9개월 유통기한 요구", "quote_ids": ["E3"]}]},
        {"qid": "Q4", "title": "박람회·부스", "points": []},
    ]
    return {"quotes": quotes, "sources": sources, "cards": cards,
            "booth": {"key_message": "끈적임 없는 휴대용 전통 과자", "reasons": [{"text": "휴대성 수요", "quote_ids": ["E2", "E9"]}],
                      "ideas": []},
            "stats": {"quotes_used": 4, "country_quotes": 3, "sources_found": 3}}


fake_tavily_result.calls = []


class CombinedTest(unittest.TestCase):
    def setUp(self):
        trend_fakes.FakeTrends.fail_related = False
        trend_fakes.FakeTrends.fail_iot = False
        trend_fakes.FakeTrends.sparse = False
        trend_fakes.FakeTrends.calls = []
        fake_tavily_result.calls = []
        self.patches = [
            mock.patch.object(trend_usp, "_chat_json", side_effect=trend_fakes.fake_chat_json),
            mock.patch.object(trend_usp, "TrendsClient", trend_fakes.FakeTrends),
            mock.patch.object(combined.tavily_research, "run_research", side_effect=fake_tavily_result),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_both_pipelines_linked(self):
        combo = run_combined(PRODUCT, "미국", "Summer Fancy Food Show")
        self.assertIsNone(combo["trend_error"])
        self.assertIsNone(combo["tavily_error"])
        self.assertEqual(combo["country_en"], "United States")
        call = fake_tavily_result.calls[0]
        self.assertEqual((call["product_name"], call["country"], call["exhibition_name"]),
                         ("약과", "United States", "Summer Fancy Food Show"))
        self.assertEqual(call["company_profile"]["price_range"], PRODUCT["price"])

        links = combo["links"]
        by_name = {c["id"]: c["name"] for c in combo["trend"]["competitors"]}
        linked = {by_name[cid]: v for cid, v in links["competitors"].items()}
        self.assertEqual(set(linked), {"Baklava", "Biscoff Cookies"})       # ghost 제품은 웹 출처 없음
        self.assertEqual(linked["Baklava"]["quotes"][0]["id"], "E1")         # Q2·대상 국가 발췌 우선
        self.assertEqual(linked["Baklava"]["price_quotes"][0]["id"], "E1")   # 가격 표현 있는 발췌
        self.assertEqual(linked["Biscoff Cookies"]["price_quotes"], [])
        self.assertTrue(linked["Baklava"]["price_confirmed"])               # AI 가격 $8.99 = 웹 발췌 $8.99
        self.assertFalse(linked["Biscoff Cookies"]["price_confirmed"])
        self.assertEqual(linked["Baklava"]["quotes"][0]["url"], "https://example-news.com/baklava")

        self.assertEqual(links["checkpoint_source"], "web")
        self.assertEqual(links["buyer"][0]["refs"][0]["domain"], "kati.net")
        self.assertEqual(links["exhibition"], [])
        self.assertEqual([r["id"] for r in links["tavily_booth"]["reasons"][0]["refs"]], ["E2"])  # 없는 E9 제거
        self.assertEqual(links["summary"]["usp_rows_web_confirmed"], 2)
        self.assertEqual(links["summary"]["web_cards_with_points"], 3)

    def test_tavily_failure_keeps_trend(self):
        combined.tavily_research.run_research.side_effect = RuntimeError("TAVILY_API_KEY가 설정되어 있지 않습니다")
        combo = run_combined(PRODUCT, "미국")
        self.assertIsNotNone(combo["trend"])
        self.assertIn("TAVILY_API_KEY", combo["tavily_error"])
        self.assertEqual(combo["links"]["competitors"], {})
        self.assertEqual(combo["links"]["checkpoint_source"], "ai")

    def test_trend_failure_keeps_tavily(self):
        with mock.patch.object(combined, "_run_trend", side_effect=trend_usp.PipelineError("AI 분석 호출 실패")):
            combo = run_combined(PRODUCT, "미국")
        self.assertIsNone(combo["trend"])
        self.assertIn("AI 분석 호출 실패", combo["trend_error"])
        self.assertTrue(combo["links"]["consumer"])

    def test_both_fail(self):
        combined.tavily_research.run_research.side_effect = RuntimeError("tavily down")
        with mock.patch.object(combined, "_run_trend", side_effect=RuntimeError("trends down")):
            with self.assertRaises(trend_usp.PipelineError):
                run_combined(PRODUCT, "미국")

    def test_render_combined_page(self):
        import app as web
        client = web.app.test_client()
        html = client.post("/", data={**PRODUCT, "country": "미국"}).get_data(as_text=True)
        for text in ["검색 트렌드 + 웹 자료 결합 진단", "USP 경쟁 제품 중 웹 출처로도 확인", "2 / 2", "웹 출처 확인",
                     "example-news.com", "웹 출처 가격 있음 [E1]", "웹 출처와 일치 [E1]", "웹 자료로 본 현지 소비자",
                     "FDA 라벨·최소 9개월 유통기한 요구", "웹 자료 기반 부스 포인트", "kdrama yakgwa", "Biscoff Cookies"]:
            self.assertIn(text, html, text)
        self.assertNotIn("박람회 트렌드·부스 사례", html)       # Q4 근거 없음 → 패널 숨김
        # 웹 출처 체크포인트가 AI 참고 체크포인트보다 우선 (AI 참고 목록은 화면에 그리지 않음, 원본 JSON에만 남음)
        self.assertIn('이 시장 바이어가 주로 확인하는 것 <span class="ev web">웹 출처</span>', html)
        self.assertNotIn('<ul class="checklist">', html)
        self.assertEqual(client.get("/").status_code, 200)

    def test_render_when_trend_fails(self):
        import app as web
        with mock.patch.object(combined, "_run_trend", side_effect=trend_usp.PipelineError("AI 분석 호출 실패")):
            html = web.app.test_client().post("/", data={**PRODUCT, "country": "미국"}).get_data(as_text=True)
        self.assertIn("검색 트렌드 분석 실패", html)
        self.assertIn("웹 자료 조사 결과", html)
        self.assertIn("덜 끈적이고 휴대 쉬운 간식 선호", html)

    def test_render_when_tavily_fails(self):
        import app as web
        combined.tavily_research.run_research.side_effect = RuntimeError("tavily down")
        html = web.app.test_client().post("/", data={**PRODUCT, "country": "미국"}).get_data(as_text=True)
        self.assertIn("웹 자료(Tavily) 조사 실패", html)
        self.assertIn('<ul class="checklist">', html)           # AI 참고 체크포인트로 대체


class UnitTest(unittest.TestCase):
    def test_english_country_name(self):
        profiles = trend_usp.COUNTRY_PROFILES
        self.assertEqual(english_country_name(profiles["US"], "미국"), "United States")
        self.assertEqual(english_country_name(profiles["DE"], "독일"), "Germany")
        self.assertEqual(english_country_name(profiles["AE"], "두바이"), "United Arab Emirates")
        self.assertEqual(english_country_name({"aliases": []}, "페루"), "페루")

    def test_price_amounts(self):
        self.assertEqual(combined.price_amounts("$8.99 / 12oz"), {"8.99"})
        self.assertEqual(combined.price_amounts("30개입 8,000원, 약 6 USD"), {"8000", "6"})
        self.assertEqual(combined.price_amounts("12 months"), set())

    def test_mentions_word_boundary(self):
        self.assertTrue(combined._mentions("Lotus Biscoff is popular", ["biscoff"]))
        self.assertFalse(combined._mentions("Biscoffee shop", ["biscoff"]))
        self.assertFalse(combined._mentions("a b c", ["abc", "b"]))           # 4자 미만 이름은 매칭 안 함

    def test_tavily_openai_wrapped_for_old_brotli(self):
        self.assertIsInstance(combined.tavily_research.OpenAI, functools.partial)
        self.assertEqual(combined.tavily_research.OpenAI.keywords["default_headers"]["Accept-Encoding"], "gzip, deflate")


if __name__ == "__main__":
    unittest.main()

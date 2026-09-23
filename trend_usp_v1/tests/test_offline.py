"""네트워크 없이 파이프라인 로직과 화면 렌더링을 검증하는 오프라인 테스트.

Google Trends와 OpenAI 호출을 가짜 응답으로 바꿔서 실행한다.
    python -m unittest discover -s tests -v
"""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import trend_usp  # noqa: E402
from trend_usp import compute_yoy, find_unsupported_certs, run_trend_usp  # noqa: E402

PRODUCT = {
    "name": "약과",
    "strengths": "조청 흡수가 적어 손에 안 묻는 식감, 개별 포장",
    "ingredients": "밀가루, 꿀, 참기름",
    "certifications": "HACCP",
    "price": "200g 소매가 6~7달러",
}


def weekly_series(base: float, recent: float, weeks: int = 260) -> list:
    """앞부분은 base, 마지막 13주는 recent인 주간 시계열."""
    return [base] * (weeks - 13) + [recent] * 13


RELATED = {
    "yakgwa": {
        "top": [{"query": "yakgwa recipe", "value": 100}, {"query": "korean honey cookie", "value": 60},
                {"query": "yakgwa", "value": 50}],
        "rising": [{"query": "buy yakgwa near me", "value": 340}, {"query": "yakgwa ice cream", "value": 9000},
                   {"query": "baklava vs yakgwa", "value": 120}],
    },
    "korean honey cookie": {
        "top": [{"query": "Yakgwa  Recipe", "value": 40}, {"query": "yakgwa with coffee", "value": 30},
                {"query": "honey pastry biscuit", "value": 20}],
        "rising": [{"query": "kpop demon hunters snack", "value": 250}],
    },
}

SERIES = {
    "yakgwa recipe": weekly_series(40, 34),          # -15%
    "buy yakgwa near me": weekly_series(5, 22),      # +340%
    "yakgwa ice cream": weekly_series(10, 20),       # +100%
    "baklava vs yakgwa": weekly_series(0, 3),        # 데이터 부족 (전년 0)
    "honey pastry biscuit": weekly_series(20, 29),   # +45%
    "yakgwa with coffee": weekly_series(10, 10),     # 0%
    "kpop demon hunters snack": weekly_series(0, 0),
}


def fake_chat_json(system_prompt, user_prompt, temperature):
    if "시드" not in user_prompt and "Google에 실제로 입력하는 검색어를 만드세요" in user_prompt:
        return {"seeds": [{"keyword": "yakgwa", "lang": "English", "ko": "약과"},
                          {"keyword": "korean honey cookie", "lang": "English", "ko": "한국 꿀과자"},
                          {"keyword": "YAKGWA", "lang": "English", "ko": "중복"}],
                "category": {"keyword": "korean dessert", "lang": "English", "ko": "한국 디저트"},
                "english_name": "Yakgwa"}
    if "추정해야 합니다" in user_prompt:
        return {"keywords": ["yakgwa recipe", "buy yakgwa online", "yakgwa vs baklava", "yakgwa with tea"]}
    if "현지 연관 검색어 목록" in user_prompt:
        ids = {}
        for line in user_prompt.splitlines():
            m = re.match(r"^\[(\d+)\] (.*)$", line)
            if m:
                ids[m.group(2).replace(" (급상승)", "")] = int(m.group(1))

        def ref(kw, **extra):
            return {"id": ids.get(kw, 999), "ko": f"{kw} 해석", **extra}

        return {"clusters": {
            "culture_trigger": {"items": [ref("kpop demon hunters snack"), ref("yakgwa ice cream"),
                                          {"id": 999, "ko": "지어낸 검색어"}],
                                "summary_ko": "K-콘텐츠 유입", "tag_ko": "미디어 결합도", "insight_ko": "화제성 활용"},
            "intent_funnel": {"items": [ref("buy yakgwa near me", stage="purchase"),
                                        ref("yakgwa recipe", stage="consideration"),
                                        ref("yakgwa ice cream")],  # 중복 ID → 폐기돼야 함
                              "summary_ko": "구매 전환", "tag_ko": "구매 단계 전환", "insight_ko": "완제품 타깃"},
            "category_perception": {"items": [ref("baklava vs yakgwa"), ref("honey pastry biscuit")],
                                    "summary_ko": "대체재 비교", "tag_ko": "조력 대체재", "insight_ko": "차별화"},
            "consumption_habit": {"items": [ref("yakgwa with coffee")],
                                  "summary_ko": "커피 페어링", "tag_ko": "취식 페어링", "insight_ko": "번들 제안"},
        }, "excluded": [{"id": ids.get("korean honey cookie", 999), "reason_ko": "시드와 동일"}]}
    if "usp_matrix" in user_prompt:
        return {"usp_matrix": [
            {"target": "Baklava", "target_ko": "바클라바", "weakness_ko": "시럽이 끈적임",
             "our_usp_ko": "손에 안 묻는 식감 + 개별 포장", "evidence": ["제품 강점"],
             "pitch_headline": "Subtle sweetness without sticky syrup mess", "pitch_headline_ko": "끈적임 없는 은은한 단맛"},
            {"target": "Gluten-free cookies", "target_ko": "글루텐프리 쿠키", "weakness_ko": "식감이 푸석함",
             "our_usp_ko": "비건 인증 전통 레시피", "evidence": ["보유 인증"],
             "pitch_headline": "Vegan heritage recipe", "pitch_headline_ko": "비건 전통 레시피"},
        ], "booth_concept": {
            "headline_slogan": {"title": "Heritage Tea & Coffee Lounge", "title_ko": "헤리티지 라운지",
                                "slogan": "Sweet Heritage, Modern Craving", "slogan_ko": "달콤한 전통", "description_ko": "라운지 연출"},
            "sampling_strategy": {"title": "Espresso Pairing Bar", "title_ko": "에스프레소 페어링 바", "description_ko": "시식"},
            "pitching_wall": {"title": "Holiday Golden PO Wall", "title_ko": "연말 발주 월", "description_ko": "인포그래픽"},
            "packaging_display": {"title": "Stand Pouch Line", "title_ko": "스탠드 파우치", "description_ko": "진열"},
        }}
    if "Google 트렌드 조사용 프로필" in user_prompt:
        return {"geo": "PE", "name_ko": "페루", "languages": ["Spanish"], "hl": "es-419",
                "buyer_language": "Spanish", "reliability": "high", "reliability_note_ko": ""}
    raise AssertionError(f"예상하지 못한 프롬프트: {user_prompt[:200]}")


class FakeTrends:
    fail_related = False
    fail_iot = False
    calls = []

    def __init__(self, hl, use_cache=True):
        self.hl = hl

    def related_queries(self, keywords, geo):
        FakeTrends.calls.append(("related", tuple(keywords), geo))
        if FakeTrends.fail_related:
            raise RuntimeError("429 Too Many Requests")
        return {kw: RELATED.get(kw, {"top": [], "rising": []}) for kw in keywords}

    def interest_over_time(self, keywords, geo):
        FakeTrends.calls.append(("iot", tuple(keywords), geo))
        if FakeTrends.fail_iot:
            raise RuntimeError("429 Too Many Requests")
        return {kw: SERIES.get(kw, weekly_series(0, 0)) for kw in keywords}


class PipelineTest(unittest.TestCase):
    def setUp(self):
        FakeTrends.fail_related = False
        FakeTrends.fail_iot = False
        FakeTrends.calls = []
        self.patches = [mock.patch.object(trend_usp, "_chat_json", side_effect=fake_chat_json),
                        mock.patch.object(trend_usp, "TrendsClient", FakeTrends)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _all_keywords(self, result):
        return {kw["keyword"]: kw for c in result["trend_analysis"].values() for kw in c["keywords"]}

    def test_normal_flow(self):
        result = run_trend_usp(PRODUCT, "미국")
        meta = result["meta"]
        self.assertEqual(meta["geo"], "US")
        self.assertEqual(meta["data_level"], "seed")
        self.assertEqual([s["keyword"] for s in meta["seed_keywords"]], ["yakgwa", "korean honey cookie"])

        kws = self._all_keywords(result)
        # 지어낸 ID(999)와 중복 ID는 버려짐
        self.assertNotIn("지어낸 검색어", [k["ko"] for k in kws.values()])
        self.assertEqual(len(result["trend_analysis"]["intent_funnel"]["keywords"]), 2)
        # 시드 자체("yakgwa")는 연관 검색어에서 제외, 대소문자·공백 중복 병합
        self.assertNotIn("yakgwa", kws)
        self.assertEqual(sum(1 for k in kws if k.casefold() == "yakgwa recipe"), 1)
        self.assertEqual(kws["yakgwa recipe"]["source"], "top")
        # 퍼널 순서: 탐색 → 구매 전환
        self.assertEqual([k["stage"] for k in result["trend_analysis"]["intent_funnel"]["keywords"]],
                         ["consideration", "purchase"])
        # YoY 수치는 코드 계산
        self.assertEqual(kws["yakgwa recipe"]["yoy_pct"], -15)
        self.assertEqual(kws["buy yakgwa near me"]["yoy_pct"], 340)
        self.assertEqual(kws["honey pastry biscuit"]["yoy_pct"], 45)
        self.assertEqual(kws["yakgwa with coffee"]["yoy_pct"], 0)
        self.assertIsNone(kws["baklava vs yakgwa"]["yoy_pct"])
        self.assertEqual(kws["baklava vs yakgwa"]["yoy_status"], "insufficient")
        self.assertTrue(kws["yakgwa ice cream"]["is_breakout"])
        # 입력하지 않은 인증(비건) 언급 경고, HACCP만 입력했으므로
        self.assertEqual(result["usp_matrix"][0]["unsupported_certs"], [])
        self.assertIn("비건", result["usp_matrix"][1]["unsupported_certs"])
        self.assertTrue(any("인증" in w for w in meta["warnings"]))
        self.assertEqual(meta["reliability"], "high")
        self.assertEqual(meta["reliability_note_ko"], "")

    def test_trends_failure_falls_back_to_estimate(self):
        FakeTrends.fail_related = True
        result = run_trend_usp(PRODUCT, "USA")
        meta = result["meta"]
        self.assertEqual(meta["data_level"], "estimated")
        self.assertTrue(meta["is_estimated"])
        self.assertTrue(any("AI 추정" in w for w in meta["warnings"]))
        kws = self._all_keywords(result)
        self.assertTrue(kws)
        for kw in kws.values():
            self.assertEqual(kw["yoy_status"], "estimated")
            self.assertIsNone(kw["yoy_pct"])
        # seed@US, category@US, seed@글로벌 순서로 확장 시도
        levels = [(c[1], c[2]) for c in FakeTrends.calls if c[0] == "related"]
        self.assertEqual(levels, [(("yakgwa", "korean honey cookie"), "US"),
                                  (("korean dessert",), "US"),
                                  (("yakgwa", "korean honey cookie"), "")])
        # 추정 모드에선 YoY 조회를 하지 않음
        self.assertFalse(any(c[0] == "iot" for c in FakeTrends.calls))

    def test_yoy_failure_keeps_result(self):
        FakeTrends.fail_iot = True
        result = run_trend_usp(PRODUCT, "us")
        self.assertTrue(any("증감률" in w for w in result["meta"]["warnings"]))
        for kw in self._all_keywords(result).values():
            self.assertIsNone(kw["yoy_pct"])

    def test_low_reliability_country_warning(self):
        result = run_trend_usp(PRODUCT, "중국")
        self.assertEqual(result["meta"]["geo"], "CN")
        self.assertEqual(result["meta"]["reliability"], "low")
        self.assertIn("바이두", result["meta"]["reliability_note_ko"])

    def test_unknown_country_uses_llm_profile(self):
        result = run_trend_usp(PRODUCT, "페루")
        self.assertEqual(result["meta"]["geo"], "PE")
        self.assertTrue(result["meta"]["is_profile_estimated"])

    def test_empty_product_name(self):
        with self.assertRaises(trend_usp.PipelineError):
            run_trend_usp({"name": " "}, "미국")

    def test_flask_render(self):
        import app as web
        client = web.app.test_client()
        resp = client.post("/", data={**PRODUCT, "country": "미국"})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        for text in ["CULTURE TRIGGER", "buy yakgwa near me", "+340%", "-15%", "데이터 부족",
                     "Baklava", "Heritage Tea &amp; Coffee Lounge", "입력하지 않은 인증 언급"]:
            self.assertIn(text, html)
        self.assertEqual(client.get("/").status_code, 200)


class UnitTest(unittest.TestCase):
    def test_compute_yoy(self):
        self.assertEqual(compute_yoy(weekly_series(40, 34))["yoy_pct"], -15)
        self.assertEqual(compute_yoy([1] * 30)["yoy_status"], "insufficient")  # 기간 부족
        self.assertEqual(compute_yoy(weekly_series(0.5, 10))["yoy_status"], "insufficient")  # 기저 너무 작음

    def test_find_unsupported_certs(self):
        self.assertEqual(find_unsupported_certs("HACCP certified vegan snack", "HACCP, 비건"), [])
        self.assertEqual(find_unsupported_certs("Halal & organic", "HACCP"), ["할랄", "유기농"])


if __name__ == "__main__":
    unittest.main()

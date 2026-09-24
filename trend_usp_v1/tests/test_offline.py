"""네트워크 없이 v2 파이프라인 로직과 화면 렌더링을 검증하는 오프라인 테스트.

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
from trend_usp import (  # noqa: E402
    compute_yoy,
    find_unsupported_certs,
    headline_issues,
    is_generic_target,
    run_trend_usp,
    validate_pitch_blocks,
)

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


class PipelineTest(unittest.TestCase):
    def setUp(self):
        FakeTrends.fail_related = False
        FakeTrends.fail_iot = False
        FakeTrends.sparse = False
        FakeTrends.calls = []
        self.chat = mock.patch.object(trend_usp, "_chat_json", side_effect=fake_chat_json)
        self.chat_mock = self.chat.start()
        self.trends = mock.patch.object(trend_usp, "TrendsClient", FakeTrends)
        self.trends.start()

    def tearDown(self):
        self.chat.stop()
        self.trends.stop()

    def _kws(self, result):
        return {kw["keyword"]: kw for c in result["trend_analysis"].values() for kw in c["keywords"]}

    # --- 1단계: 수집·분류·배지 -------------------------------------------------
    def test_collection_uses_seed_and_category_together(self):
        result = run_trend_usp(PRODUCT, "미국")
        related_calls = [c for c in FakeTrends.calls if c[0] == "related"]
        self.assertEqual(related_calls, [("related", ("yakgwa", "korean honey cookie", "korean dessert"), "US", "today 12-m")])
        self.assertEqual(result["meta"]["data_level"], "seed")
        self.assertGreaterEqual(result["meta"]["keyword_pool_size"], 10)

    def test_collection_widens_when_sparse(self):
        FakeTrends.sparse = True
        result = run_trend_usp(PRODUCT, "미국")
        levels = [(a["level"], a["geo"], a["timeframe"]) for a in result["meta"]["collection_attempts"]]
        self.assertEqual(levels, [("seed", "US", "today 12-m"), ("extended", "US", "today 5-y"),
                                  ("global", "GLOBAL", "today 12-m")])
        self.assertEqual(result["meta"]["data_level"], "global")
        self.assertTrue(any("전 세계" in w for w in result["meta"]["warnings"]))

    def test_classification_validation_and_badges(self):
        result = run_trend_usp(PRODUCT, "미국")
        kws = self._kws(result)
        ta = result["trend_analysis"]
        self.assertNotIn("지어낸 검색어", [k.get("ko") for k in kws.values()])
        self.assertNotIn("yakgwa", kws)                                   # 시드 제외
        self.assertEqual(sum(1 for k in kws if k.casefold() == "yakgwa recipe"), 1)  # 중복 병합
        self.assertIn("Baklava", [k["keyword"] for k in ta["category_perception"]["keywords"]])  # 연관 주제 → 경쟁 인식
        self.assertEqual(kws["Baklava"]["kind"], "topic")
        # 퍼널 순서(인지→탐색→구매, 단계 없음은 맨 뒤) + 중복 ID는 먼저 넣은 분류(intent)에만
        self.assertEqual([k["stage"] for k in ta["intent_funnel"]["keywords"]],
                         ["consideration", "purchase", "purchase", None])
        self.assertEqual([k["keyword"] for k in ta["consumption_habit"]["keywords"]], ["yakgwa with coffee"])
        self.assertEqual([e["keyword"] for e in result["excluded_keywords"]], ["hotteok"])
        # 배지 우선순위: YoY → 급상승 → 없음
        self.assertEqual(kws["yakgwa recipe"]["badge"], {"kind": "yoy", "pct": -15})
        self.assertEqual(kws["costco yakgwa"]["badge"], {"kind": "yoy", "pct": 340})
        self.assertEqual(kws["yakgwa with coffee"]["badge"], {"kind": "yoy", "pct": 0})
        self.assertEqual(kws["buy yakgwa near me"]["badge"], {"kind": "rising", "pct": 340})
        self.assertEqual(kws["baklava vs yakgwa"]["badge"], {"kind": "rising", "pct": 120})
        self.assertIsNone(kws["Baklava"]["badge"] if kws["Baklava"]["yoy_pct"] is None else None)
        self.assertTrue(kws["yakgwa ice cream"]["is_breakout"])
        self.assertEqual(kws["yakgwa recipe"]["evidence"], "measured")

    # --- 4단계: 탐색 검증 ------------------------------------------------------
    def test_probe_keywords_verified_by_search_volume(self):
        result = run_trend_usp(PRODUCT, "미국")
        culture = [k["keyword"] for k in result["trend_analysis"]["culture_trigger"]["keywords"]]
        self.assertEqual(culture, ["kdrama yakgwa"])       # 검색량 있는 후보만 남음, 중복 후보는 제외
        kw = result["trend_analysis"]["culture_trigger"]["keywords"][0]
        self.assertEqual(kw["evidence"], "probe")
        self.assertEqual(kw["badge"], {"kind": "yoy", "pct": 200})
        self.assertEqual((result["meta"]["probe_candidates"], result["meta"]["probe_verified"]), (2, 1))
        # 검색어 2개 미만인 분류만 요청 (culture 0개, habit은 중복 제거 후 1개 / intent·perception은 충분)
        probe_prompt = next(c.args[1] for c in self.chat_mock.call_args_list if "신호가 부족했습니다" in c.args[1])
        self.assertIn("- culture_trigger:", probe_prompt)
        self.assertIn("- consumption_habit:", probe_prompt)
        self.assertNotIn("- intent_funnel:", probe_prompt)

    # --- 2단계: 시장 맥락·검색량 비교·USP ---------------------------------------
    def test_competitors_filtered_and_compared_with_anchor(self):
        result = run_trend_usp(PRODUCT, "미국")
        names = [c["name"] for c in result["competitors"]]
        self.assertNotIn("Korean Snacks", names)            # 카테고리 이름 제거
        search = {c["name"]: c["vs_anchor"] for c in result["competitor_search"]}
        self.assertEqual(search, {"Biscoff Cookies": 5.0, "Baklava": 3.0})  # 검색 흔적 없는 후보 제외, 큰 순
        # 모든 검색량 조회 묶음에 기준점(anchor)이 포함되고 5개를 넘지 않음
        for call in [c for c in FakeTrends.calls if c[0] == "iot" and len(c[1]) > 1]:
            self.assertEqual(call[1][0], "yakgwa")
            self.assertLessEqual(len(call[1]), 5)

    def test_usp_rows_checked_and_regenerated(self):
        result = run_trend_usp(PRODUCT, "미국")
        rows = result["usp_matrix"]
        self.assertEqual([r["competitor_id"] for r in rows], ["C1", "C2"])   # 없는 C9 제거
        c1, c2 = rows
        self.assertEqual(c1["pitch_headline"], "No sticky syrup: honey pastry that stays clean")  # 상투어 → 재생성
        self.assertEqual(c1["issues"], [])
        self.assertEqual(c2["unsupported_certs"], [])                       # 비건 언급 → 재생성으로 해소
        self.assertEqual(c1["target_evidence"], "search_verified")
        self.assertEqual(c1["price_evidence"], "ai")
        self.assertEqual(c1["evidence"], ["제품 강점"])
        usp_calls = [c for c in self.chat_mock.call_args_list if "USP 행을 만드세요" in c.args[1]]
        self.assertEqual(len(usp_calls), 2)

    def test_known_competitor_marked_as_user_input(self):
        def chat(system, prompt, temperature, strategy=False):
            data = fake_chat_json(system, prompt, temperature, strategy)
            if "buyer_checkpoints" in prompt:
                data["competitors"][0]["from_user"] = True
            return data
        self.chat_mock.side_effect = chat
        result = run_trend_usp({**PRODUCT, "known_competitors": "Baklava 12oz 8.99달러"}, "미국")
        baklava = next(c for c in result["competitors"] if c["name"] == "Baklava")
        self.assertTrue(baklava["from_user"])
        self.assertEqual(baklava["price_evidence"], "user")

    # --- 3단계: 부스 ------------------------------------------------------------
    def test_booth_without_pitch_inputs(self):
        result = run_trend_usp(PRODUCT, "미국")
        booth = result["booth_concept"]
        self.assertIsNone(booth["pitching_wall"])
        self.assertFalse(result["meta"]["has_pitch_inputs"])
        self.assertEqual(booth["sampling_strategy"]["compare_with"], "Baklava")
        self.assertEqual(booth["headline_slogan"]["refs"], ["검색어 yakgwa ice cream", "입력: 제품 강점"])
        self.assertNotIn("입력: 유통기한", booth["packaging_display"]["refs"])   # 입력 안 한 항목 참조는 버림
        booth_prompt = next(c.args[1] for c in self.chat_mock.call_args_list if "박람회 부스 카드" in c.args[1])
        self.assertNotIn("pitching_wall", booth_prompt)

    def test_booth_pitch_wall_uses_only_input_numbers(self):
        result = run_trend_usp(PITCH_PRODUCT, "미국")
        wall = result["booth_concept"]["pitching_wall"]
        self.assertEqual([b["value"] for b in wall["blocks"]], ["12 months", "$6-7"])  # 24개월·미입력 MOQ 제거
        self.assertEqual(wall["blocks"][0]["source_label"], "유통기한")
        self.assertEqual(wall["refs"], ["입력: 유통기한"])

    # --- 실패·경계 상황 ----------------------------------------------------------
    def test_trends_failure_falls_back_to_estimate(self):
        FakeTrends.fail_related = True
        result = run_trend_usp(PRODUCT, "USA")
        meta = result["meta"]
        self.assertEqual(meta["data_level"], "estimated")
        self.assertTrue(any("AI 추정" in w for w in meta["warnings"]))
        for kw in self._kws(result).values():
            self.assertEqual(kw["evidence"], "estimated")
            self.assertIsNone(kw["badge"])
        self.assertFalse(any(c[0] == "iot" for c in FakeTrends.calls))
        self.assertEqual(meta["probe_candidates"], 0)

    def test_iot_failure_keeps_result_and_drops_unverified_probes(self):
        FakeTrends.fail_iot = True
        result = run_trend_usp(PRODUCT, "us")
        self.assertTrue(any("검색량" in w for w in result["meta"]["warnings"]))
        self.assertEqual(result["trend_analysis"]["culture_trigger"]["keywords"], [])
        self.assertEqual(result["competitor_search"], [])
        kws = self._kws(result)
        self.assertEqual(kws["buy yakgwa near me"]["badge"], {"kind": "rising", "pct": 340})

    def test_low_reliability_country_warning(self):
        result = run_trend_usp(PRODUCT, "중국")
        self.assertEqual(result["meta"]["reliability"], "low")
        self.assertIn("바이두", result["meta"]["reliability_note_ko"])

    def test_unknown_country_uses_llm_profile(self):
        result = run_trend_usp(PRODUCT, "페루")
        self.assertEqual(result["meta"]["geo"], "PE")
        self.assertTrue(result["meta"]["is_profile_estimated"])

    def test_empty_product_name(self):
        with self.assertRaises(trend_usp.PipelineError):
            run_trend_usp({"name": " "}, "미국")

    # --- 화면 ------------------------------------------------------------------
    def test_flask_render(self):
        import app as web
        client = web.app.test_client()
        html = client.post("/", data={**PRODUCT, "country": "미국"}).get_data(as_text=True)
        for text in ["CULTURE TRIGGER", "kdrama yakgwa", "탐색 검증", "+340%", "-15%", "급상승 +340%",
                     "경쟁 제품 검색량", "×5.0", "Biscoff Cookies", "검색 확인", "AI 참고",
                     "No sticky syrup", "추가 정보를 입력하면 제공됩니다", "유통기한", "배지: 작년 같은 기간 대비 검색량 변화"]:
            self.assertIn(text, html, text)
        for removed in ["차별점은 입력한 제품 스펙만", "오프라인 전시 부스 기획", "데이터 부족"]:
            self.assertNotIn(removed, html, removed)

        html = client.post("/", data={**PITCH_PRODUCT, "country": "미국"}).get_data(as_text=True)
        self.assertIn("12 months", html)
        self.assertNotIn("24 months", html)
        self.assertEqual(client.get("/").status_code, 200)

    def test_flask_render_empty_clusters_folded(self):
        def chat(system, prompt, temperature, strategy=False):
            data = fake_chat_json(system, prompt, temperature, strategy)
            if "[현지 연관 검색어·연관 주제 목록]" in prompt:
                data["clusters"]["consumption_habit"]["items"] = []
            if "신호가 부족했습니다" in prompt:
                return {"probes": {}}
            return data
        self.chat_mock.side_effect = chat
        import app as web
        html = web.app.test_client().post("/", data={**PRODUCT, "country": "미국"}).get_data(as_text=True)
        self.assertIn("검색 신호가 확인되지 않은 분류", html)
        self.assertNotIn("HABIT &amp; TPO", html)


class UnitTest(unittest.TestCase):
    def test_compute_yoy(self):
        self.assertEqual(compute_yoy(weekly_series(40, 34))["yoy_pct"], -15)
        self.assertEqual(compute_yoy([1] * 30)["yoy_status"], "insufficient")
        self.assertEqual(compute_yoy(weekly_series(0.5, 10))["yoy_status"], "insufficient")

    def test_find_unsupported_certs(self):
        self.assertEqual(find_unsupported_certs("HACCP certified vegan snack", "HACCP, 비건"), [])
        self.assertEqual(find_unsupported_certs("Halal & organic", "HACCP"), ["할랄", "유기농"])

    def test_is_generic_target(self):
        for name in ["Korean Snacks", "Asian Sweets", "Korean Rice Cake", "instant coffee mix", "Cookies"]:
            self.assertTrue(is_generic_target(name), name)
        for name in ["Baklava", "Nescafé Taster's Choice 3in1", "Biscoff Cookies"]:
            self.assertFalse(is_generic_target(name), name)

    def test_headline_issues(self):
        self.assertEqual(headline_issues("No sticky syrup, just honey", "no sticky syrup"), [])
        self.assertTrue(any("상투어" in i for i in headline_issues("Experience Yakgwa sticky-free", "no sticky")))
        self.assertTrue(any("핵심 이점" in i for i in headline_issues("Great honey pastry", "individually wrapped")))
        self.assertEqual(headline_issues("ベタつかない蜂蜜菓子", "ベタつかない"), [])

    def test_validate_pitch_blocks(self):
        product = {"shelf_life": "상온 12개월", "moq_price": "MOQ 1,000박스, FOB 3.2달러"}
        blocks = validate_pitch_blocks([
            {"headline": "MOQ", "value": "1,000 boxes", "source_field": "moq_price"},
            {"headline": "FOB", "value": "$3.2", "source_field": "moq_price"},
            {"headline": "FOB", "value": "$3.5", "source_field": "moq_price"},
            {"headline": "Channel", "value": "Amazon", "source_field": "channel"},
        ], product)
        self.assertEqual([b["value"] for b in blocks], ["1,000 boxes", "$3.2"])


if __name__ == "__main__":
    unittest.main()

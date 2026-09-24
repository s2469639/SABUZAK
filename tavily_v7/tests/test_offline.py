"""네트워크 없이 v7(주요 사이트 우선 검색 + 충분성 판정 + 페르소나 부스 컨셉) 로직을 검증하는 오프라인 테스트.

OpenAI(_ask_json)와 Tavily(search)를 가짜 응답으로 바꿔서 실행한다.
    python -m unittest discover -s tests -v
"""

import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from research import (  # noqa: E402
    build_queries,
    check_minimums,
    decide_fallback,
    define_criteria,
    run_research,
    validate_domains,
    validate_followup,
)


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


class FakeTavily:
    def __init__(self):
        self.calls = []

    def search(self, query, include_raw_content=True, **params):
        self.calls.append({"query": query, **params})
        return {"results": fake_search_results(query, params)}


BOOTH_CALLS = []


def booth_payload(stage):
    """가짜 부스 기획안. stage별로 요약만 다르게 해서 어떤 단계 결과가 쓰였는지 확인한다."""
    return {
        "summary": f"{stage}: 휴대성과 커피 페어링을 앞세운 약과 부스",
        "positioning": {"target_buyer": "스페셜티 식료품 바이어", "core_message": "손에 안 묻는 한국 꿀과자"},
        "main_visual": {"concept_en": "Honey Heritage, No Sticky Fingers", "concept_ko": "끈적임 없는 꿀 전통",
                        "key_message": "테이크아웃 커피 옆 한입 간식",
                        "bullets": [{"text": "커피잔 옆 약과 클로즈업 백월", "basis": ["E2", "E99"]},
                                    {"text": "우드톤 카페 무드", "basis": ["기획"]}]},
        "slogan": {"main_en": "Sweet Heritage, Zero Sticky Fingers", "main_ko": "끈적임 없는 전통 단맛",
                   "sub_en": "Your coffee's new best friend", "sub_ko": "커피의 새 단짝",
                   "bullets": [{"text": "강점(손에 안 묻음)을 전면에", "basis": ["기업:강점"]}]},
        "signature_pairing": {"item": "아메리카노", "intent": "카페 페어링 수요",
                              "bullets": [{"text": "에스프레소 샷과 한입 약과", "basis": ["E2"]}]},
        "demonstration": {"title": "10초 언박싱 시연", "bullets": [{"text": "개별 포장 뜯어 바로 시식", "basis": ["기업:없는항목"]}]},
        "packaging": {"direction": "Grab & Go", "bullets": "문자열 불릿도 받아야 함"},
        "merchandising": {"zones": [{"name": "Hero Zone", "position": "중앙", "purpose": "대표 제품", "basis": ["E1"]},
                                   {"name": "", "position": "우측", "purpose": "이름 없는 존은 버림"}],
                          "bullets": [{"text": "눈높이 진열", "basis": []}]},
        "risks": [{"text": "화기 사용 허가 확인", "basis": []}],
        "questions": ["유통기한은 몇 개월인가요?"],
        "applied": ["시연을 10초 언박싱으로 단축"] if stage == "revised" else [],
    }


def fake_ask_json(client, prompt, temperature=0.0, model=None, system=None):
    p = prompt
    if "부스 컨셉 기획안을 작성하세요" in p:
        BOOTH_CALLS.append(("draft", model, system))
        return booth_payload("draft")
    if "바이어 입장에서 검토 의견을 주세요" in p:
        BOOTH_CALLS.append(("review", model, system))
        return {"overall": "가격 정보가 약함", "comments": [{"section": "demonstration", "issue": "시연이 길다",
                                                            "suggestion": "10초 안에"}]}
    if "바이어 검토 의견이 왔습니다" in p:
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


class V6PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "cache.db")
        self.tavily = FakeTavily()
        self.patches = [
            mock.patch.object(research, "get_clients", return_value=(object(), self.tavily)),
            mock.patch.object(research, "_ask_json", side_effect=fake_ask_json),
            mock.patch.object(research, "domain_exists", side_effect=lambda d: d != "made-up-news.pe"),
            mock.patch.object(research, "DEFAULT_DB_PATH", self.db),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_us(self, **kw):
        return run_research("약과", "United States", db_path=self.db, **kw)

    def test_main_queries_use_question_site_groups(self):
        r = self.run_us(exhibition_name="Summer Fancy Food Show", exhibition_website="specialtyfood.com")
        self.assertEqual(r["site_profile"]["source"], "curated")
        main = [q for q in r["query_details"] if q["tier"] == "main"]
        by_q = {}
        for q in main:
            by_q.setdefault(q["qid"], set()).update(q["include_domains"])
        us = research.MAIN_SITES["united states"]["groups"]
        self.assertEqual(by_q["Q1"], set(us["media"]))
        self.assertEqual(by_q["Q2"], set(us["retail"] + us["trade"]))
        self.assertEqual(by_q["Q3"], set(us["trade"] + us["public"]))
        self.assertEqual(by_q["KR"], set(research.KR_PUBLIC_DOMAINS))
        self.assertIn("specialtyfood.com", by_q["Q4"])
        for q in main:
            self.assertLessEqual(len(q["include_domains"]), research.MAX_DOMAINS_PER_QUERY)

    def test_fallback_decisions_code_and_ai(self):
        r = self.run_us()
        search = {c["qid"]: c["search"] for c in r["cards"]}
        # Q1: 코드 기준 + AI 체크리스트 통과 → 일반 웹 안 감
        self.assertFalse(search["Q1"]["used"])
        self.assertEqual(set(search["Q1"]["covered"]), {"구매 이유", "취식 상황", "불만"})
        # Q2: 출처 1곳 → 코드 기준 미달
        self.assertEqual((search["Q2"]["used"], search["Q2"]["stage"]), (True, "code"))
        self.assertTrue(any("출처 1곳" in x for x in search["Q2"]["reasons"]))
        # Q3: 코드 기준 통과, AI 판정에서 필수 측면 미충족
        self.assertEqual((search["Q3"]["used"], search["Q3"]["stage"]), (True, "ai"))
        self.assertTrue(any("필수 측면 '수입 인증 요건'" in x for x in search["Q3"]["reasons"]))
        # 보강 쿼리: site: 연산자 쿼리는 버리고, 제품군 용어가 들어간 것만
        self.assertIn("FDA certification korean dessert US", search["Q3"]["followup_queries"])
        self.assertFalse(any("site:" in q for q in search["Q3"]["followup_queries"]))
        # Q4: 주요 사이트 결과 없음 → 코드 기준 미달
        self.assertEqual(search["Q4"]["stage"], "code")
        self.assertEqual(r["stats"]["fallback_questions"], ["Q2", "Q3", "Q4"])

    def test_open_search_only_for_weak_questions(self):
        r = self.run_us()
        open_q = [q for q in r["query_details"] if q["tier"] == "open"]
        self.assertTrue(open_q)
        self.assertNotIn("Q1", {q["qid"] for q in open_q})          # 충분한 Q1은 일반 웹 검색 안 함
        self.assertTrue(all(not q["include_domains"] for q in open_q))
        for call in self.tavily.calls:                                # 일반 웹 검색엔 보고서 사이트·SNS 제외
            if not call.get("include_domains") and call.get("search_depth") != "basic":
                self.assertIn("facebook.com", call["exclude_domains"])

    def test_quotes_tiers_and_main_site_country_signal(self):
        r = self.run_us()
        q1 = [q for q in r["quotes"] if q["question"] == "Q1"]
        self.assertTrue(q1 and all(q["tier"] == "main" for q in q1))
        # nytimes 기사에는 국가명이 없지만 주요 사이트라 대상 국가로 인정
        ny = next(q for q in q1 if "Shoppers say" in q["quote"])
        self.assertEqual(ny["market"], "country")
        st = r["stats"]
        self.assertGreater(st["main_quotes"], 0)
        self.assertGreater(st["open_quotes"], 0)
        self.assertEqual(st["main_quotes"] + st["open_quotes"], st["quotes_used"])
        cards = {c["qid"]: c for c in r["cards"]}
        self.assertEqual(cards["Q1"]["open_quotes"], 0)
        self.assertGreater(cards["Q2"]["open_quotes"], 0)
        self.assertEqual(len(r["quotes"]), len({q["id"] for q in r["quotes"]}))  # 1·2차 합쳐도 id 중복 없음

    def test_ai_site_profile_validated_and_cached(self):
        r = run_research("약과", "Peru", db_path=self.db)
        sp = r["site_profile"]
        self.assertEqual(sp["source"], "ai")
        self.assertEqual(sp["groups"]["media"], ["elcomercio.pe", "larepublica.pe"])
        reasons = {d["domain"]: d["reason"] for d in sp["dropped"]}
        self.assertEqual(reasons["facebook.com"], "SNS")
        self.assertIn("DNS", reasons["made-up-news.pe"])
        self.assertEqual(reasons["kotra.or.kr"], "한국 공공기관(별도 검색)")
        self.assertIn("digesa.minsa.gob.pe", sp["groups"]["public"])
        r2 = run_research("약과", "Peru", db_path=self.db, exhibition_name="x")  # 리포트 캐시를 피해 프로필 캐시만 확인
        self.assertEqual(r2["site_profile"]["source"], "cache")

    def test_no_site_profile_falls_back_like_v5(self):
        with mock.patch.object(research, "get_site_profile",
                               return_value={"source": "none", "reviewed": False, "groups": {}, "dropped": []}):
            r = run_research("약과", "Peru", db_path=self.db)
        self.assertEqual(r["stats"]["fallback_questions"], ["Q1", "Q2", "Q3", "Q4"])
        self.assertTrue(all(c["search"]["stage"] == "code" for c in r["cards"]))

    def test_flask_render(self):
        import app as web
        with mock.patch.object(research, "DEFAULT_DB_PATH", self.db):
            html = web.app.test_client().post("/", data={"product_name": "약과", "country": "United States",
                                                         "strengths": "손에 안 묻는 식감"}).get_data(as_text=True)
        for text in ["v7 · 주요 사이트 우선 + 부스 컨셉 기획", "검색 범위", "부스 컨셉 기획안", "1. 메인 비주얼",
                     "Sweet Heritage, Zero Sticky Fingers", "기업: 강점", "기획 제안", "바이어 검토 의견 1건",
                     "기업에 확인하고 싶은 것", "15년차", "주요 사이트 자료만으로 충분", "일반 웹까지 검색",
                     "필수 측면 &#39;수입 인증 요건&#39; 자료 없음", "사전 등록 목록, 팀 검수 전",
                     "tier-main", "tier-open", "(필수)"]:
            self.assertIn(text, html, text)


class V7BoothTest(V6PipelineTest):
    """v7: 페르소나 부스 컨셉(B안), 근거 분류, 주요 사이트 표시 버그 수정, 요약 중복 제거."""

    def setUp(self):
        super().setUp()
        BOOTH_CALLS.clear()

    def run_with_profile(self, **kw):
        return run_research("약과", "United States", db_path=self.db,
                            company_profile={"strengths": "손에 안 묻는 식감", "price_range": "200g 6~7달러"}, **kw)

    def test_b_flow_draft_review_revise(self):
        r = self.run_with_profile()
        self.assertEqual([c[0] for c in BOOTH_CALLS], ["draft", "review", "revise"])
        self.assertTrue(all(c[1] == research.BOOTH_MODEL for c in BOOTH_CALLS))
        self.assertEqual([c[2] for c in BOOTH_CALLS],
                         [research.PLANNER_PERSONA, research.REVIEWER_PERSONA, research.PLANNER_PERSONA])
        b = r["booth"]
        self.assertEqual((b["mode"], b["stage"]), ("B", "revised"))
        self.assertTrue(b["summary"].startswith("revised"))
        self.assertEqual(b["applied"], ["시연을 10초 언박싱으로 단축"])
        self.assertEqual(b["review"]["comments"][0]["section"], "시연")
        self.assertEqual(list(b["sections"]), list(research.BOOTH_SECTIONS))

    def test_basis_classification_keeps_every_sentence(self):
        b = self.run_with_profile()["booth"]
        mv = b["sections"]["main_visual"]["bullets"]
        self.assertEqual(mv[0]["quote_ids"], ["E2"])                    # 없는 E99만 빠지고 문장은 유지
        self.assertTrue(mv[1]["is_idea"])
        self.assertEqual(b["sections"]["slogan"]["bullets"][0]["company"], ["강점"])
        self.assertTrue(b["sections"]["demonstration"]["bullets"][0]["is_idea"])   # 입력 안 한 기업 항목 → 기획 제안
        self.assertEqual(b["sections"]["packaging"]["bullets"][0]["text"], "문자열 불릿도 받아야 함")
        zones = b["sections"]["merchandising"]["zones"]
        self.assertEqual([z["name"] for z in zones], ["Hero Zone"])
        self.assertEqual(zones[0]["quote_ids"], ["E1"])
        self.assertEqual(b["risks"][0]["text"], "화기 사용 허가 확인")

    def test_a_mode_single_call(self):
        with mock.patch.object(research, "BOOTH_REVIEW", False):
            r = self.run_with_profile()
        self.assertEqual([c[0] for c in BOOTH_CALLS], ["draft"])
        self.assertEqual((r["booth"]["mode"], r["booth"]["stage"]), ("A", "draft"))
        self.assertIsNone(r["booth"]["reviewer_persona"])
        # A/B를 바꾸면 리포트 캐시를 새로 만든다
        r2 = self.run_with_profile()
        self.assertFalse(r2["from_cache"])
        self.assertEqual(r2["booth"]["mode"], "B")

    def test_review_failure_falls_back_to_draft(self):
        def failing(client, prompt, temperature=0.0, model=None, system=None):
            if "바이어 입장에서 검토 의견을 주세요" in prompt:
                raise RuntimeError("timeout")
            return fake_ask_json(client, prompt, temperature, model, system)
        with mock.patch.object(research, "_ask_json", side_effect=failing):
            r = self.run_with_profile()
        self.assertEqual(r["booth"]["stage"], "draft")
        self.assertTrue(r["booth"]["summary"].startswith("draft"))

    def test_outside_domain_in_main_search_marked_open(self):
        original = fake_search_results

        def with_intruder(query, params):
            results = original(query, params)
            if "nytimes.com" in (params.get("include_domains") or []):
                results.append(article("Q1", "juliabaird.com", "My review is that yakgwa tastes great in the United States."))
            return results
        with mock.patch(__name__ + ".fake_search_results", side_effect=with_intruder):
            r = self.run_us()
        src = next(x for x in r["sources"] if x["domain"] == "juliabaird.com")
        self.assertEqual(src["tier"], "open")
        q = next(x for x in r["quotes"] if "My review" in x["quote"])
        self.assertEqual(q["tier_label"], "일반 웹")
        self.assertEqual(next(c for c in r["cards"] if c["qid"] == "Q1")["diagnostics"].get("outside_main"), 1)

    def test_conclusion_not_repeated_in_points(self):
        def dup(client, prompt, temperature=0.0, model=None, system=None):
            data = fake_ask_json(client, prompt, temperature, model, system)
            if "해외시장조사 보고서를 쓰는 애널리스트" in prompt:
                ids = data["conclusion_ids"]
                data["points"] = [{"text": "요약 결론", "quote_ids": ids}, {"text": "다른 사실", "quote_ids": ids}]
            return data
        with mock.patch.object(research, "_ask_json", side_effect=dup):
            r = self.run_us()
        q1 = next(c for c in r["cards"] if c["qid"] == "Q1")
        self.assertEqual(q1["conclusion"]["text"], "요약 결론")
        self.assertEqual([p["text"] for p in q1["points"]], ["다른 사실"])


class UnitTest(unittest.TestCase):
    def test_validate_domains(self):
        with mock.patch.object(research, "domain_exists", side_effect=lambda d: d != "ghost.com"):
            kept, dropped = validate_domains(["https://www.Example.com/path", "example.com", "facebook.com",
                                              "kati.net", "bad domain", "ghost.com", "grandviewresearch.com"])
        self.assertEqual(kept, ["example.com"])
        self.assertEqual({d["domain"]: d["reason"] for d in dropped},
                         {"facebook.com": "SNS", "kati.net": "한국 공공기관(별도 검색)", "bad domain": "도메인 형식 아님",
                          "ghost.com": "DNS 조회 실패(존재하지 않음)", "grandviewresearch.com": "보고서 판매 사이트"})

    def test_define_criteria_normalizes(self):
        with mock.patch.object(research, "_ask_json", side_effect=fake_ask_json):
            c = define_criteria(object(), "약과", "United States", {})
        self.assertEqual([a["essential"] for a in c["Q2"]], [True, False, False])
        self.assertEqual(c["Q2"][2]["search_hint"], "")                 # 한글 힌트 제거
        self.assertEqual([a["label_ko"] for a in c["Q4"]], [x[1] for x in research.DEFAULT_ASPECTS["Q4"]])
        with mock.patch.object(research, "_ask_json", side_effect=RuntimeError("down")):
            c = define_criteria(object(), "약과", "United States", {})
        self.assertEqual(len(c["Q1"]), 3)

    def test_check_minimums(self):
        q = lambda i, sid, market="country", scope="category", stale=False: {  # noqa: E731
            "id": i, "question": "Q2", "source_ids": [sid], "market": market, "scope": scope, "is_stale": stale}
        self.assertEqual(check_minimums("Q2", [q("E1", 1), q("E2", 2)]), [])
        self.assertEqual(len(check_minimums("Q2", [])), 2)   # 발췌 0건: 수량·출처 사유만 (권역 사유는 안 붙임)
        self.assertTrue(any("출처 1곳" in r for r in check_minimums("Q2", [q("E1", 1), q("E2", 1)])))
        self.assertTrue(any("대상 국가" in r for r in check_minimums("Q2", [q("E1", 1, "region"), q("E2", 2, "region")])))
        self.assertTrue(any("제품·제품군" in r for r in check_minimums("Q2", [q("E1", 1, scope="kfood"), q("E2", 2, scope="kfood")])))
        self.assertTrue(any("오래된" in r for r in check_minimums("Q2", [q("E1", 1, stale=True), q("E2", 2, stale=True)])))

    def test_validate_followup(self):
        terms = {"product_match": ["약과", "yakgwa"], "category_terms": ["korean dessert"], "kfood_terms": ["korean food"],
                 "category_en": "korean dessert"}
        taken = set()
        self.assertEqual(validate_followup("yakgwa price walmart", terms, taken), "yakgwa price walmart")
        self.assertIsNone(validate_followup("yakgwa price walmart", terms, taken))     # 중복
        self.assertIsNone(validate_followup("site:fda.gov yakgwa rules", terms, taken))
        self.assertIsNone(validate_followup("import rules usa", terms, taken))        # 제품·제품군 용어 없음
        self.assertIsNone(validate_followup("yakgwa", terms, taken))                  # 너무 짧음

    def test_decide_fallback_coverage_ratio(self):
        criteria = {"Q1": [{"id": "Q1-1", "label_ko": "A", "essential": True, "search_hint": "why"},
                           {"id": "Q1-2", "label_ko": "B", "essential": False, "search_hint": ""},
                           {"id": "Q1-3", "label_ko": "C", "essential": False, "search_hint": ""}]}
        terms = {"selected": ["yakgwa"], "product_match": ["약과", "yakgwa"], "category_terms": [], "kfood_terms": [],
                 "category_en": "dessert", "local_country": "United States"}
        # 필수 충족했지만 1/3 → 기준(2개) 미달
        d = decide_fallback("Q1", criteria, [], {"Q1": {"covered": {"Q1-1": ["E1"]}, "followups": []}}, terms, set())
        self.assertTrue(d["used"])
        self.assertIn("측면 충족 1/3 (기준 2개)", d["reasons"])
        self.assertEqual(d["followup_queries"], [])            # 빠진 측면(B, C)에 현지어 힌트가 없어서 조립 안 됨
        # 2/3 + 필수 충족 → 충분
        d = decide_fallback("Q1", criteria, [], {"Q1": {"covered": {"Q1-1": ["E1"], "Q1-2": ["E2"]}, "followups": []}},
                            terms, set())
        self.assertFalse(d["used"])
        # AI 판정 실패 → 보수적으로 일반 웹, 힌트로 보강 쿼리 조립
        d = decide_fallback("Q1", criteria, [], {}, terms, set())
        self.assertEqual((d["used"], d["stage"]), (True, "ai"))
        self.assertEqual(d["followup_queries"], ["yakgwa why United States"])

    def test_build_open_queries_limited_to_weak(self):
        terms = {"words": dict(research.DEFAULT_WORDS), "local_country": "United States", "selected": ["yakgwa"],
                 "product_match": ["약과", "yakgwa"], "category_terms": ["korean dessert"], "kfood_terms": ["korean food"],
                 "category_en": "korean dessert", "country_ko": "미국", "category_ko": "", "region_en": "North America"}
        qs = build_queries(terms, "약과", "United States", None, None, tier="open", qids=["Q2"],
                           followups={"Q2": ["yakgwa price costco"]})
        self.assertEqual({q["qid"] for q in qs}, {"Q2"})
        self.assertIn("yakgwa price costco", [q["query"] for q in qs])


if __name__ == "__main__":
    unittest.main()

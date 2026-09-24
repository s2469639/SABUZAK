#!/usr/bin/env python3
"""박람회 준비 데스크 리서치 CLI (v7.0, 주요 사이트 우선 검색 + 페르소나 부스 컨셉 기획).

    python cli.py --product 김부각 --country Germany
    python cli.py --product 김부각 --country Germany --exhibition ANUGA --website anuga.com --strengths "찹쌀 코팅 수작업"
    python cli.py --product 김부각 --country Germany --audit 10      # 발췌 무작위 점검
    python cli.py --product 김부각 --country Germany --debug         # 제외·삭제 내역까지 출력
"""

import argparse
import random
import sys

from env_setup import ensure_required_keys
from research import BOOTH_SECTIONS, run_research


def main():
    p = argparse.ArgumentParser(description="박람회 준비 데스크 리서치")
    p.add_argument("--product", required=True)
    p.add_argument("--country", required=True)
    p.add_argument("--exhibition")
    p.add_argument("--website")
    p.add_argument("--strengths")
    p.add_argument("--ingredients")
    p.add_argument("--certifications")
    p.add_argument("--price-range")
    p.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조사")
    p.add_argument("--audit", type=int, metavar="N", help="발췌 N개를 무작위로 뽑아 링크와 함께 출력")
    p.add_argument("--debug", action="store_true", help="쿼리, 제외 출처, 검사에서 지운 문장까지 출력")
    a = p.parse_args()

    ensure_required_keys()
    try:
        r = run_research(a.product, a.country, exhibition_name=a.exhibition, exhibition_website=a.website,
                         company_profile={"strengths": a.strengths, "ingredients": a.ingredients,
                                          "certifications": a.certifications, "price_range": a.price_range},
                         force=a.force)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)

    quotes = {q["id"]: q for q in r["quotes"]}
    sources = {s["id"]: s for s in r["sources"]}
    t, s = r["terms"], r["stats"]

    def ids(xs):
        return " ".join(f"[{x}]" for x in xs)

    print("=" * 70)
    print(f"[{r['country']}] {r['product_name']} 박람회 준비 리서치  ({r['version']}, 캐시: {r['from_cache']})")
    print("=" * 70)
    print(f"제품 용어: {', '.join(t['selected']) or '검색 결과에서 확인된 용어 없음'}  / 권역: {t['region_ko'] or '미상'}")
    print(f"출처 {s['sources_found']}건 / 사용 발췌 {s['quotes_used']}건 (대상 국가 {s['country_quotes']}, 권역 {s['region_quotes']})")
    print(f"제외: 보고서 사이트·SNS {s['excluded_source']} / 다른 시장 {s['market_other']} / "
          f"원문(본문)에 없음 {s['not_in_source']} / 범위 밖 {s['off_scope']}")
    print(f"주의: 오래된 자료 발췌 {s['stale_quotes']} / 번역 숫자 불일치 {s['translation_warnings']}")
    sp = r["site_profile"]
    print(f"검색 범위: 주요 사이트 발췌 {s['main_quotes']}건(출처 {s['main_sources']}) / "
          f"일반 웹 발췌 {s['open_quotes']}건(출처 {s['open_sources']}) / "
          f"일반 웹으로 넓힌 질문: {', '.join(s['fallback_questions']) or '없음'}")
    print(f"주요 사이트 목록: {sp['source']}" + (" (팀 검수 전)" if sp["source"] == "curated" and not sp["reviewed"] else "")
          + " | " + " / ".join(f"{g}: {len(ds)}개" for g, ds in sp["groups"].items()))

    for c in r["cards"]:
        print(f"\n■ {c['qid']}. {c['title']} — {c['question']}")
        sr = c["search"]
        if sr["used"]:
            print(f"  [검색] 주요 사이트 부족 → 일반 웹 ({'코드 기준' if sr['stage'] == 'code' else 'AI 체크리스트'}): "
                  + "; ".join(sr["reasons"]))
            if sr["followup_queries"]:
                print(f"         보강 쿼리: {' / '.join(sr['followup_queries'])}")
        else:
            print("  [검색] 주요 사이트 자료만으로 충분")
        print("  [체크리스트] " + ", ".join(("✓" if a["label_ko"] in sr["covered"] else "·") + a["label_ko"]
                                          + ("(필수)" if a["essential"] else "") for a in c["criteria"]))
        if c["notice"]:
            print(f"  ⚠️  {c['notice']}")
        if c["conclusion"]:
            print(f"  결론(AI 요약): {c['conclusion']['text']} {ids(c['conclusion']['quote_ids'])}")
        for pt in c["points"]:
            print(f"   - {pt['text']} {ids(pt['quote_ids'])}")
        if c["interpretation"]:
            print(f"  AI 해석: {c['interpretation']}")
        if c["gaps"]:
            print(f"  확인 필요: {c['gaps']}")
        for qid in c["quote_ids"]:
            q = quotes[qid]
            src = sources[q["source_ids"][0]]
            badges = [q["scope_label"], q["market_label"], q["tier_label"]]
            if q["is_public_kr"]:
                badges.append("한국 공공기관")
            if q["is_stale"]:
                badges.append(f"오래된 자료({q['year']})")
            if q["translation_warning"]:
                badges.append("번역 확인 필요")
            print(f"    [{qid}] ({', '.join(badges)}) \"{q['quote']}\"")
            print(f"          → {q['translation_ko']}")
            print(f"          🔗 {src['url']} ({q['year'] or '연도 미상'})")
        if a.debug:
            print(f"  [진단] {c['diagnostics']}")
            for d in c["dropped"]:
                print(f"  [지운 문장] {d['reason']}: {d['text']}")

    b = r["booth"]
    if b:
        print("\n" + "=" * 70)
        mode = "기획자 초안 → 바이어 검토 → 수정" if b["mode"] == "B" else "기획자 1회 생성"
        print(f"■ 부스 컨셉 기획안 ({mode}, {b['model']})")
        print("=" * 70)
        if not b["has_product_evidence"]:
            print("  ⚠️  제품 자체에 대한 현지 자료 없이 제품군·한국 식품 자료를 바탕으로 한 기획입니다.")
        print(f"  요약: {b['summary']}")
        pos = b["positioning"]
        if pos["target_buyer"] or pos["core_message"]:
            print(f"  타깃 바이어: {pos['target_buyer']} / 핵심 메시지: {pos['core_message']}")

        def basis(x):
            tags = list(x["quote_ids"]) + [f"기업:{c}" for c in x["company"]]
            return " [" + ", ".join(tags) + "]" if tags else " [기획 제안]"

        for key, (title, title_en) in BOOTH_SECTIONS.items():
            sec = b["sections"][key]
            print(f"\n  {title} ({title_en})")
            for label, field in (("컨셉", "concept_en"), ("", "concept_ko"), ("메인", "main_en"), ("", "main_ko"),
                                 ("서브", "sub_en"), ("", "sub_ko"), ("아이템", "item"), ("기획 의도", "intent"),
                                 ("시연", "title"), ("방향", "direction"), ("핵심 메시지", "key_message")):
                if sec.get(field):
                    print(f"    {label + ': ' if label else '      '}{sec[field]}")
            for z in sec.get("zones", []):
                print(f"    [존] {z['name']} ({z['position']}): {z['purpose']}{basis(z)}")
            for x in sec["bullets"]:
                print(f"    - {x['text']}{basis(x)}")
        if b["risks"]:
            print("\n  확인할 점")
            for x in b["risks"]:
                print(f"    - {x['text']}{basis(x)}")
        if b["questions"]:
            print("\n  기업에 확인하고 싶은 것")
            for q in b["questions"]:
                print(f"    - {q}")
        if b["review"]["comments"]:
            print(f"\n  바이어 검토: {b['review']['overall']}")
            for c in b["review"]["comments"]:
                print(f"    - [{c['section']}] {c['issue']} → {c['suggestion']}")
            for x in b["applied"]:
                print(f"    ✓ 반영: {x}")

    if a.debug:
        print("\n[쿼리]")
        for q in r["query_details"]:
            scope = f" (사이트 {len(q['include_domains'])}곳 한정)" if q["include_domains"] else ""
            print(f"  - [{q['tier']}/{q['qid']}] {q['query']}{scope}")
        print("\n[제외된 출처]")
        for e in r["excluded_sources"]:
            print(f"  - {e['reason']}: {e['url']}")
        print("\n[다른 시장으로 판정된 출처]")
        for src in r["sources"]:
            if src.get("market") == "other":
                print(f"  - {src['url']}")

    if a.audit and r["quotes"]:
        print("\n" + "=" * 70)
        print("점검: 발췌는 원문 대조를 통과했습니다. 번역·범위·시장 배지가 맞는지 확인하세요.")
        for q in random.sample(r["quotes"], min(a.audit, len(r["quotes"]))):
            print(f"\n[{q['id']}] ({q['scope_label']}, {q['market_label']}) {q['quote']}"
                  f"\n  번역: {q['translation_ko']}\n  🔗 {sources[q['source_ids'][0]]['url']}")


if __name__ == "__main__":
    main()

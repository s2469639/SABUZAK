#!/usr/bin/env python3
"""박람회 준비 데스크 리서치 CLI (v5.0).

    python cli.py --product 김부각 --country Germany
    python cli.py --product 김부각 --country Germany --exhibition ANUGA --website anuga.com --strengths "찹쌀 코팅 수작업"
    python cli.py --product 김부각 --country Germany --audit 10      # 발췌 무작위 점검
    python cli.py --product 김부각 --country Germany --debug         # 제외·삭제 내역까지 출력
"""

import argparse
import random
import sys

from env_setup import ensure_required_keys
from research import run_research


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

    for c in r["cards"]:
        print(f"\n■ {c['qid']}. {c['title']} — {c['question']}")
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
            badges = [q["scope_label"], q["market_label"]]
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
        print("\n■ 부스 기획 포인트 (AI 제안)")
        if not b["has_product_evidence"]:
            print("  ⚠️  제품 자체에 대한 현지 근거 없이 제품군·한국 식품 자료로 만든 제안입니다.")
        print(f"  핵심 메시지: {b['key_message']}")
        for x in b["reasons"]:
            print(f"   근거: {x['text']} {ids(x['quote_ids'])}")
        for x in b["ideas"]:
            print(f"   아이디어: {x['text']} {ids(x['quote_ids'])}")

    if a.debug:
        print("\n[쿼리]")
        for q in r["queries"]:
            print(f"  - {q}")
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

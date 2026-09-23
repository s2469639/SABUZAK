#!/usr/bin/env python3
"""박람회 준비 데스크 리서치 CLI (v4).

    python cli.py --product 김부각 --country "United States"
    python cli.py --product 김부각 --country Germany --exhibition ANUGA --website anuga.com \
        --strengths "찹쌀 코팅 수작업" --certifications HACCP
    python cli.py --product 김부각 --country Germany --audit 10     # 발췌 무작위 점검
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

    def ids(xs):
        return " ".join(f"[{x}]" for x in xs)

    print("=" * 64)
    print(f"[{r['country']}] {r['product_name']} 박람회 준비 리서치  (캐시: {r['from_cache']})")
    print("=" * 64)
    t = r["terms"]
    print(f"조사 용어: {', '.join(t['selected'])}" + ("" if t["is_verified"] else "  (⚠️ 검증 통과 용어 없음)"))
    s = r["stats"]
    print(f"출처 {s['sources_found']}건 중 {s['sources_used']}건 사용 / 원문 확인 발췌 {s['quotes_verified']}건 / "
          f"원문에 없어 버린 발췌 {s['quotes_rejected']}건 / 대상 외 자료 {s['unusable_sources']}건")

    for c in r["cards"]:
        print(f"\n■ {c['qid']}. {c['title']} — {c['question']}")
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
            print(f"    [{qid}] \"{q['quote']}\"")
            print(f"          → {q['translation_ko']}")
            print(f"          🔗 {src['url']} ({src.get('published_date') or '날짜 미상'}, 출처 {len(q['source_ids'])}곳)")

    b = r["booth"]
    if b:
        print("\n■ 부스 기획 포인트 (AI 제안)")
        print(f"  핵심 메시지: {b['key_message']}")
        for x in b["reasons"]:
            print(f"   근거: {x['text']} {ids(x['quote_ids'])}")
        for x in b["ideas"]:
            print(f"   아이디어: {x['text']} {ids(x['quote_ids'])}")

    if a.audit and r["quotes"]:
        print("\n" + "=" * 64)
        print("점검: 발췌는 원문 대조를 통과했으므로, 번역과 요약이 발췌 뜻과 맞는지 확인하세요.")
        for q in random.sample(r["quotes"], min(a.audit, len(r["quotes"]))):
            print(f"\n[{q['id']}] {q['quote']}\n  번역: {q['translation_ko']}\n  🔗 {sources[q['source_ids'][0]]['url']}")


if __name__ == "__main__":
    main()

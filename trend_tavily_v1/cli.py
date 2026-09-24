#!/usr/bin/env python3
"""터미널에서 검색 트렌드 + 웹 자료 결합 진단을 실행한다.

예:
    python cli.py --name 약과 --country 미국 --strengths "손에 안 묻는 식감" --certifications HACCP
    python cli.py --name 약과 --country 미국 --exhibition "Summer Fancy Food Show" --json
"""

import argparse
import json
import logging

from combined import run_combined, tavily_env, trend_usp


def print_summary(combo: dict) -> None:
    links = combo["links"]
    s = links["summary"]
    print(f"\n=== 결합 진단 ({combo['country_en']}) ===")
    if combo["trend_error"]:
        print(f"⚠️  검색 트렌드 분석 실패: {combo['trend_error']}")
    if combo["tavily_error"]:
        print(f"⚠️  웹 자료 조사 실패: {combo['tavily_error']}")
    print(f"USP 경쟁 제품 웹 출처 확인: {s['usp_rows_web_confirmed']}/{s['usp_rows']} | "
          f"경쟁 후보 웹 확인: {s['competitors_web_confirmed']}/{s['competitors']} | "
          f"웹 발췌 {s['web_quotes']}건(대상 국가 {s['web_country_quotes']}건)")

    trend = combo["trend"]
    if trend:
        print("\n[USP × 웹 출처]")
        for row in trend["usp_matrix"]:
            web = links["competitors"].get(row["competitor_id"])
            mark = "웹 출처 확인" if web else "웹 출처 없음"
            print(f"- {row['target']} [{trend_usp.EVIDENCE_LABELS_KO[row['target_evidence']]} / {mark}]"
                  f" → {row['pitch_headline']}")
            if web:
                w = web["quotes"][0]
                print(f"    \"{w['quote'][:120]}\" ({w['domain']})")

    for title, key in (("웹 자료: 현지 소비자", "consumer"), ("웹 자료: 경쟁 제품", "competition"),
                       ("웹 자료: 바이어·유통", "buyer"), ("웹 자료: 박람회", "exhibition")):
        if links[key]:
            print(f"\n[{title}]")
            for p in links[key]:
                src = ", ".join(r["domain"] for r in p["refs"][:2])
                print(f"- {p['text']}" + (f" ({src})" if src else ""))
    if links["tavily_booth"]:
        print(f"\n[웹 자료 기반 부스 핵심 메시지] {links['tavily_booth']['key_message']}")


def main():
    parser = argparse.ArgumentParser(description="검색 트렌드 + 웹 자료 결합 진단")
    parser.add_argument("--name", required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--strengths", default="")
    parser.add_argument("--ingredients", default="")
    parser.add_argument("--certifications", default="")
    parser.add_argument("--price", default="")
    parser.add_argument("--shelf-life", dest="shelf_life", default="")
    parser.add_argument("--pack-format", dest="pack_format", default="")
    parser.add_argument("--moq-price", dest="moq_price", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--known-competitors", dest="known_competitors", default="")
    parser.add_argument("--exhibition", default="", help="박람회명 (웹 자료 조사용)")
    parser.add_argument("--exhibition-website", dest="exhibition_website", default="")
    parser.add_argument("--force", action="store_true", help="캐시 무시")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    tavily_env.ensure_required_keys()
    product = {k: getattr(args, k) for k in trend_usp.PRODUCT_FIELDS}
    try:
        combo = run_combined(product, args.country, args.exhibition, args.exhibition_website, force=args.force)
    except (trend_usp.PipelineError, ValueError) as e:
        print(f"오류: {e}")
        raise SystemExit(1)
    if args.json:
        print(json.dumps(combo, ensure_ascii=False, indent=2, default=str))
    else:
        print_summary(combo)


if __name__ == "__main__":
    main()

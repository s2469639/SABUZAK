#!/usr/bin/env python3
"""터미널에서 트렌드·USP 분석을 실행한다.

예:
    python cli.py --name 약과 --country 미국 --strengths "겉바속쫀, 꿀 코팅" \
        --ingredients "밀가루, 꿀, 참기름" --certifications HACCP --price "4~5 USD / 200g"
    python cli.py --name 김밥 --country 일본 --json      # 전체 JSON 출력
"""

import argparse
import json
import logging

from env_setup import ensure_required_keys
from trend_usp import CLUSTER_KEYS, CLUSTER_META, FUNNEL_STAGES_KO, PipelineError, run_trend_usp


def _badge(kw: dict) -> str:
    if kw["yoy_status"] == "estimated":
        return "AI추정"
    if kw["yoy_pct"] is None:
        return "데이터 부족"
    return f"전년比 {kw['yoy_pct']:+d}%"


def print_summary(result: dict) -> None:
    meta = result["meta"]
    print(f"\n=== {result['product_info']['name']} → {meta['country_ko']} ({meta['geo']}) ===")
    print(f"검색 언어: {', '.join(meta['languages'])} | 데이터: {meta['data_level_label_ko']} "
          f"| Google 신뢰도: {meta['reliability_label_ko']}")
    print("시드 검색어: " + ", ".join(f"{s['keyword']}({s['ko']})" for s in meta["seed_keywords"]))
    for w in ([meta["reliability_note_ko"]] if meta["reliability_note_ko"] else []) + meta["warnings"]:
        print(f"⚠️  {w}")

    print("\n[1. 4단계 클러스터링]")
    for key in CLUSTER_KEYS:
        c = result["trend_analysis"][key]
        print(f"\n■ {CLUSTER_META[key]['label']} - {CLUSTER_META[key]['title_ko']} [{c['tag']}]")
        print(f"  {c['summary']}")
        for kw in c["keywords"]:
            stage = f" <{FUNNEL_STAGES_KO[kw['stage']]}>" if kw.get("stage") else ""
            hot = " 🔥급등" if kw["is_breakout"] else ""
            print(f"   - {kw['keyword']} ({kw['ko']}){stage}  {_badge(kw)}{hot}")
        if c["insight"]:
            print(f"  → {c['insight']}")

    print("\n[2. USP 매트릭스]")
    for row in result["usp_matrix"]:
        print(f"\n■ {row['target']} ({row['target_ko']})")
        print(f"  한계: {row['weakness_ko']}")
        print(f"  차별점: {row['our_usp_ko']}  (근거: {', '.join(row['evidence'])})")
        print(f"  피칭: {row['pitch_headline']}  / {row['pitch_headline_ko']}")
        if row["unsupported_certs"]:
            print(f"  ⚠️  입력하지 않은 인증 언급: {', '.join(row['unsupported_certs'])}")

    print("\n[3. 부스 컨셉]")
    for key, item in result["booth_concept"].items():
        print(f"\n■ {key}: {item['title']} ({item['title_ko']})")
        if item.get("slogan"):
            print(f"  슬로건: {item['slogan']} / {item['slogan_ko']}")
        print(f"  {item['description_ko']}")


def main():
    parser = argparse.ArgumentParser(description="연관 검색어 기반 시장 트렌드 & USP & 부스 컨셉 진단")
    parser.add_argument("--name", required=True, help="제품명 (예: 약과)")
    parser.add_argument("--country", required=True, help="진출 대상 국가 (예: 미국, 일본, DE)")
    parser.add_argument("--strengths", default="", help="제품 강점")
    parser.add_argument("--ingredients", default="", help="주요 원료")
    parser.add_argument("--certifications", default="", help="보유 인증")
    parser.add_argument("--price", default="", help="가격대")
    parser.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조회")
    parser.add_argument("--json", action="store_true", help="전체 결과 JSON 출력")
    parser.add_argument("--debug", action="store_true", help="상세 로그 출력")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ensure_required_keys()

    product = {k: getattr(args, k) for k in ("name", "strengths", "ingredients", "certifications", "price")}
    try:
        result = run_trend_usp(product, args.country, use_cache=not args.force)
    except PipelineError as e:
        print(f"오류: {e}")
        raise SystemExit(1)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_summary(result)


if __name__ == "__main__":
    main()

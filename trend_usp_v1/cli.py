#!/usr/bin/env python3
"""터미널에서 트렌드·USP 분석을 실행한다.

예:
    python cli.py --name 약과 --country 미국 --strengths "겉바속쫀, 꿀 코팅" \
        --ingredients "밀가루, 꿀, 참기름" --certifications HACCP --price "4~5 USD / 200g" \
        --shelf-life "상온 12개월" --pack-format "개별 포장 30g × 10입"
    python cli.py --name 김밥 --country 일본 --json      # 전체 JSON 출력
"""

import argparse
import json
import logging

from env_setup import ensure_required_keys
from trend_usp import (
    CLUSTER_KEYS,
    CLUSTER_META,
    EVIDENCE_LABELS_KO,
    FUNNEL_STAGES_KO,
    PipelineError,
    run_trend_usp,
)


def _badge(kw: dict) -> str:
    badge = kw.get("badge")
    if not badge:
        return ""
    if badge["kind"] == "yoy":
        return f"전년比 {badge['pct']:+d}%"
    return f"급상승 +{badge['pct']}%"


def print_summary(result: dict) -> None:
    meta = result["meta"]
    print(f"\n=== {result['product_info']['name']} → {meta['country_ko']} ({meta['geo']}) ===")
    print(f"검색 언어: {', '.join(meta['languages'])} | 데이터: {meta['data_level_label_ko']} "
          f"| Google 신뢰도: {meta['reliability_label_ko']}")
    print("시드: " + ", ".join(s["keyword"] for s in meta["seed_keywords"])
          + " | 카테고리: " + (", ".join(s["keyword"] for s in meta["category_keywords"]) or "-"))
    for w in ([meta["reliability_note_ko"]] if meta["reliability_note_ko"] else []) + meta["warnings"]:
        print(f"⚠️  {w}")

    print("\n[1. 4단계 클러스터링]")
    empty = []
    for key in CLUSTER_KEYS:
        c = result["trend_analysis"][key]
        if not c["keywords"]:
            empty.append(CLUSTER_META[key]["short_ko"])
            continue
        tag = f" [{c['tag']}]" if c["tag"] else ""
        print(f"\n■ {CLUSTER_META[key]['label']} - {CLUSTER_META[key]['title_ko']}{tag}")
        if c["summary"]:
            print(f"  {c['summary']}")
        for kw in c["keywords"]:
            stage = f" <{FUNNEL_STAGES_KO[kw['stage']]}>" if kw.get("stage") else ""
            hot = " 🔥급등" if kw["is_breakout"] else ""
            print(f"   - {kw['keyword']} ({kw.get('ko', '')}){stage} [{EVIDENCE_LABELS_KO[kw['evidence']]}]"
                  f"  {_badge(kw)}{hot}")
        if c["insight"]:
            print(f"  → {c['insight']}")
    if result["competitor_search"]:
        print("\n  경쟁 제품 검색량 (우리 제품 = 1): " + ", ".join(
            f"{c['name']} " + ("우리보다 훨씬 큼" if c["anchor_zero"] else f"×{c['vs_anchor']}")
            for c in result["competitor_search"]))
    if empty:
        print(f"\n  검색 신호 없음: {', '.join(empty)}")

    print("\n[2. USP 매트릭스]")
    for row in result["usp_matrix"]:
        print(f"\n■ {row['target']} ({row['target_ko']}) [{EVIDENCE_LABELS_KO[row['target_evidence']]}]"
              f" 가격: {row['price_local'] or '-'}")
        print(f"  불만: {row['consumer_pain_ko']}")
        print(f"  해결: {row['our_fix_ko']}  (근거: {', '.join(row['evidence']) or '-'})")
        print(f"  헤드라인: {row['pitch_headline']}  / {row['pitch_headline_ko']}")
        if row["unsupported_certs"]:
            print(f"  ⚠️  입력하지 않은 인증 언급: {', '.join(row['unsupported_certs'])}")

    print("\n[3. 부스 컨셉]")
    booth = result["booth_concept"]
    b = booth["headline_slogan"]
    print(f"\n■ 슬로건: {b['slogan']} / {b['slogan_ko']}\n  보조: {b['sub_copy']}\n  비주얼: {b['key_visual_ko']}")
    b = booth["sampling_strategy"]
    print(f"\n■ 비교 시식: {b['title']} - 비교 대상 {b['compare_with'] or '-'}, {b['serving_ko']}"
          f"\n  멘트: {b['staff_line']} / {b['staff_line_ko']}\n  받아낼 것: {b['collect_ko']}")
    if booth["pitching_wall"]:
        print("\n■ 피칭 월: " + " | ".join(f"{blk['value']} {blk['headline']}" for blk in booth["pitching_wall"]["blocks"]))
    else:
        print("\n■ 피칭 월: 추가 정보(유통기한·포장·MOQ·유통채널)를 입력하면 제공")
    b = booth["packaging_display"]
    print(f"\n■ 진열: {' / '.join(b['layout_ko'])}\n  POP: {b['pop_copy']} / {b['pop_copy_ko']}")


def main():
    parser = argparse.ArgumentParser(description="연관 검색어 기반 시장 트렌드 & USP & 부스 컨셉 진단")
    parser.add_argument("--name", required=True, help="제품명 (예: 약과)")
    parser.add_argument("--country", required=True, help="진출 대상 국가 (예: 미국, 일본, DE)")
    parser.add_argument("--strengths", default="", help="제품 강점")
    parser.add_argument("--ingredients", default="", help="주요 원료")
    parser.add_argument("--certifications", default="", help="보유 인증")
    parser.add_argument("--price", default="", help="가격대")
    parser.add_argument("--shelf-life", dest="shelf_life", default="", help="유통기한 (피칭 월용)")
    parser.add_argument("--pack-format", dest="pack_format", default="", help="포장 단위·형태 (피칭 월용)")
    parser.add_argument("--moq-price", dest="moq_price", default="", help="MOQ·납품가 (피칭 월용)")
    parser.add_argument("--channel", default="", help="타깃 유통채널 (피칭 월용)")
    parser.add_argument("--known-competitors", dest="known_competitors", default="", help="알고 있는 경쟁 제품·가격")
    parser.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조회")
    parser.add_argument("--json", action="store_true", help="전체 결과 JSON 출력")
    parser.add_argument("--debug", action="store_true", help="상세 로그 출력")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ensure_required_keys()

    product = {k: getattr(args, k) for k in ("name", "strengths", "ingredients", "certifications", "price",
                                              "shelf_life", "pack_format", "moq_price", "channel",
                                              "known_competitors")}
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

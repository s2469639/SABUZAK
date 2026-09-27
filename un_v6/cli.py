#!/usr/bin/env python3
"""un_comtrade.py 단독 실행/테스트용 CLI.

사전 준비:
    pip install -r requirements.txt
    .env 파일에 OPENAI_API_KEY, UN_COMTRADE_SUBSCRIPTION_KEY 설정
    (없으면 실행 시 터미널에서 물어봄. Comtrade 키는 comtradeplus.un.org에서
    무료로 가입하면 자동 승인됨)

실행:
    python cli.py --hscode 190590 --country Vietnam
    python cli.py --hscode 190590 --country VNM --years 2020 2021 2022
    python cli.py --hscode 190590 --country VNM --debug   # 원본 응답 컬럼 확인용

    # 여러 후보국을 "성장률 x 한국 점유율" 매트릭스로 한 번에 비교
    python cli.py --hscode 190590 --matrix                       # 글로벌 수입 상위 10개국 자동 비교
    python cli.py --hscode 190590 --matrix --candidates VNM THA PHL

--debug: UN Comtrade 응답 DataFrame의 실제 컬럼명을 그대로 출력합니다.
    이 코드는 실 서버 응답을 확인 못 한 채로 문서 기준으로 짰기 때문에,
    처음 실행했을 때 컬럼 이름이 다르면 이 옵션으로 확인해서 알려주세요.
"""

import argparse
import sys

from env_setup import ensure_required_keys
from un_comtrade import get_config, get_market_research, get_multi_country_comparison


def debug_dump(hscode, country):
    """원본 API 응답 컬럼을 그대로 찍어서 스키마를 확인하는 용도."""
    import un_comtrade as uc

    openai_client, subscription_key = get_config()
    iso3 = uc.resolve_iso3(country)
    year = 2023
    print(f"[디버그] reporterCode={iso3} 로 {year}년 데이터 원본 조회...")
    df = uc.comtradeapicall.getFinalData(
        subscription_key, typeCode="C", freqCode="A", clCode="HS", period=str(year),
        reporterCode=uc.iso3_to_numeric(iso3), cmdCode=hscode, flowCode="M",
        partnerCode=None, partner2Code=None, customsCode=None, motCode=None,
        maxRecords=10, format_output="JSON", aggregateBy=None,
        breakdownMode="classic", countOnly=None, includeDesc=True,
    )
    if df is None or df.empty:
        print("빈 응답입니다 (해당 연도/국가/HS코드 조합에 데이터가 없을 수 있음).")
        return
    print("실제 컬럼 목록:", list(df.columns))
    print(df.head(3).to_string())


def print_matrix(hscode, candidates, years, force):
    try:
        result = get_multi_country_comparison(hscode, candidates, years=years, force=force)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"HS {result['hscode']} 성장률 x 한국 점유율 매트릭스 비교")
    print(f"조회 연도: {result['years']}")
    print("=" * 60)
    if result.get("official_item_desc"):
        print(f"\n📋 UN Comtrade 공식 품목 설명: {result['official_item_desc']}")

    th = result["thresholds"]
    print(f"\n기준선(후보국 평균): 성장률 {th['avg_cagr_pct']}% / 한국 점유율 {th['avg_korea_share_pct']}%\n")
    for c in result["candidates"]:
        flag = "  ⚠️ 최신연도 집계중일 수 있음" if c["may_be_incomplete_latest_year"] else ""
        print(f"  [{c['quadrant']}] {c['label']}: 성장률 {c['cagr_pct']}% / 한국점유율 {c['korea_share_pct']}%{flag}")

    if result["excluded"]:
        names = ", ".join(e["label"] for e in result["excluded"])
        print(f"\n⚠️ 데이터 부족으로 제외됨: {names}")

    if result["ai_summary"]:
        ai = result["ai_summary"]
        print("\nAI 전략 시사점")
        for m in ai["top_priority_markets"]:
            print(f"  우선 공략: {m['label']} - {m['reason']}")
        print(f"  종합 전략: {ai['overall_strategy']}")
    else:
        print("\nAI 해석 생성 실패 (원본 수치는 위에 그대로 있음)")


def main():
    parser = argparse.ArgumentParser(description="HS코드+국가 UN Comtrade 시장조사")
    parser.add_argument("--hscode", required=True, help="6자리 HS코드, 예: 190590")
    parser.add_argument("--country", help="예: Vietnam, VNM, 베트남 (단일 국가 조사 시 필수)")
    parser.add_argument("--years", nargs="+", type=int, help="조회할 연도 (예: 2020 2021 2022)")
    parser.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조사")
    parser.add_argument("--debug", action="store_true", help="원본 API 응답 컬럼만 확인하고 종료")
    parser.add_argument("--matrix", action="store_true", help="여러 후보국을 매트릭스로 한 번에 비교")
    parser.add_argument("--candidates", nargs="+", help="--matrix와 함께: 비교할 후보국 목록 (비우면 상위 10개국 자동)")
    args = parser.parse_args()

    ensure_required_keys()

    if args.matrix:
        print_matrix(args.hscode, args.candidates, args.years, args.force)
        return

    if args.debug:
        debug_dump(args.hscode, args.country)
        return

    if not args.country:
        print("오류: --country는 단일 국가 조사 시 필수입니다 (매트릭스 비교는 --matrix 사용).")
        sys.exit(1)

    try:
        result = get_market_research(args.hscode, args.country, years=args.years, force=args.force)
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"[{result['target_country']}] HS {result['hscode']} UN Comtrade 시장조사")
    print(f"조회 연도: {result['years']} / 캐시 사용: {result['from_cache']}")
    print("=" * 60)

    if result.get("official_item_desc"):
        print(f"\n📋 UN Comtrade 공식 품목 설명(HS {result['hscode']}): {result['official_item_desc']}")
        print("   (조사하려던 품목과 다르면 HS코드를 다시 확인하세요)")

    print("\n[1] 글로벌 수입 순위 (상위 10개국)")
    if result["global_import_ranking"]:
        for i, r in enumerate(result["global_import_ranking"], 1):
            print(f"  {i}. {r['country']}: ${r['import_value_usd']:,.0f}")
    else:
        print("  데이터 없음")

    print("\n[2] 타깃 시장 경쟁력")
    comp = result["competitiveness"]
    if comp["total_import_usd"]:
        print(f"  {result['target_country']} 전체 수입액: ${comp['total_import_usd']:,.0f} ({comp['year']}년)")
        for b in comp["breakdown"]:
            share = f"{b['share_pct']}%" if b["share_pct"] is not None else "N/A"
            print(f"    - {b['country_iso3']}: ${b['import_value_usd']:,.0f} (점유율 {share})")
    else:
        print("  데이터 없음")

    growth = result["growth_trend"]
    print(f"\n[3] 성장 트렌드 ({growth.get('years_with_data', 0)}/{len(growth.get('years_requested', []))}개년 데이터 확보)")
    for y in growth["by_year"]:
        flag = "  ⚠️ 아직 집계 중일 수 있음" if y.get("may_be_incomplete") else ""
        print(f"  {y['year']}년: ${y['import_value_usd']:,.0f}{flag}")
    print(f"  CAGR: {growth['cagr_pct']}%" if growth["cagr_pct"] is not None else "  CAGR 계산 불가 (데이터 부족)")
    if growth["by_year"] and any(y.get("may_be_incomplete") for y in growth["by_year"]):
        print("  ⚠️ 가장 최근 연도가 아직 집계 중이라면 실제 수치/CAGR은 달라질 수 있습니다.")

    if result["ai_insight"]:
        print("\n[4] AI 전략 시사점")
        ai = result["ai_insight"]
        print(f"  시장 매력도: {ai.get('market_attractiveness')}")
        print(f"  경쟁 구도: {ai.get('competitive_position')}")
        print(f"  전략 제언: {ai.get('strategic_recommendation')}")
    else:
        print("\n[4] AI 해석 생성 실패 (원본 수치는 위에 그대로 있음)")


if __name__ == "__main__":
    main()

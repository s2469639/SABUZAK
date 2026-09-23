"""
UNCTAD TRAINS Online의 denormalisedRegulations API가 실제로 뭘 돌려주는지
확인하는 디버그 스크립트.

사용법 (sabuzak/scripts/market 에서):
    python debug_trains_ntm.py --country Singapore --hs-code 1905.90
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.hscode import resolve_country_iso  # noqa: E402
from app.services.trains_client import (  # noqa: E402
    fetch_regulations_for_country,
    top_relevant_regulations,
)


def _print_regs(regs):
    for r in regs:
        print("-" * 40)
        for k in ("imposingCountryName", "officialTitle", "description", "hsCodes", "implementationDate", "agencies"):
            if r.get(k):
                print(f"  {k}: {r[k]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True, help="영문 국가명 (예: Singapore)")
    ap.add_argument("--hs-code", required=True, help="제품 HS코드 (예: 1905.90) - 마이페이지에 등록한 것과 동일하게")
    args = ap.parse_args()

    iso3 = resolve_country_iso(args.country)
    print(f"국가명 '{args.country}' -> ISO3: {iso3}")
    if not iso3:
        print("!! ISO3 변환 실패.")
        return

    print(f"\nTRAINS 호출: country={iso3}, hs_code={args.hs_code} (이 나라+제품만 바로 조회)")
    regulations = fetch_regulations_for_country(iso3, args.hs_code)
    print(f"\n원본 수신 건수: {len(regulations)} (필터링 전)")

    filtered = top_relevant_regulations(regulations, args.hs_code, limit=6)
    print(f"\n이 제품(HS {args.hs_code}) 관련 필터링 후 상위 {len(filtered)}건:")
    _print_regs(filtered)


if __name__ == "__main__":
    main()

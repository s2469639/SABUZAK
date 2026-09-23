"""
UNCTAD TRAINS Online의 denormalisedMeasures API가 실제로 뭘 돌려주는지 확인하는
디버그 스크립트.

사용법 (sabuzak/scripts/market 에서):
    python debug_trains_ntm.py --country Singapore
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.hscode import resolve_country_iso  # noqa: E402
from app.services.trains_client import fetch_regulations_for_country  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True, help="영문 국가명 (예: Singapore)")
    args = ap.parse_args()

    iso3 = resolve_country_iso(args.country)
    print(f"국가명 '{args.country}' -> ISO3: {iso3}")
    if not iso3:
        print("!! ISO3 변환 실패.")
        return

    print(f"\nTRAINS 호출: country={iso3} (전세계 조회 후 국가명으로 필터링, 시간이 좀 걸릴 수 있음)")
    regulations = fetch_regulations_for_country(iso3)

    print(f"\n파싱된 규정 수: {len(regulations)}")
    for r in regulations[:5]:
        print("-" * 40)
        for k in ("countryImposingNTMs", "ntmCode", "regulationTitle", "hsCode", "implementationDate"):
            if r.get(k):
                print(f"  {k}: {r[k]}")


if __name__ == "__main__":
    main()

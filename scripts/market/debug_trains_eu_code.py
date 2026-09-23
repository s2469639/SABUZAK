"""TRAINS의 imposingCountries가 EU를 나타내는 코드로 뭘 쓰는지 후보들을
테스트하는 임시 디버그 스크립트. (WTO Timeseries API는 EU를 "EEC"/918로
따로 잡는데, TRAINS도 개별 EU 회원국 대신 EU 전체로 등록했을 가능성이
있어 확인용)

사용법 (sabuzak/scripts/market 에서):
    python debug_trains_eu_code.py --hs-code 190220
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.trains_client import fetch_regulations_for_country  # noqa: E402

# WTO의 EU 코드(EEC)를 포함해, TRAINS가 흔히 쓸 법한 후보들을 넓게 시도
CANDIDATES = ["EEC", "EUN", "EUE", "EU", "EU2", "EU27", "EU28"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hs-code", required=True)
    args = ap.parse_args()

    for code in CANDIDATES:
        print(f"\n=== 시도: imposingCountries=[{code!r}] ===")
        try:
            rows = fetch_regulations_for_country(code, args.hs_code, force_refresh=True, max_pages=1)
            print(f"  -> {len(rows)}건")
            if rows:
                r = rows[0]
                print(f"  샘플: imposingCountryName={r.get('imposingCountryName')!r}, officialTitle={r.get('officialTitle')!r}")
        except Exception as e:
            print(f"  -> 에러: {e}")


if __name__ == "__main__":
    main()

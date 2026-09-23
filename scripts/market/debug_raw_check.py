"""필터링 전 원본 규정 내용을 확인하는 임시 디버그 스크립트.

사용법 (sabuzak 루트에서):
    python scripts/market/debug_raw_check.py --country POL --hs-code 190220
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.trains_client import fetch_regulations_for_country  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True, help="ISO3 (예: POL)")
    ap.add_argument("--hs-code", required=True)
    args = ap.parse_args()

    regs = fetch_regulations_for_country(args.country, args.hs_code)
    print(f"원본 {len(regs)}건")
    for r in regs:
        print("-" * 40)
        print("officialTitle:", r.get("officialTitle"))
        print("description:", r.get("description"))
        print("hsCodes:", r.get("hsCodes"))


if __name__ == "__main__":
    main()

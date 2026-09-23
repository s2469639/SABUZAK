"""app.services.wto_client.get_country_tariff_averages()가 실제로 뭘
돌려주는지 확인하는 디버그 스크립트 (.env의 WTO_API_KEY를 읽어야 하므로
Flask app 컨텍스트 안에서 실행).

사용법 (sabuzak 루트에서):
    python scripts/market/debug_wto_client.py --country ESP
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE_DIR / ".env")  # run.py와 동일하게, app 모듈 import 전에 .env부터 로드

from app.services import wto_client  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True, help="ISO3 코드 (예: ESP)")
    args = ap.parse_args()

    print("WTO_API_KEY 읽힘:", bool(wto_client.WTO_API_KEY))
    if wto_client.WTO_API_KEY:
        print("키 앞 6자리:", wto_client.WTO_API_KEY[:6])

    result = wto_client.get_country_tariff_averages(args.country)
    print("결과:", result)


if __name__ == "__main__":
    main()

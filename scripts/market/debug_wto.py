"""
WTO Timeseries API(api.wto.org/timeseries/v1) 테스트용 임시 디버그 스크립트.
관세율 관련 indicator가 있는지, 실제 데이터가 우리가 쓸만한 형태인지 확인용.

구독키(subscription key)가 필요함 - WTO API 포털(apiportal.wto.org)에서
Timeseries API를 구독하면 발급됨.

사용법 (sabuzak/scripts/market 에서):
    # indicator 이름으로 검색 (예: tariff 들어간 지표 찾기)
    python debug_wto.py indicators --key 발급받은키 --name tariff

    # 실제 데이터 조회 (예: 2023년 전체 국가, HS6 단위 관세율)
    python debug_wto.py data --key 발급받은키 --indicator TP_A_0010 --pc HS6 --ps 2023 --r all
"""
import argparse
import json

import requests

BASE = "https://api.wto.org/timeseries/v1"


def call(path: str, key: str, params: dict):
    headers = {"Ocp-Apim-Subscription-Key": key}
    resp = requests.get(f"{BASE}/{path}", headers=headers, params=params, timeout=30)
    print(f"GET {resp.url}")
    print(f"status: {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        print("(JSON 아님) 응답 앞부분:", resp.text[:500])
        return
    print(json.dumps(data if isinstance(data, list) else [data], ensure_ascii=False, indent=2)[:4000])


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ind = sub.add_parser("indicators", help="지표 목록 검색")
    p_ind.add_argument("--key", required=True, help="구독키 (Ocp-Apim-Subscription-Key)")
    p_ind.add_argument("--name", help="지표 이름(일부) 검색, 예: tariff")

    p_data = sub.add_parser("data", help="실제 데이터포인트 조회")
    p_data.add_argument("--key", required=True)
    p_data.add_argument("--indicator", required=True, help="지표 코드, 예: TP_A_0010")
    p_data.add_argument("--r", default="all", help="reporting economies, 콤마구분 ISO3 (기본 all)")
    p_data.add_argument("--pc", default="default", help="품목 분류, 예: HS6 / HS4 / default")
    p_data.add_argument("--ps", default="default", help="기간, 예: 2023 / 2020-2023 / default")

    args = ap.parse_args()

    if args.cmd == "indicators":
        params = {}
        if args.name:
            params["name"] = args.name
        call("indicators", args.key, params)
    else:
        params = {"i": args.indicator, "r": args.r, "pc": args.pc, "ps": args.ps}
        call("data", args.key, params)


if __name__ == "__main__":
    main()

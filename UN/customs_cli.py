#!/usr/bin/env python3
"""customs_trade_stats.py 단독 실행/테스트용 CLI.

사전 준비:
    pip install -r requirements.txt
    .env 파일에:
        DATA_GO_KR_API_KEY=...
        CUSTOMS_ITEM_API_URL=...          (data.go.kr 활용신청 승인화면의 요청URL 그대로 복사)
        CUSTOMS_ITEM_COUNTRY_API_URL=...

실행:
    python customs_cli.py --hscode 190590                      # 품목 전체(국가 구분 없음)
    python customs_cli.py --hscode 190590 --country 베트남 Vietnam  # 국가 매칭까지
    python customs_cli.py --hscode 190590 --debug              # 원본 응답 그대로 출력

--debug: 관세청 API 원본 응답(품목별/품목별국가별 둘 다)을 그대로 찍습니다.
    이 코드는 실제 응답을 확인 못 한 채로 "공공데이터 개방 표준" 형식을
    가정하고 짰기 때문에, 처음 실행했을 때 필드가 안 맞으면 이 옵션 결과를
    알려주시면 바로 고쳐드릴 수 있습니다.
"""

import argparse
import json
import sys

import customs_trade_stats as cts


def debug_dump(hscode):
    start_ym, end_ym = cts._month_range(6)
    print(f"[디버그] 품목별 수출입실적(GW) 원본 응답 (HS {hscode}, {start_ym}~{end_ym})")
    try:
        api_key = cts.get_config()
        url = cts._get_endpoint("CUSTOMS_ITEM_API_URL")
        items = cts._request(url, api_key, {
            "hsSgn": hscode, "startYyyyMm": start_ym, "endYyyyMm": end_ym, "numOfRows": 5,
        })
        print(json.dumps(items[:3], ensure_ascii=False, indent=2))
        if items:
            print("실제 필드 목록:", list(items[0].keys()))
    except Exception as e:
        print(f"오류: {e}")

    print(f"\n[디버그] 품목별 국가별 수출입실적(GW) 원본 응답 (HS {hscode}, {start_ym}~{end_ym})")
    try:
        api_key = cts.get_config()
        url = cts._get_endpoint("CUSTOMS_ITEM_COUNTRY_API_URL")
        items = cts._request(url, api_key, {
            "hsSgn": hscode, "startYyyyMm": start_ym, "endYyyyMm": end_ym, "numOfRows": 5,
        })
        print(json.dumps(items[:3], ensure_ascii=False, indent=2))
        if items:
            print("실제 필드 목록:", list(items[0].keys()))
    except Exception as e:
        print(f"오류: {e}")


def main():
    parser = argparse.ArgumentParser(description="관세청(data.go.kr) 수출입실적 조회")
    parser.add_argument("--hscode", required=True, help="6자리 HS코드, 예: 190590")
    parser.add_argument("--country", nargs="+", help="매칭할 국가명 후보 (예: --country 베트남 Vietnam)")
    parser.add_argument("--months", type=int, default=36, help="조회할 개월 수 (기본 36개월)")
    parser.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조사")
    parser.add_argument("--debug", action="store_true", help="원본 API 응답만 확인하고 종료")
    args = parser.parse_args()

    if args.debug:
        debug_dump(args.hscode)
        return

    try:
        result = cts.get_customs_context(
            args.hscode, args.country, months=args.months, force=args.force,
        )
    except Exception as e:
        print(f"오류: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"HS {result['hscode']} 관세청 공식 수출입 실적 ({result['months_covered']})")
    print(f"캐시 사용: {result['from_cache']}")
    print("=" * 60)

    print("\n[1] 월별 전세계 합계 (최근 6개월)")
    for m in result["item_total"][-6:]:
        exp = f"${m['export_usd']:,.0f}" if m["export_usd"] is not None else "N/A"
        imp = f"${m['import_usd']:,.0f}" if m["import_usd"] is not None else "N/A"
        print(f"  {m['year_month']}: 수출 {exp} / 수입 {imp}")

    if args.country:
        print(f"\n[2] '{' / '.join(args.country)}' 매칭 결과")
        match = result["target_country_match"]
        if match:
            print(f"  매칭된 국가: {match['country_name_ko']} ({match['country_name_en']})")
            exp = f"${match['export_usd']:,.0f}" if match["export_usd"] is not None else "N/A"
            imp = f"${match['import_usd']:,.0f}" if match["import_usd"] is not None else "N/A"
            print(f"  한국의 수출: {exp} / 한국의 수입: {imp}")
        else:
            print("  매칭되는 국가를 찾지 못했습니다 (국가명 표기가 다를 수 있습니다).")


if __name__ == "__main__":
    main()

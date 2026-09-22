"""
macmap NTM API가 실제로 뭘 돌려주는지 원본 그대로 확인하는 디버그 스크립트.
403 등 에러가 날 때, 세션 쿠키 확보 단계부터 막히는지 / API 호출만 막히는지,
차단 응답 본문이 뭔지까지 자세히 찍어준다.

사용법 (sabuzak/scripts/market 에서):
    python debug_macmap_ntm.py --country Singapore --hs 190590
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.services.hscode import get_m49_code, resolve_country_iso  # noqa: E402
from app.services.macmap_client import BASE, KOREA_M49, UA  # noqa: E402

import requests  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True, help="영문 국가명 (예: Singapore)")
    ap.add_argument("--hs", required=True, help="HS코드 6자리 (예: 190590)")
    args = ap.parse_args()

    iso3 = resolve_country_iso(args.country)
    print(f"국가명 '{args.country}' -> ISO3: {iso3}")
    if not iso3:
        print("!! ISO3 변환 실패.")
        return

    m49 = get_m49_code(iso3)
    print(f"ISO3 '{iso3}' -> M49: {m49}")
    if not m49:
        print("!! M49 변환 실패.")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"})

    print(f"\n1단계: 세션 쿠키 확보 (GET {BASE}/en/query/results)")
    resp1 = session.get(f"{BASE}/en/query/results", timeout=15)
    print(f"  상태코드: {resp1.status_code}")
    print(f"  받은 쿠키: {dict(session.cookies)}")
    print(f"  응답 헤더 일부: server={resp1.headers.get('server')}, cf-ray={resp1.headers.get('cf-ray')}")

    print(f"\n2단계: NTM API 호출 (reporter={m49}, partner={KOREA_M49}, product={args.hs})")
    url = f"{BASE}/api/results/ntm-measures"
    params = {"reporter": m49, "partner": KOREA_M49, "product": args.hs}
    referer = f"{BASE}/en/query/results?reporter={m49}&partner={KOREA_M49}&product={args.hs}&level=6"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    resp2 = session.get(url, params=params, headers=headers, timeout=15)
    print(f"  상태코드: {resp2.status_code}")
    print(f"  응답 헤더: server={resp2.headers.get('server')}, cf-ray={resp2.headers.get('cf-ray')}, content-type={resp2.headers.get('content-type')}")
    print(f"\n응답 본문 (앞 1500자):")
    print(resp2.text[:1500])


if __name__ == "__main__":
    main()

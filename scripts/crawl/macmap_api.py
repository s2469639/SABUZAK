"""
Market Access Map (macmap.org) NTM/관세 데이터 - 비공식 API 직접 호출 스크립트

브라우저 개발자도구로 확인한 실제 내부 API를 requests로 직접 호출합니다.
(Playwright 불필요 - 훨씬 가볍고 빠름)

확인된 엔드포인트 패턴 (reporter=수입국, partner=수출국, product=HS코드):
    /api/results/ntm-measures?reporter=..&partner=..&product=..   비관세조치(NTM)
    /api/results/customduties?reporter=..&partner=..&product=..   관세
    /api/results/taxes?reporter=..&partner=..&product=..          기타 조세
    /api/results/traderemedy?reporter=..&partner=..&product=..    무역구제조치(반덤핑 등)

인증: x-api-key 없음. ASP.NET_SessionId 등 세션 쿠키 + Referer 헤더로 동작.
    → requests.Session()으로 메인 페이지 먼저 방문해 쿠키 확보 후 API 호출.

국가코드: UN M49 숫자코드 사용 (예: 410=대한민국, 344=홍콩, 842=미국, 392=일본, 156=중국)
전체 목록: https://unstats.un.org/unsd/methodology/m49/ 참고

주의:
- 어디까지나 브라우저 내부 API 역호출이라 macmap 측 변경 시 깨질 수 있습니다.
- 비영리/교육 목적, 소량 조회 기준. 요청 간 딜레이 유지 (과도한 속도로 호출 금지).
- ToS 상 자동 대량수집이 금지되어 있을 수 있으니, 연구/과제용 소규모 조회로 사용 권장.

설치:
    pip install requests pandas openpyxl

사용 예:
    python macmap_api.py --reporter 410 --partner 76 --product 19051000
    (reporter=한국 수입, partner=브라질 수출, HS 19051000 크네케브로트)

    여러 조합 일괄조회는 --batch csv파일 (컬럼: reporter,partner,product) 사용
"""

import argparse
import csv
import time
from pathlib import Path

import requests

BASE = "https://www.macmap.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_DELAY_SEC = 2  # 매너 크롤링 - 요청 간 최소 대기


def make_session() -> requests.Session:
    """메인 쿼리 페이지를 방문해 세션 쿠키(ASP.NET_SessionId 등)를 확보한다."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"})
    s.get(f"{BASE}/en/query/results", timeout=15)
    return s


def fetch_endpoint(session: requests.Session, endpoint: str, reporter: str, partner: str, product: str) -> dict:
    url = f"{BASE}/api/results/{endpoint}"
    params = {"reporter": reporter, "partner": partner, "product": product}
    referer = (
        f"{BASE}/en/query/results?reporter={reporter}&partner={partner}"
        f"&product={product}&level=6"
    )
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    resp = session.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"  # requests의 인코딩 오판으로 특수문자 깨지는 것 방지
    return resp.json()


def flatten_ntm(data: list, reporter: str, partner: str, product: str) -> list[dict]:
    """ntm-measures 응답(리스트)을 표 형태로 펼친다.

    실제 구조 (같은 그룹 안에 요약용 Measures와 상세용 AllMeasures가 같이 옴):
    [
      {"MeasureSection": "Import requirements...", "MeasureDirection": "1",
       "NtmYear": "2018", "DataSource": "UNCTAD",
       "Measures": [{"MeasureCode","MeasureTitle","MeasureSummary","MeasureCount"}, ...],
       "AllMeasures": [
         {"Code","Title","Summary","LegislationTitle","LegislationSummary",
          "ImplementationAuthority","StartDate","EndDate","WebLink","TextLink", ...},
         ...  # 세부 법령 건마다 하나씩 (MeasureCount 개수만큼)
       ]},
      ...
    ]
    """
    rows = []
    for group in data:
        section = group.get("MeasureSection", "")
        direction = group.get("MeasureDirection", "")
        ntm_year = group.get("NtmYear", "")
        source = group.get("DataSource", "")
        for m in group.get("AllMeasures", []):
            rows.append({
                "reporter": reporter,
                "partner": partner,
                "product": product,
                "measure_section": section,
                "measure_direction": direction,
                "measure_code": m.get("Code", ""),
                "measure_title": m.get("Title", ""),
                "measure_summary": m.get("Summary", ""),
                "legislation_title": m.get("LegislationTitle", ""),
                "legislation_summary": m.get("LegislationSummary", ""),
                "implementation_authority": m.get("ImplementationAuthority", ""),
                "start_date": m.get("StartDate", ""),
                "end_date": m.get("EndDate", ""),
                "affected_countries": m.get("AdditionalCommentCountry", ""),
                "web_link": m.get("WebLink", ""),
                "text_link": m.get("TextLink", ""),
                "ntm_year": ntm_year,
                "data_source": source,
            })
    return rows


def flatten_customduties(data: dict, reporter: str, partner: str, product: str) -> list[dict]:
    """customduties 응답을 표 형태로 펼친다.

    실제 구조:
    {
      "Year": "2026", "ReferenceData": "Source : ITC (2026)",
      "CustomDuty": [
        {"NTLCCode","NTLCDescription","TariffRegime","TariffReported","TariffAve",
         "Qty","Unit","OtherDuties","Year","Revision","AgreementID","FtaId", ...},
        ...
      ]
    }
    같은 product에 여러 TariffRegime(MFN/특혜세율 등)이 동시에 나올 수 있음.
    """
    rows = []
    source = data.get("ReferenceData", "")
    for d in data.get("CustomDuty", []):
        rows.append({
            "reporter": reporter,
            "partner": partner,
            "product": product,
            "ntlc_code": d.get("NTLCCode", ""),
            "ntlc_description": d.get("NTLCDescription", ""),
            "tariff_regime": d.get("TariffRegime", ""),
            "tariff_reported": d.get("TariffReported", ""),
            "tariff_ave": d.get("TariffAve", ""),
            "unit": d.get("Unit", ""),
            "other_duties": d.get("OtherDuties", ""),
            "year": d.get("Year", ""),
            "revision": d.get("Revision", ""),
            "source": source,
        })
    return rows


FLATTENERS = {
    "ntm-measures": flatten_ntm,
    "customduties": flatten_customduties,
}


def run_one(session: requests.Session, endpoint: str, reporter: str, partner: str, product: str) -> list[dict]:
    data = fetch_endpoint(session, endpoint, reporter, partner, product)
    time.sleep(REQUEST_DELAY_SEC)
    return FLATTENERS[endpoint](data, reporter, partner, product)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reporter", help="수입국(=수출대상국) UN M49 코드 (예: 410=한국)")
    ap.add_argument("--partner", help="수출국 UN M49 코드")
    ap.add_argument("--product", help="HS 코드 (8자리, 예: 19051000)")
    ap.add_argument("--batch", help="reporter,partner,product 컬럼을 가진 CSV로 일괄 조회")
    ap.add_argument(
        "--endpoint",
        choices=["ntm-measures", "customduties"],
        default="ntm-measures",
        help="ntm-measures=비관세장벽(기본), customduties=관세율",
    )
    ap.add_argument("--raw", action="store_true", help="파싱 없이 원본 JSON만 출력 (구조 확인용)")
    args = ap.parse_args()

    session = make_session()
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)

    tasks = []
    if args.batch:
        with open(args.batch, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tasks.append((row["reporter"], row["partner"], row["product"]))
    else:
        if not (args.reporter and args.partner and args.product):
            ap.error("--reporter --partner --product 모두 지정하거나 --batch csv를 쓰세요")
        tasks.append((args.reporter, args.partner, args.product))

    if args.raw:
        data = fetch_endpoint(session, args.endpoint, *tasks[0])
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
        return

    all_rows = []
    for reporter, partner, product in tasks:
        print(f"조회중[{args.endpoint}]: reporter={reporter} partner={partner} product={product}")
        try:
            rows = run_one(session, args.endpoint, reporter, partner, product)
            all_rows.extend(rows)
        except Exception as e:
            print(f"  실패: {e}")
        time.sleep(REQUEST_DELAY_SEC)

    if all_rows:
        out_path = out_dir / f"macmap_{args.endpoint}_results.csv"
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"저장 완료: {out_path} ({len(all_rows)}건)")
    else:
        print("결과 없음. --raw 옵션으로 원본 JSON 구조부터 확인해보세요.")


if __name__ == "__main__":
    main()

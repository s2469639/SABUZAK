"""
UN Comtrade — 한국(410) HS 190590 국가별 수출 추적기
-------------------------------------------------------
지정한 연도들에 대해 한국의 '목적지 국가별' 수출액을 가져와서
  · 국가별 수출액(USD, FOB 기준)
  · 전년比 증가율(YoY %)
을 계산해 콘솔에 '전체 국가' 출력하고 CSV로 저장한다.

사전 준비:
  pip install requests pandas python-dotenv

API 키:
  이 파일과 같은 폴더에 '.env' 파일을 만들고 아래 한 줄 (따옴표·공백 없이):
    COMTRADE_KEY=발급받은키

실행:
  python comtrade_export_tracker.py
"""

import os
import sys
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()   # .env 읽기 (API_KEY 줄보다 반드시 위)

# ── 설정 ────────────────────────────────────────────────
API_KEY = os.environ.get("COMTRADE_KEY")
if not API_KEY:
    sys.exit(".env에서 COMTRADE_KEY를 찾지 못했습니다. 파일 이름(.env)·위치·키 이름을 확인하세요.")

BASE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"  # 상품(C)/연간(A)/HS

REPORTER = "410"                 # 한국 (신고 주체)
FLOW = "X"                       # 수출. 수입으로 바꾸려면 "M"
HS_CODE = "190590"               # 제품 HS코드 (제품군에 맞게 교체)
YEARS = [2022, 2023, 2024]       # 증가율 계산 위해 최근 3개년


# ── API 호출 ────────────────────────────────────────────
def fetch_year(year: int) -> pd.DataFrame:
    """해당 연도의 국가별 수출 내역을 DataFrame으로 반환. 없으면 빈 DF."""
    params = {
        "reporterCode": REPORTER,
        "flowCode": FLOW,
        "cmdCode": HS_CODE,
        "period": str(year),
        "includeDesc": "true",   # 나라·품목 이름 같이 받기
        # partnerCode 미지정 → 모든 상대국 반환
    }
    headers = {"Ocp-Apim-Subscription-Key": API_KEY}

    resp = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
    resp.raise_for_status()      # 4xx/5xx면 예외 발생
    rows = resp.json().get("data", [])

    if not rows:
        print(f"  ⚠ {year}: 데이터 없음 (아직 미집계일 수 있음)")
        return pd.DataFrame()

    df = pd.DataFrame(rows)[["period", "partnerCode", "partnerDesc", "primaryValue"]].copy()
    # 이름이 비면 코드로 대체
    df["partnerDesc"] = df["partnerDesc"].fillna(df["partnerCode"].astype(str))
    # World 합계(0) 제외 → 순수 국가별만 남김
    df = df[df["partnerCode"] != 0]
    df["year"] = year
    return df


def main() -> None:
    # 연도별 조회 (무료 티어 하루 500콜, 여기선 연도 수만큼만 사용)
    frames = []
    for y in YEARS:
        print(f"조회 중: {y} ...")
        try:
            frames.append(fetch_year(y))
        except requests.HTTPError as e:
            print(f"  ✗ {y} 요청 실패: {e}")
        time.sleep(1)            # rate limit 여유

    frames = [f for f in frames if not f.empty]
    if not frames:
        sys.exit("가져온 데이터가 없습니다. 파라미터(REPORTER/HS_CODE/YEARS)를 확인하세요.")

    data = pd.concat(frames, ignore_index=True)

    # 국가 × 연도 피벗 (값 = 수출액 USD)
    pivot = data.pivot_table(
        index=["partnerCode", "partnerDesc"],
        columns="year",
        values="primaryValue",
        aggfunc="sum",
    ).reset_index()

    latest, prev = YEARS[-1], YEARS[-2]

    # 전년比 증가율(YoY %) — 두 연도가 모두 있을 때만
    if latest in pivot.columns and prev in pivot.columns:
        pivot["YoY_%"] = ((pivot[latest] - pivot[prev]) / pivot[prev] * 100).round(1)

    # 최신연도 수출액 기준 내림차순 정렬
    if latest in pivot.columns:
        pivot = pivot.sort_values(latest, ascending=False)

    # ── CSV 저장 (원본 숫자 그대로) ──
    out = f"korea_{HS_CODE}_exports.csv"
    pivot.to_csv(out, index=False, encoding="utf-8-sig")  # 엑셀 한글 안깨지게 utf-8-sig

    # ── 콘솔 출력 (데이터 있는 전체 국가) ──
    pd.set_option("display.max_rows", None)      # 줄임표(...) 없이 전부 출력
    pd.set_option("display.width", None)         # 가로 잘림 방지

    show = pivot.copy()
    for y in YEARS:
        if y in show.columns:
            show[y] = show[y].map(lambda v: f"{v:,.0f}" if pd.notna(v) else "-")
    if "YoY_%" in show.columns:
        show["YoY_%"] = show["YoY_%"].map(lambda v: f"{v:+.1f}%" if pd.notna(v) else "-")

    print(f"\n=== 한국 HS {HS_CODE} 국가별 수출액 (USD, 전체 {len(show)}개국) ===")
    print(show.to_string(index=False))
    print(f"\n전체 결과 저장됨 → {out}")


if __name__ == "__main__":
    main()
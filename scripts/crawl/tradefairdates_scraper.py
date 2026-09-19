#!/usr/bin/env python3
"""
tradefairdates.com 리스트 페이지 크롤러

추출 항목: 전시회명, 개최기간, 개최국, 개최도시, 개최장소(베뉴)
출력: CSV

사용법:
    pip install requests beautifulsoup4
    python tradefairdates_scraper.py "https://www.tradefairdates.com/Fancy-Food-Shows-Y82-S1.html" output.csv

실제 페이지 DOM 구조 (개발자도구로 확인됨):
    div.messeninfoTile
      div.inner
        div.tileHeader
          a.title[title]              -> 전시회명 (title 속성에 "이름 YYYY, 도시")
          div.headBottom
            div.time                  -> 개최기간 (예: "11. October 2026")
        div.tileMeta
          a.title                     -> 전시회명 (tileHeader와 동일 텍스트)
          div.description             -> 설명
          p.zutritt                   -> 참관대상
          div.messeTerminLocation
            div.flag > img[alt]       -> 개최국 (alt="Italy" 등)
            div.messeTerminLocationOrtContainer
              span.messeTerminZentrum -> 개최장소(베뉴)
              span.messeTerminOrt     -> 개최도시
              span.messeTerminLand    -> ", 국가" (콤마 포함)
"""

import csv
import random
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PAGE_RE = re.compile(r"-S(\d+)\.html$")
BASE_URL = "https://www.tradefairdates.com/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# 요청 사이 대기 시간(초). 서버 부담과 IP 차단 위험을 줄이려면 값을 늘리세요.
MIN_DELAY = 1.5
MAX_DELAY = 3.0
MAX_RETRIES = 3

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def polite_sleep():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

FIELDNAMES = [
    "전시회명",
    "시작일",
    "종료일",
    "개최국",
    "개최도시",
    "개최장소(베뉴)",
    "참관대상",
    "거래유형",
    "축제URL",
    "축제소개",
]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# tileHeader의 div.time에 나오는 개최기간 텍스트를 (시작일, 종료일) 숫자(YYYYMMDD)로 변환.
#
# 정렬(임박한 날짜 순 오름차순) 기준으로 "미상"을 항상 맨 뒤로 보내려면, 미상 값이
# 실존하는 모든 날짜보다 커야 한다. 0(0000-00-00)은 사전식/숫자식 정렬 모두에서
# 가장 작은 값이라 오름차순 정렬 시 오히려 맨 위로 올라오는 버그가 생긴다.
# 그래서 두 가지 "미상"을 구분해서 인코딩한다:
#   - 일자만 미상 (예: "Expected in October 2027", 연/월은 앎)
#     -> 그 달의 일(day)을 32로 채움 (예: 20271032). 실제 날짜(...31)보다는 크지만
#        다음 달(202711xx)보다는 작아서, 해당 월 안에서만 맨 뒤로 밀림
#   - 날짜 전체가 미상 (예: "Date Still Unknown")
#     -> UNKNOWN_DATE(99999999). 어떤 연/월/일 조합보다도 큰 값이라 항상 맨 뒤로 감
UNKNOWN_DATE = 99999999

_SINGLE_DAY_RE = re.compile(r"^(\d{1,2})\.\s+([A-Za-z]+)\s+(\d{4})$")
_SAME_MONTH_RANGE_RE = re.compile(r"^(\d{1,2})\.\s*-\s*(\d{1,2})\.\s+([A-Za-z]+)\s+(\d{4})$")
_CROSS_MONTH_RANGE_RE = re.compile(
    r"^(\d{1,2})\.\s+([A-Za-z]+)\s*-\s*(\d{1,2})\.\s+([A-Za-z]+)\s+(\d{4})$"
)
_MONTH_ONLY_RE = re.compile(r"([A-Za-z]+)\s+(\d{4})")


def _ymd(year, month, day):
    return year * 10000 + month * 100 + day


def parse_period(period_text: str):
    """개최기간 원문 -> (시작일, 종료일) 숫자(YYYYMMDD) 튜플."""
    text = (period_text or "").strip()
    if not text:
        return UNKNOWN_DATE, UNKNOWN_DATE

    m = _SAME_MONTH_RANGE_RE.match(text)
    if m:
        start_day, end_day, month_name, year = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            year = int(year)
            return _ymd(year, month, int(start_day)), _ymd(year, month, int(end_day))

    m = _CROSS_MONTH_RANGE_RE.match(text)
    if m:
        start_day, start_month_name, end_day, end_month_name, year = m.groups()
        start_month = MONTHS.get(start_month_name.lower())
        end_month = MONTHS.get(end_month_name.lower())
        if start_month and end_month:
            year = int(year)
            return _ymd(year, start_month, int(start_day)), _ymd(year, end_month, int(end_day))

    m = _SINGLE_DAY_RE.match(text)
    if m:
        day, month_name, year = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            date = _ymd(int(year), month, int(day))
            return date, date

    # 일자 미상, 달/연도만 아는 경우 (예: "Expected in October 2027")
    m = _MONTH_ONLY_RE.search(text)
    if m:
        month_name, year = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            date = _ymd(int(year), month, 32)
            return date, date

    # 그 외(예: "Date Still Unknown")는 날짜 전체가 미상
    return UNKNOWN_DATE, UNKNOWN_DATE


# 참관대상(p.zutritt) 원문에서 B2B/B2C 여부를 규칙 기반으로 판별.
# AI 호출 없이 문구만으로 판단 가능해서 크롤링 시점에 바로 계산해둔다.
_B2B_HINTS = ("professional", "trade only", "trade visitors", "business visitors")
_B2C_HINTS = ("general public", "open to public", "public welcome", "consumer")


def classify_audience_type(audience_note: str) -> str:
    """참관대상 원문 -> 'B2B' / 'B2C' / 'B2B, B2C' / '미상'."""
    text = (audience_note or "").lower()
    is_b2b = any(hint in text for hint in _B2B_HINTS)
    is_b2c = any(hint in text for hint in _B2C_HINTS)
    if is_b2b and is_b2c:
        return "B2B, B2C"
    if is_b2b:
        return "B2B"
    if is_b2c:
        return "B2C"
    return "미상"


def fetch_html(url: str) -> str:
    for attempt in range(1, MAX_RETRIES + 1):
        resp = SESSION.get(url, timeout=30)

        # 429(요청 과다) / 503(일시적 차단·점검)이면 대기 후 재시도
        if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
            wait = float(resp.headers.get("Retry-After", 10 * attempt))
            print(f"  -> {resp.status_code} 응답, {wait:.0f}초 대기 후 재시도 ({attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text

    resp.raise_for_status()
    return resp.text


def text_or_empty(node):
    return node.get_text(strip=True) if node else ""


def parse_tile(tile) -> dict:
    inner = tile.select_one("div.inner") or tile

    # 전시회명: tileHeader의 a.title 우선, 없으면 tileMeta의 a.title
    title_a = inner.select_one("div.tileHeader a.title") or inner.select_one(
        "div.tileMeta a.title"
    )
    name = text_or_empty(title_a)

    # 개최기간
    date_div = inner.select_one("div.tileHeader div.headBottom div.time")
    date_text = text_or_empty(date_div)

    # 개최국 (플래그 이미지의 alt 속성이 가장 정확)
    flag_img = inner.select_one("div.messeTerminLocation div.flag img")
    country = flag_img.get("alt", "").strip() if flag_img else ""
    if not country:
        land_span = inner.select_one("span.messeTerminLand")
        country = text_or_empty(land_span).lstrip(",").strip()

    # 개최도시
    ort_span = inner.select_one("span.messeTerminOrt")
    city = text_or_empty(ort_span)

    # 개최장소(베뉴)
    zentrum_span = inner.select_one("span.messeTerminZentrum")
    venue = text_or_empty(zentrum_span)

    # 참관대상 (예: "professional visitors only", "general public")
    # B2B/B2C 판단의 핵심 근거이므로 목록 페이지에서 바로 수집
    zutritt_p = inner.select_one("p.zutritt")
    audience = text_or_empty(zutritt_p)

    if not any([name, date_text, country, city, venue]):
        return None

    detail_url = urljoin(BASE_URL, title_a["href"]) if title_a and title_a.get("href") else ""
    start_date, end_date = parse_period(date_text)
    audience_type = classify_audience_type(audience)

    return {
        "전시회명": name,
        "시작일": start_date,
        "종료일": end_date,
        "개최국": country,
        "개최도시": city,
        "개최장소(베뉴)": venue,
        "참관대상": audience,
        "거래유형": audience_type,
        "축제URL": "",
        "축제소개": "",
        "_detail_url": detail_url,
    }


def parse_detail(url: str) -> dict:
    """상세페이지에서 전시회 공식 웹사이트와 한 줄 소개를 추출."""
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    # 전시회 공식 웹사이트 (예: www.iffip.kiev.ua)
    website_span = soup.select_one('span[data-role="gothere"]')
    website = text_or_empty(website_span)

    # 한 줄 소개: div#messetext 안의 첫 번째 내용이 있는 <p> (강조된 이름 + 설명 문장)
    intro = ""
    for p in soup.select("div#messetext p"):
        text = p.get_text(" ", strip=True)
        if text:
            intro = text
            break

    return {"축제URL": website, "축제소개": intro}


def crawl_page(url: str):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    tiles = soup.select("div.messeninfoTile")
    rows = []
    for tile in tiles:
        row = parse_tile(tile)
        if row:
            rows.append(row)
    return rows


def crawl_all_pages(start_url: str):
    """URL의 '-S<번호>.html' 부분을 늘려가며 결과가 없는 페이지가 나올 때까지 수집."""
    m = PAGE_RE.search(start_url)
    if not m:
        # 페이지네이션 패턴이 없으면 단일 페이지만 수집
        return crawl_page(start_url)

    page_num = int(m.group(1))
    all_rows = []
    seen_keys = set()

    def row_key(row):
        # 상세페이지 URL이 있으면 그걸로, 없으면 이름+날짜+장소 조합으로 유일성 판단
        # (동명의 전시회가 여러 페이지에 걸쳐 나올 수 있어 이름만으로는 구분 불가)
        return row.get("_detail_url") or (
            row["전시회명"], row["개최기간"], row["개최장소(베뉴)"]
        )

    while True:
        page_url = PAGE_RE.sub(f"-S{page_num}.html", start_url)
        print(f"페이지 {page_num} 수집 중: {page_url}")
        try:
            rows = crawl_page(page_url)
        except requests.exceptions.HTTPError:
            break

        if not rows:
            break

        # 이전 페이지와 완전히 동일한 목록이 반복되면(마지막 페이지 초과) 중단
        new_rows = [r for r in rows if row_key(r) not in seen_keys]
        print(f"  -> 이 페이지에서 {len(rows)}건 발견, 신규 {len(new_rows)}건")
        if not new_rows:
            break

        all_rows.extend(new_rows)
        seen_keys.update(row_key(r) for r in rows)

        page_num += 1
        polite_sleep()

    return all_rows


def enrich_with_details(rows):
    """각 전시회의 상세페이지를 방문해 축제URL/축제소개를 채운다."""
    total = len(rows)
    for i, row in enumerate(rows, 1):
        detail_url = row.get("_detail_url", "")
        if not detail_url:
            continue
        print(f"[{i}/{total}] 상세페이지 수집 중: {detail_url}")
        try:
            detail = parse_detail(detail_url)
            row["축제URL"] = detail["축제URL"]
            row["축제소개"] = detail["축제소개"]
        except requests.exceptions.RequestException as e:
            print(f"  -> 실패: {e}")
        polite_sleep()
    return rows


def save_csv(rows, out_path: str):
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def main():
    if len(sys.argv) < 3:
        print("사용법: python tradefairdates_scraper.py <URL> <output.csv> [--details]")
        print("       (URL에 -S1.html 이 포함되어 있으면 자동으로 전체 페이지를 수집합니다)")
        print("       --details 를 추가하면 각 전시회 상세페이지의 축제URL/축제소개도 함께 수집합니다")
        sys.exit(1)

    url = sys.argv[1]
    out_path = sys.argv[2]
    with_details = "--details" in sys.argv[3:]

    rows = crawl_all_pages(url)
    if not rows:
        print("경고: 추출된 데이터가 없습니다. 페이지 구조가 변경되었을 수 있습니다.")
    if with_details:
        rows = enrich_with_details(rows)
    save_csv(rows, out_path)
    print(f"{len(rows)}건 저장 완료 -> {out_path}")


if __name__ == "__main__":
    main()

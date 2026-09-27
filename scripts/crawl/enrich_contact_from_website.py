#!/usr/bin/env python3
"""
raw_exhibitions.website 에 저장된 "박람회 공식 홈페이지"들을 순회하며
이메일/전화번호를 찾아서 DB에 채워넣는 스크립트.

주의: tradefairdates.com/myfair.co 자체를 긁는 게 아니라, 그 사이트들이 이미
알려준 "박람회 주최측 공식 홈페이지"를 대상으로 합니다. 주최측이 문의를 받으려고
직접 공개해둔 연락처를 가져오는 것이라, myfair.co의 "Display e-mail address"
클릭식 스팸방지 우회와는 성격이 다릅니다.

동작 순서 (요청하신 흐름 그대로):
    1. website 링크 접속
       A. <a href="mailto:..."> 태그 탐색
       B. 못 찾으면 본문 텍스트에서 이메일 정규식(@) 매칭
       C. 그래도 없으면 "Contact/About/Kontakt/Impressum" 등 링크를 한 번
          따라가서 그 페이지에서 A, B 재시도 (딱 1단계만 더 들어감, 무한 추적 방지)
       전화번호도 같은 흐름으로 tel: 링크 우선, 없으면 정규식으로 시도
    2. 이메일 정제(형식 검증, 이미지 파일명 오탐 제거)
    3. DB에 organizer_email / organizer_phone 컬럼으로 저장
       (이미 채워진 건 재수집 안 함 -> 신규/공란만 대상, API 크롤링과 동일한 절약 전략)

사전 준비:
    pip install requests beautifulsoup4

실행:
    python enrich_contact_from_website.py --db ../../instance/sabuzak.db
    python enrich_contact_from_website.py --db ../../instance/sabuzak.db --limit 20   # 테스트
    python enrich_contact_from_website.py --db ../../instance/sabuzak.db --force      # 전체 재수집

한계:
    - 사이트마다 구조가 천차만별이라 100% 성공은 불가능합니다. 못 찾으면 그냥
      빈 값으로 남습니다 (에러 아님).
    - myfair.co처럼 자바스크립트로 나중에 채워지는 사이트는 이 방식(requests)으로는
      못 잡습니다. 그런 사이트가 많으면 Playwright 버전으로 바꿔야 할 수 있어요.
    - 정말 사이트 자체가 없어졌거나(도메인 만료) 응답이 없으면 건너뜁니다.
"""

import argparse
import os
import random
import re
import sqlite3
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 15
MIN_DELAY = 1.0
MAX_DELAY = 2.5

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# 이미지/스크립트 파일명이 이메일처럼 오탐되는 걸 방지 (예: logo@2x.png)
BAD_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
BAD_EMAIL_KEYWORDS = ("example.com", "sentry.io", "yourdomain", "domain.com")

# 스팸봇 방지로 "info at domain dot com" 처럼 @/.을 텍스트로 풀어쓴 경우를
# 정규식 매칭 전에 원래 기호로 되돌려놓기 위한 패턴들
DEOBFUSCATE_PATTERNS = [
    (re.compile(r"\s*\[\s*at\s*\]\s*", re.I), "@"),
    (re.compile(r"\s*\(\s*at\s*\)\s*", re.I), "@"),
    (re.compile(r"\s+at\s+", re.I), "@"),
    (re.compile(r"\s*\[\s*dot\s*\]\s*", re.I), "."),
    (re.compile(r"\s*\(\s*dot\s*\)\s*", re.I), "."),
    (re.compile(r"\s+dot\s+", re.I), "."),
]

# 전화번호는 오탐(날짜, 연도, 가격 등)이 너무 많아서, "+국가코드"로 시작하는
# 국제전화 형태만 신뢰한다. tel: 링크는 이 검증 없이 그대로 신뢰.
PHONE_RE = re.compile(r"\+\d[\d\s().-]{6,17}\d")


def deobfuscate(text: str) -> str:
    for pattern, repl in DEOBFUSCATE_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def extract_email_from_jsonld(soup: BeautifulSoup) -> str:
    """<script type="application/ld+json"> 안의 Organization/ContactPoint
    구조화 데이터에서 이메일을 찾는다 (사이트가 SEO용으로 흔히 넣어둠)."""
    import json

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            email = item.get("email")
            if email and is_valid_email(email):
                return email
            contact_point = item.get("contactPoint")
            if isinstance(contact_point, dict):
                email = contact_point.get("email")
                if email and is_valid_email(email):
                    return email
    return ""


def extract_phone_from_jsonld(soup: BeautifulSoup) -> str:
    import json

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (ValueError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            phone = item.get("telephone")
            if phone:
                return phone
            contact_point = item.get("contactPoint")
            if isinstance(contact_point, dict):
                phone = contact_point.get("telephone")
                if phone:
                    return phone
    return ""

# "contact" 계열을 최우선으로 찾고, 그런 링크가 전혀 없을 때만 about/impressum류로
# 대체(fallback)한다. 순서를 안 나누면 "About"이 "Contact"보다 먼저 나오는 페이지에서
# About을 잘못 집어버리는 문제가 있었음.
STRONG_CONTACT_KEYWORDS = ("contact", "kontakt", "contacto", "contatti", "연락처", "문의")
FALLBACK_CONTACT_KEYWORDS = ("about", "impressum", "imprint")

NEW_COLUMNS = {
    "organizer_email": "TEXT",
    "organizer_phone": "TEXT",
    "contact_synced_at": "TEXT",
}


def polite_sleep():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def normalize_url(website: str) -> str:
    website = website.strip()
    if not website:
        return ""
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    return website


def is_valid_email(candidate: str) -> bool:
    lower = candidate.lower()
    if lower.endswith(BAD_EMAIL_SUFFIXES):
        return False
    if any(bad in lower for bad in BAD_EMAIL_KEYWORDS):
        return False
    return True


def extract_email_from_html(soup: BeautifulSoup) -> str:
    # A. mailto 태그 우선
    mailto_a = soup.select_one('a[href^="mailto:"]')
    if mailto_a:
        email = mailto_a["href"].replace("mailto:", "").split("?")[0].strip()
        if is_valid_email(email):
            return email

    # B. 구조화 데이터(JSON-LD) - SEO용으로 넣어둔 정확한 값이라 신뢰도 높음
    jsonld_email = extract_email_from_jsonld(soup)
    if jsonld_email:
        return jsonld_email

    # C. 본문 텍스트 정규식 (원문 그대로, 그다음 "at/dot" 난독화 풀어서 재시도)
    text = soup.get_text(" ", strip=True)
    for match in EMAIL_RE.findall(text):
        if is_valid_email(match):
            return match

    deobfuscated = deobfuscate(text)
    for match in EMAIL_RE.findall(deobfuscated):
        if is_valid_email(match):
            return match

    return ""


def extract_phone_from_html(soup: BeautifulSoup) -> str:
    # tel: 링크는 사이트가 명시적으로 전화번호라고 표시한 것이므로 형식 검증 없이 신뢰
    tel_a = soup.select_one('a[href^="tel:"]')
    if tel_a:
        phone = tel_a["href"].replace("tel:", "").strip()
        if phone:
            return phone

    jsonld_phone = extract_phone_from_jsonld(soup)
    if jsonld_phone:
        return jsonld_phone

    # 본문 텍스트에서는 날짜/연도 등과 헷갈리는 오탐이 너무 많아서 "+국가코드"로
    # 시작하는 국제전화 형태만 인정한다.
    text = soup.get_text(" ", strip=True)
    m = PHONE_RE.search(text)
    if m:
        return m.group(0).strip()

    return ""


def find_contact_link(soup: BeautifulSoup, base_url: str) -> str:
    links = soup.select("a[href]")

    def _search(keywords):
        for a in links:
            label = a.get_text(strip=True).lower()
            href = a.get("href", "")
            if any(kw in label for kw in keywords) or any(kw in href.lower() for kw in keywords):
                return urljoin(base_url, href)
        return ""

    return _search(STRONG_CONTACT_KEYWORDS) or _search(FALLBACK_CONTACT_KEYWORDS)


def fetch_soup(url: str):
    resp = SESSION.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return BeautifulSoup(resp.text, "html.parser")


# --- Playwright fallback (requests로 못 잡았을 때만, JS 렌더링 사이트 대비) ---
_pw_state = {"playwright": None, "browser": None, "page": None}


def _get_playwright_page():
    if _pw_state["page"] is None:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"], viewport={"width": 1366, "height": 900}
        )
        _pw_state["playwright"] = pw
        _pw_state["browser"] = browser
        _pw_state["page"] = context.new_page()
    return _pw_state["page"]


def close_playwright():
    if _pw_state["browser"] is not None:
        _pw_state["browser"].close()
        _pw_state["playwright"].stop()
        _pw_state["page"] = None


def fetch_soup_rendered(url: str):
    """requests로 못 잡았을 때(자바스크립트 렌더링 사이트 등)만 쓰는 2차 시도."""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    try:
        page = _get_playwright_page()
        page.goto(url, timeout=20000, wait_until="load")
        page.wait_for_timeout(1500)
        return BeautifulSoup(page.content(), "html.parser")
    except Exception:
        return None


def find_contact_info(website: str) -> dict:
    """C 단계까지 포함한 전체 흐름. requests로 둘 다 못 찾으면 Playwright로
    한 번 더 시도(JS 렌더링 사이트 대비). 그래도 실패하면 각 필드 빈 문자열."""
    url = normalize_url(website)
    if not url:
        return {"email": "", "phone": ""}

    try:
        soup = fetch_soup(url)
    except requests.exceptions.RequestException:
        soup = None

    email = extract_email_from_html(soup) if soup else ""
    phone = extract_phone_from_html(soup) if soup else ""

    if soup and (not email or not phone):
        contact_url = find_contact_link(soup, url)
        # 같은 도메인으로만 한정 (외부 링크 함부로 안 따라감)
        if contact_url and urlparse(contact_url).netloc == urlparse(url).netloc:
            try:
                contact_soup = fetch_soup(contact_url)
                if not email:
                    email = extract_email_from_html(contact_soup)
                if not phone:
                    phone = extract_phone_from_html(contact_soup)
            except requests.exceptions.RequestException:
                pass

    # requests로 아무것도 못 찾았으면(자바스크립트 렌더링 사이트일 가능성) Playwright로 재시도
    if not email and not phone:
        rendered_soup = fetch_soup_rendered(url)
        if rendered_soup:
            email = extract_email_from_html(rendered_soup)
            phone = extract_phone_from_html(rendered_soup)

    return {"email": email, "phone": phone}


def ensure_columns(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(raw_exhibitions)")
    existing = {row[1] for row in cur.fetchall()}
    for col, coltype in NEW_COLUMNS.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE raw_exhibitions ADD COLUMN {col} {coltype}")
    conn.commit()


def fetch_targets(conn, force: bool, limit: int):
    cur = conn.cursor()
    query = """
        SELECT id, name, website FROM raw_exhibitions
        WHERE is_active = 1 AND website IS NOT NULL AND website != ''
    """
    if not force:
        # 이메일/전화 둘 중 하나라도 비어있으면 재시도 대상 (OR)
        # -> 둘 다 채워졌을 때만 스킵. AND로 하면 "이메일은 찾았는데 전화는
        # 못 찾은" 행이 재시도 대상에서 빠지는 버그가 생김.
        query += " AND ((organizer_email IS NULL OR organizer_email = '') OR (organizer_phone IS NULL OR organizer_phone = ''))"
    query += " ORDER BY id"
    cur.execute(query)
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def save_result(conn, exhibition_id, email, phone, ts):
    conn.execute(
        """
        UPDATE raw_exhibitions
        SET organizer_email = COALESCE(NULLIF(?, ''), organizer_email),
            organizer_phone = COALESCE(NULLIF(?, ''), organizer_phone),
            contact_synced_at = ?
        WHERE id = ?
        """,
        (email, phone, ts, exhibition_id),
    )
    conn.commit()


def main():
    from datetime import datetime, timezone

    parser = argparse.ArgumentParser(description="공식 홈페이지에서 연락처(이메일/전화) 수집")
    parser.add_argument("--db", default="../../instance/sabuzak.db")
    parser.add_argument("--limit", type=int, default=0, help="테스트용 최대 N건 (0=전체)")
    parser.add_argument("--force", action="store_true", help="이미 채워진 것도 다시 시도")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"DB 파일을 찾을 수 없습니다: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    ensure_columns(conn)

    targets = fetch_targets(conn, args.force, args.limit)
    if not targets:
        print("수집할 대상이 없습니다 (모두 처리됨).")
        return

    print(f"대상: {len(targets)}건")
    found_email = 0
    found_phone = 0
    failed = 0

    for i, (exhibition_id, name, website) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {name} <- {website}")
        try:
            info = find_contact_info(website)
            ts = datetime.now(timezone.utc).isoformat()
            save_result(conn, exhibition_id, info["email"], info["phone"], ts)
            if info["email"]:
                found_email += 1
            if info["phone"]:
                found_phone += 1
            print(f"  -> 이메일: {info['email'] or '(못찾음)'} / 전화: {info['phone'] or '(못찾음)'}")
        except Exception as e:
            print(f"  -> 실패: {e}")
            failed += 1
        polite_sleep()

    conn.close()
    close_playwright()
    print(f"\n완료: 이메일 발견 {found_email}건 / 전화 발견 {found_phone}건 / 실패 {failed}건 (총 {len(targets)}건 중)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
tradefairdates.com 크롤링 -> SQLite DB 동기화 스크립트

목적:
    매번 전체를 처음부터 다시 크롤링하는 대신, 기존에 DB에 있는 박람회는
    그대로 두고(중복 저장 X), 새로 생긴 박람회만 추가하거나 정보가 바뀐
    항목만 업데이트합니다.

핵심 아이디어:
    - 각 박람회의 상세페이지 URL(detail_url)을 "고유 키"로 사용합니다.
      (tradefairdates.com에서 박람회마다 URL이 고유하게 부여되기 때문)
    - DB에 이미 있는 detail_url  -> 내용이 바뀐 필드만 업데이트 (이름이 같아도
      시작일/종료일이 바뀌면 업데이트 대상), last_updated_at 갱신
    - DB에 없는 detail_url       -> 새 행으로 INSERT
    - 이번 크롤링에서 안 보인(목록에서 사라진) 기존 항목 -> is_active = 0 으로
      표시만 하고 삭제하지 않음 (지난 박람회이거나 목록에서 내려간 것일 수 있음)

사전 준비:
    pip install requests beautifulsoup4

실행:
    python sync_to_db.py                       # 기본 DB 경로(sabuzak.db)에 동기화
    python sync_to_db.py --db ../instance/sabuzak.db
    python sync_to_db.py --details             # 상세페이지(축제URL/소개)도 함께 동기화
    python sync_to_db.py --sites bakery,seafood # 일부 카테고리만

주의:
    이 스크립트는 sabuzak 프로젝트의 실제 Flask-SQLAlchemy 모델(models.py)과는
    별개로 동작하는 "원본 데이터 테이블"(raw_exhibitions)을 SQLite에 만듭니다.
    Flask 앱의 Exhibition 모델에 그대로 매핑하고 싶다면, 이 테이블을 조회해서
    필요한 필드만 옮겨 담는 마이그레이션 코드를 앱 쪽에 추가하면 됩니다.
    (표 구조는 아래 init_db() 참고 — 필요에 맞게 컬럼을 조정하세요)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tradefairdates_scraper as tfd

SITES = {
    "bakery": ("Bakery Trade Shows", "https://www.tradefairdates.com/Bakery-Trade-Shows-Y36-S1.html"),
    "specialityfinefood": ("Speciality Fine Food Fairs", "https://www.tradefairdates.com/Speciality-Fine-Food-Fairs-Y108-S1.html"),
    "fancyfood": ("Fancy Food Shows", "https://www.tradefairdates.com/Fancy-Food-Shows-Y82-S1.html"),
    "seafood": ("Trade fair for Seafood", "https://www.tradefairdates.com/Trade-fair-for-Seafood-Y417-S1.html"),
    "beer": ("Trade Fairs for Beer", "https://www.tradefairdates.com/Trade-Fairs-for-Beer-Y414-S1.html"),
    "foodtrade": ("Food Trade Shows", "https://www.tradefairdates.com/Food-Trade-Shows-Y256-S1.html"),
    "foodfairs": ("Food Fairs", "https://www.tradefairdates.com/Food-Fairs-Y216-S1.html"),
}

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabuzak.db")

# DB 컬럼명은 영문으로 둔다 (SQL/ORM에서 매번 따옴표 처리를 안 해도 되고, 다른 도구와의
# 호환성도 더 좋음). 화면에 한글로 보여주는 건 Jinja 템플릿 쪽 라벨/필터가 담당한다.
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_exhibitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    detail_url      TEXT NOT NULL UNIQUE,
    name            TEXT,
    start_date      INTEGER,
    end_date        INTEGER,
    country         TEXT,
    city            TEXT,
    venue           TEXT,
    audience_note   TEXT,
    website         TEXT,
    intro           TEXT,
    category        TEXT,
    continent       TEXT,
    food_yn         INTEGER,
    scale           TEXT,
    keywords        TEXT,
    intro_ko        TEXT,
    classified_at   TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_updated_at TEXT NOT NULL
);
"""

NEW_COLUMNS = [
    "id", "detail_url", "name", "start_date", "end_date", "country", "city", "venue",
    "audience_note", "website", "intro", "category", "continent", "food_yn", "scale",
    "keywords", "intro_ko", "classified_at", "is_active", "last_updated_at",
]


def now_iso():
    # 마이크로초까지 포함: 동기화 직후 바로 분류 스크립트가 이어서 돌아도
    # (같은 초 안에 실행되는 경우) last_updated_at / classified_at 비교가 어긋나지 않도록 함
    return datetime.now(timezone.utc).isoformat()


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _old_row_to_new(old_cols, row):
    """예전 스키마(period 하나, first_seen_at/last_seen_at 포함, 혹은 한글 컬럼명 등)의
    한 행을 새 스키마 값으로 변환. old_cols는 {컬럼명}, row는 dict."""

    def pick(*names, default=None):
        for n in names:
            if n in old_cols and row.get(n) is not None:
                return row[n]
        return default

    start_date = pick("start_date", "시작일", default=None)
    end_date = pick("end_date", "종료일", default=None)
    if start_date is None and "period" in old_cols:
        start_date, end_date = tfd.parse_period(row.get("period", ""))
    # 0은 이 스크립트의 예전 버전이 "날짜 미상"에 썼던 값(오름차순 정렬 시 맨 위로
    # 올라오는 버그가 있었음) -> 지금 sentinel인 UNKNOWN_DATE로 교체
    if start_date in (None, 0):
        start_date = tfd.UNKNOWN_DATE
    if end_date in (None, 0):
        end_date = tfd.UNKNOWN_DATE

    return {
        "detail_url": row.get("detail_url"),
        "name": pick("name", "박람회명", default=""),
        "start_date": start_date,
        "end_date": end_date,
        "country": pick("country", "국가", default=""),
        "city": pick("city", "도시", default=""),
        "venue": pick("venue", "장소", default=""),
        "audience_note": pick("audience_note", "참관대상", default=""),
        "website": pick("website", "웹사이트", default=""),
        "intro": pick("intro", "상세설명", default=""),
        "category": pick("category", default=""),
        "continent": pick("continent", "대륙", default=None),
        "food_yn": pick("food_yn", default=None),
        "scale": pick("scale", "규모", default=None),
        "keywords": pick("keywords", "키워드", default=None),
        "intro_ko": pick("intro_ko", default=None),
        "classified_at": pick("classified_at", default=None),
        "is_active": pick("is_active", default=1),
        "last_updated_at": pick("last_updated_at", default=now_iso()),
    }


def init_db(conn):
    """raw_exhibitions를 최신 스키마로 만든다. 테이블이 없으면 새로 만들고,
    예전 스키마로 이미 있으면 데이터를 보존하면서 새 스키마로 옮긴다."""
    if not _table_exists(conn, "raw_exhibitions"):
        conn.execute(SCHEMA)
        conn.commit()
        return

    cols = {row[1] for row in conn.execute("PRAGMA table_info(raw_exhibitions)")}
    if cols == set(NEW_COLUMNS):
        return  # 이미 최신 스키마

    print("  -> 예전 스키마 감지, 데이터를 보존하며 새 스키마로 마이그레이션합니다...")
    conn.row_factory = sqlite3.Row
    old_rows = [dict(r) for r in conn.execute("SELECT * FROM raw_exhibitions")]
    conn.row_factory = None

    conn.execute("ALTER TABLE raw_exhibitions RENAME TO raw_exhibitions_old")
    conn.execute(SCHEMA)

    for row in old_rows:
        new_row = _old_row_to_new(set(row.keys()), row)
        conn.execute(
            """
            INSERT INTO raw_exhibitions
                (detail_url, name, start_date, end_date, country, city, venue,
                 audience_note, website, intro, category, continent, food_yn, scale, keywords,
                 intro_ko, classified_at, is_active, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_row["detail_url"], new_row["name"], new_row["start_date"], new_row["end_date"],
                new_row["country"], new_row["city"], new_row["venue"], new_row["audience_note"],
                new_row["website"], new_row["intro"], new_row["category"], new_row["continent"],
                new_row["food_yn"], new_row["scale"], new_row["keywords"], new_row["intro_ko"],
                new_row["classified_at"], new_row["is_active"], new_row["last_updated_at"],
            ),
        )

    conn.execute("DROP TABLE raw_exhibitions_old")
    conn.commit()
    print(f"  -> 마이그레이션 완료: {len(old_rows)}건 이전됨")


def row_key(row):
    return row.get("_detail_url") or (
        row["전시회명"], row["시작일"], row["종료일"], row["개최장소(베뉴)"]
    )


def crawl_selected_sites(labels_urls, with_details, verbose=True):
    """여러 카테고리를 순회하며 전체 페이지 수집 + 통합 중복 제거.

    반환값: (all_rows, failed_labels). failed_labels는 카테고리 목록 페이지
    자체를 못 가져온(네트워크 오류 등) 카테고리들 — 이 카테고리는 "이번에
    크롤링해서 확인함"이 아니라 "크롤링을 시도조차 못 함"이므로, 호출 쪽에서
    deactivate_missing()에 넘길 때 제외해야 한다. 안 그러면 일시적인 네트워크
    장애로 크롤링이 전부 실패했을 때 기존 데이터가 통째로 비활성 처리되는
    사고가 날 수 있다."""
    all_rows = []
    failed_labels = []
    seen_keys = set()

    for label, url in labels_urls:
        if verbose:
            print(f"\n=== [{label}] 크롤링 시작 ===")
        try:
            rows = tfd.crawl_all_pages(url)
        except requests.exceptions.RequestException as e:
            print(f"  -> 실패: {e}")
            failed_labels.append(label)
            continue

        new_rows = []
        for r in rows:
            key = row_key(r)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            r["category"] = label
            new_rows.append(r)

        if verbose:
            print(f"  -> {label}: 총 {len(rows)}건 중 신규(중복 제외) {len(new_rows)}건")
        all_rows.extend(new_rows)

    if with_details:
        total = len(all_rows)
        print(f"\n=== 상세페이지 수집 시작: 총 {total}건 ===")
        for i, row in enumerate(all_rows, 1):
            detail_url = row.get("_detail_url", "")
            if not detail_url:
                continue
            print(f"  [{i}/{total}] {row['전시회명']}")
            try:
                detail = tfd.parse_detail(detail_url)
                row["축제URL"] = detail["축제URL"]
                row["축제소개"] = detail["축제소개"]
            except requests.exceptions.RequestException as e:
                print(f"    -> 실패: {e}")
            tfd.polite_sleep()

    return all_rows, failed_labels


def sync_rows(conn, rows):
    """크롤링 결과를 DB에 반영. 반환: (신규건수, 업데이트건수, 변경없음건수)"""
    cur = conn.cursor()
    ts = now_iso()

    new_count = 0
    updated_count = 0
    unchanged_count = 0
    seen_urls = set()

    for row in rows:
        detail_url = row.get("_detail_url", "")
        if not detail_url:
            continue
        seen_urls.add(detail_url)

        cur.execute(
            "SELECT name, start_date, end_date, country, city, venue, audience_note, "
            "website, intro, category FROM raw_exhibitions WHERE detail_url = ?",
            (detail_url,),
        )
        existing = cur.fetchone()

        # 이름이 같아도 날짜(시작일/종료일)가 바뀌면 다른 값으로 취급되어 아래
        # changed 비교에서 자동으로 업데이트 대상이 된다.
        new_values = (
            row["전시회명"],
            row["시작일"],
            row["종료일"],
            row["개최국"],
            row["개최도시"],
            row["개최장소(베뉴)"],
            row.get("참관대상", ""),
            row.get("축제URL", ""),
            row.get("축제소개", ""),
            row.get("category", ""),
        )

        if existing is None:
            cur.execute(
                """
                INSERT INTO raw_exhibitions
                    (detail_url, name, start_date, end_date, country, city, venue,
                     audience_note, website, intro, category, is_active, last_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (detail_url, *new_values, ts),
            )
            new_count += 1
        else:
            # 상세페이지를 이번에 안 가져왔으면(웹사이트/상세설명이 빈 값) 기존 값 보존
            merged = list(new_values)
            if not row.get("축제URL") and existing[7]:
                merged[7] = existing[7]
            if not row.get("축제소개") and existing[8]:
                merged[8] = existing[8]

            changed = tuple(merged) != tuple(existing)
            if changed:
                cur.execute(
                    """
                    UPDATE raw_exhibitions
                    SET name=?, start_date=?, end_date=?, country=?, city=?, venue=?,
                        audience_note=?, website=?, intro=?, category=?, is_active=1,
                        last_updated_at=?
                    WHERE detail_url=?
                    """,
                    (*merged, ts, detail_url),
                )
                updated_count += 1
            else:
                cur.execute(
                    "UPDATE raw_exhibitions SET is_active=1 WHERE detail_url=?",
                    (detail_url,),
                )
                unchanged_count += 1

    conn.commit()
    return new_count, updated_count, unchanged_count, seen_urls


def deactivate_missing(conn, crawled_categories, seen_urls):
    """이번에 크롤링한 카테고리들 안에서, 더 이상 목록에 없는 기존 항목을 비활성 처리."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT detail_url FROM raw_exhibitions "
        f"WHERE is_active = 1 AND category IN ({','.join('?' * len(crawled_categories))})",
        crawled_categories,
    )
    existing_active = {r[0] for r in cur.fetchall()}
    to_deactivate = existing_active - seen_urls

    if to_deactivate:
        cur.executemany(
            "UPDATE raw_exhibitions SET is_active = 0 WHERE detail_url = ?",
            [(u,) for u in to_deactivate],
        )
        conn.commit()
    return len(to_deactivate)


def main():
    parser = argparse.ArgumentParser(description="tradefairdates.com -> SQLite 동기화")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB 파일 경로")
    parser.add_argument(
        "--sites",
        default=",".join(SITES.keys()),
        help=f"쉼표로 구분한 카테고리 키. 기본값: 전체 ({','.join(SITES.keys())})",
    )
    parser.add_argument("--details", action="store_true", help="상세페이지 정보도 함께 수집")
    parser.add_argument(
        "--no-deactivate",
        action="store_true",
        help="목록에서 사라진 기존 항목을 비활성 처리하지 않음",
    )
    args = parser.parse_args()

    site_keys = [k.strip() for k in args.sites.split(",") if k.strip()]
    unknown = [k for k in site_keys if k not in SITES]
    if unknown:
        print(f"알 수 없는 카테고리 키: {unknown}")
        print(f"사용 가능한 키: {list(SITES.keys())}")
        sys.exit(1)

    labels_urls = [SITES[k] for k in site_keys]
    labels = [label for label, _ in labels_urls]

    conn = sqlite3.connect(args.db)
    init_db(conn)

    rows, failed_labels = crawl_selected_sites(labels_urls, with_details=args.details)
    new_count, updated_count, unchanged_count, seen_urls = sync_rows(conn, rows)

    deactivated = 0
    if failed_labels:
        print(f"\n경고: 다음 카테고리는 크롤링 자체가 실패해서 비활성 처리에서 제외합니다: {failed_labels}")
    succeeded_labels = [label for label in labels if label not in failed_labels]
    if not args.no_deactivate and succeeded_labels:
        deactivated = deactivate_missing(conn, succeeded_labels, seen_urls)

    conn.close()

    print("\n=== 동기화 완료 ===")
    print(f"DB 파일: {args.db}")
    print(f"신규 추가: {new_count}건")
    print(f"내용 업데이트: {updated_count}건")
    print(f"변경 없음: {unchanged_count}건")
    print(f"목록에서 사라져 비활성 처리: {deactivated}건")


if __name__ == "__main__":
    main()

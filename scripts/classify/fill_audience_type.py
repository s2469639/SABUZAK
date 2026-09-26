#!/usr/bin/env python3
"""raw_exhibitions에서 audience_type(B2B/B2C)이 비어있는 박람회를 채우는 스크립트.

audience_type 컬럼은 지금까지 아무 스크립트도 채운 적이 없어서 전부 비어있다
(원문 참관대상 텍스트는 audience_note에 크롤링 시점에 이미 들어있음 -
tradefairdates_scraper.py의 "참관대상" 필드). 이 스크립트는 그 audience_note
원문으로 B2B/B2C를 정하는데, API 호출을 아예 안 한다(토큰 절약).

기준:
    1) audience_note 원문에 trade/professional/industry 계열 키워드만 있으면
       "B2B", public/consumer/general 계열 키워드만 있으면 "B2C", 두 계열이
       다 있으면(예: "trade visitors + public weekend") "B2B/B2C" - 텍스트
       매칭만으로 정한다.
    2) audience_note가 비어있거나 애매해서 키워드로 못 정하면, AI 호출 없이
       그냥 "B2B"로 채운다 - 이 DB의 박람회 대부분이 식품 전문 무역박람회라
       B2B 비중이 원래 압도적으로 높아서, 애매한 건 AI한테 물어봐도 결국
       B2B로 나올 확률이 높다. "미상"으로 남겨두지 않는다.

실행:
    python fill_audience_type.py                 # 기본 DB, 비어있는 전체
    python fill_audience_type.py --limit 20       # 테스트용 20건만
    python fill_audience_type.py --dry-run        # 저장하지 않고 결과만 출력
"""

import argparse
import os
import re
import sqlite3
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "instance", "sabuzak.db"
)

# audience_note 원문 키워드 (tradefairdates.com은 영문 기준으로 적어둠)
B2B_PATTERNS = re.compile(
    r"\b(trade|professional|industry|business|b2b)\b.*\b(visitor|only|exclusive)\b"
    r"|\b(trade\s+visitors?\s+only|professionals?\s+only|industry\s+only)\b",
    re.I,
)
B2C_PATTERNS = re.compile(
    r"\b(public|consumer|general\s+public|open\s+to\s+the\s+public|b2c)\b",
    re.I,
)


def keyword_guess(audience_note):
    """audience_note 원문 텍스트만으로 판단 (API 호출 없음). 못 정하면 None."""
    text = (audience_note or "").strip()
    if not text:
        return None
    is_b2b = bool(B2B_PATTERNS.search(text))
    is_b2c = bool(B2C_PATTERNS.search(text))
    if is_b2b and is_b2c:
        return "B2B/B2C"
    if is_b2b:
        return "B2B"
    if is_b2c:
        return "B2C"
    return None


def fetch_targets(conn, limit: int):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, audience_note
        FROM raw_exhibitions
        WHERE is_active = 1
          AND (audience_type IS NULL OR audience_type = '' OR audience_type = '미상')
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def save_audience_type(conn, exhibition_id, value):
    conn.execute("UPDATE raw_exhibitions SET audience_type=? WHERE id=?", (value, exhibition_id))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="audience_type(B2B/B2C)이 비어있는 박람회를 채움")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=0, help="테스트용: 최대 N건만 처리 (0=전체)")
    parser.add_argument("--dry-run", action="store_true", help="DB에 저장하지 않고 결과만 출력")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {args.db}")

    conn = sqlite3.connect(args.db)
    targets = fetch_targets(conn, args.limit)
    if not targets:
        print("audience_type이 비어있는 박람회가 없습니다.")
        conn.close()
        return

    print(f"대상: {len(targets)}건")

    counts = {"B2B": 0, "B2C": 0, "B2B/B2C": 0}
    from_keyword = 0
    from_default = 0

    for i, (exhibition_id, name, audience_note) in enumerate(targets, 1):
        value = keyword_guess(audience_note)
        source = "키워드"
        if value:
            from_keyword += 1
        else:
            # 키워드로 못 정하면 API 호출 없이 그냥 B2B로 기본 처리 (토큰 절약).
            # 이 DB의 박람회는 대부분 식품 전문 무역박람회라 B2B가 압도적으로
            # 많아서, 애매한 건 물어봐도 결국 B2B로 나올 확률이 높음.
            value = "B2B"
            from_default += 1
            source = "기본값"

        counts[value] += 1
        print(f"[{i}/{len(targets)}] {name} -> {value} ({source})")
        if not args.dry_run:
            save_audience_type(conn, exhibition_id, value)

    conn.close()
    print(
        f"\n완료: B2B {counts['B2B']} · B2C {counts['B2C']} · B2B/B2C {counts['B2B/B2C']} "
        f"(키워드로 {from_keyword}건, 기본값 처리 {from_default}건 - API 호출 없음)"
    )
    if args.dry_run:
        print("(--dry-run: DB에는 저장하지 않았습니다)")


if __name__ == "__main__":
    main()

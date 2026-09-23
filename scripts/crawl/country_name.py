import argparse
import sqlite3
import pycountry
from babel import Locale

KO = Locale("ko")

# pycountry/babel로도 못 찾는 표기만 최소로 직접 매핑
MANUAL_OVERRIDES = {
    "Czech Republic": "체코",
    "Ivory Coast": "코트디부아르",
    "Laos": "라오스",
    "Moldova": "몰도바",
    "Myanmar": "미얀마",
    "Myanmar (Burma)": "미얀마",
    "North Korea": "북한",
    "Romania": "루마니아",
    "Russia": "러시아",
    "South Africa": "남아프리카 공화국",
    "South Korea": "대한민국",
    "Syria": "시리아",
    "Turkey": "튀르키예",
    "UAE": "아랍에미리트",
    "Ukraine": "우크라이나",
    "Vietnam": "베트남",
    "Western Sahara": "사하라 서부",
}


def resolve_korean_name(country_en: str) -> str:
    """영문 국가명 -> 한글 국가명. 못 찾으면 영문 원문 그대로 반환."""
    if country_en in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[country_en]

    try:
        match = pycountry.countries.get(name=country_en)
        if match is None:
            matches = pycountry.countries.search_fuzzy(country_en)
            match = matches[0] if matches else None
    except LookupError:
        match = None

    if match is not None:
        ko_name = KO.territories.get(match.alpha_2)
        if ko_name:
            return ko_name

    return country_en


def ensure_country_ko_column(conn):
    """raw_exhibitions 테이블에 country_ko 컬럼이 없으면 자동으로 추가한다."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(raw_exhibitions)")
    existing = {row[1] for row in cur.fetchall()}
    if "country_ko" not in existing:
        cur.execute("ALTER TABLE raw_exhibitions ADD COLUMN country_ko TEXT")
        conn.commit()
        print("✨ 'country_ko' 컬럼이 성공적으로 생성되었습니다!")


def translate_countries(db_path):
    """영문 원본(country)은 그대로 두고, country_ko에만 한글 국가명을 채운다."""
    try:
        conn = sqlite3.connect(db_path)
        ensure_country_ko_column(conn)
        cursor = conn.cursor()

        cursor.execute("SELECT id, country FROM raw_exhibitions")
        rows = cursor.fetchall()

        cache = {}
        update_count = 0
        unresolved = set()

        for row_id, country in rows:
            if not country:
                continue
            if country not in cache:
                cache[country] = resolve_korean_name(country)
            korean_country = cache[country]
            if korean_country == country:
                unresolved.add(country)

            cursor.execute(
                "UPDATE raw_exhibitions SET country_ko = ? WHERE id = ?",
                (korean_country, row_id),
            )
            update_count += 1

        conn.commit()
        conn.close()

        print(f"✨ 총 {update_count}건의 country_ko를 채웠습니다! (고유 국가 {len(cache)}개)")
        if unresolved:
            print(f"⚠️ 한글명을 못 찾아 영문 그대로 둔 국가 ({len(unresolved)}개): {sorted(unresolved)}")
            print("    -> 위 목록은 MANUAL_OVERRIDES에 직접 추가해서 재실행하면 됩니다.")
    except Exception as e:
        print(f"⚠️ 에러 발생: {e}")


def main():
    parser = argparse.ArgumentParser(description="raw_exhibitions.country_ko 자동 채우기")
    parser.add_argument("--db", default="../../instance/sabuzak.db", help="SQLite database path")
    args, unknown = parser.parse_known_args()

    print(f"📂 사용할 데이터베이스 경로: {args.db}")
    print("🌍 국가명 한글 매핑 변환을 시작합니다...")
    translate_countries(args.db)
    print("🎉 모든 작업이 완료되었습니다!")


if __name__ == "__main__":
    main()

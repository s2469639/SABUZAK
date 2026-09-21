import argparse
import sqlite3

# 1. 영어 국가명을 한글로 매핑하는 사전 (필요한 국가를 계속 추가하세요)
COUNTRY_MAP = {
    "Morocco": "모로코",
    "Australia": "호주",
    "Poland": "폴란드",
    "Vietnam": "베트남",
    "Indonesia": "인도네시아",
    "Germany": "독일",
    "China": "중국",
    "Italy": "이탈리아",
    "Austria": "오스트리아",
    "Turkey": "튀르키예",
    "Myanmar": "미얀마",
    "Ivory Coast": "코트디부아르",
    "Ukraine": "우크라이나",
    "Moldova": "몰도바",
}


def ensure_country_ko_column(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(raw_exhibitions)")
    existing = {row[1] for row in cur.fetchall()}
    if "country_ko" not in existing:
        cur.execute("ALTER TABLE raw_exhibitions ADD COLUMN country_ko TEXT")
        conn.commit()


def translate_countries(db_path):
    """country(영문)는 그대로 두고, country_ko 컬럼에 한글 국가명을 채운다.
    무역 실무자용 화면에서는 country_ko(있으면)를 표시하고, 없으면 country
    원문을 그대로 보여주면 됨 (COALESCE(country_ko, country) 형태로 조회)."""
    try:
        conn = sqlite3.connect(db_path)
        ensure_country_ko_column(conn)
        cursor = conn.cursor()

        cursor.execute("SELECT id, country FROM raw_exhibitions")
        rows = cursor.fetchall()

        update_count = 0
        for row_id, country in rows:
            if country in COUNTRY_MAP:
                korean_country = COUNTRY_MAP[country]
                cursor.execute(
                    """
                    UPDATE raw_exhibitions
                    SET country_ko = ?
                    WHERE id = ?
                    """,
                    (korean_country, row_id),
                )
                update_count += 1

        conn.commit()
        conn.close()
        print(
            f"✨ 총 {update_count}개의 국가명을 country_ko 컬럼에 한글로 채웠습니다! "
            f"(country 원문은 그대로 보존됨)"
        )
    except Exception as e:
        print(f"⚠️ 국가명 변환 중 에러 발생: {e}")


def main():
    parser = argparse.ArgumentParser(description="raw_exhibitions에 country_ko 채우기")
    parser.add_argument(
        "--db", default="../../instance/sabuzak.db", help="SQLite database path"
    )
    args, unknown = parser.parse_known_args()

    print(f"📂 사용할 데이터베이스 경로: {args.db}")
    print("🌍 country_ko 컬럼에 한글 국가명 채우기를 시작합니다...")
    translate_countries(args.db)


if __name__ == "__main__":
    main()

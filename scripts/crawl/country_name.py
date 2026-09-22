import argparse
import sqlite3

# 전 세계 주요 국가 매핑 사전 (필요한 국가를 계속 추가하세요)
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

    update_count = 0
    for row_id, country in rows:
      if country:
        # 사전에 있으면 한글로, 없으면 영문 원문 그대로 country_ko에 입력
        korean_country = COUNTRY_MAP.get(country, country)
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
        f"✨ 총 {update_count}개의 국가명이 한글(country_ko)로 변환되었습니다!"
    )
  except Exception as e:
    print(f"⚠️ 에러 발생: {e}")


def main():
  parser = argparse.ArgumentParser(description="Add country_ko column and map")
  parser.add_argument(
      "--db", default="../../instance/sabuzak.db", help="SQLite database path"
  )
  args, unknown = parser.parse_known_args()

  print(f"📂 사용할 데이터베이스 경로: {args.db}")
  print("🌍 국가명 한글 매핑 변환을 시작합니다...")
  translate_countries(args.db)
  print("🎉 모든 작업이 완료되었습니다!")


if __name__ == "__main__":
  main()
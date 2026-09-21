import argparse
import sqlite3
from googletrans import Translator

# 1. 자주 쓰는 주요 국가 수동 매핑 사전 (필요시 추가)
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

translator = Translator()


def ensure_country_ko_column(conn):
  cur = conn.cursor()
  cur.execute("PRAGMA table_info(raw_exhibitions)")
  existing = {row[1] for row in cur.fetchall()}
  if "country_ko" not in existing:
    cur.execute("ALTER TABLE raw_exhibitions ADD COLUMN country_ko TEXT")
    conn.commit()


def get_korean_name(country):
  if not country:
    return country
  # 1. 수동 사전에 있으면 사용
  if country in COUNTRY_MAP:
    return COUNTRY_MAP[country]
  # 2. 사전에 없으면 구글 번역기로 자동 번역 시도
  try:
    res = translator.translate(country, dest="ko")
    return res.text
  except Exception:
    return country


def translate_countries(db_path):
  try:
    conn = sqlite3.connect(db_path)
    ensure_country_ko_column(conn)
    cursor = conn.cursor()

    cursor.execute("SELECT id, country FROM raw_exhibitions")
    rows = cursor.fetchall()

    update_count = 0
    for row_id, country in rows:
      if country:
        korean_country = get_korean_name(country)
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
    print(f"✨ 총 {update_count}개의 국가명이 한글(country_ko)로 변환되었습니다!")
  except Exception as e:
    print(f"⚠️ 에러 발생: {e}")


def main():
  parser = argparse.ArgumentParser(description="Sync exhibitions to DB")
  parser.add_argument(
      "--db", default="../../instance/sabuzak.db", help="SQLite database path"
  )
  args, unknown = parser.parse_known_args()

  print(f"📂 사용할 데이터베이스 경로: {args.db}")
  print("🔄 데이터 크롤링 및 DB 동기화 작업 수행 중...")

  print("🌍 모든 국가명 자동 한글 변환을 시작합니다...")
  translate_countries(args.db)


if __name__ == "__main__":
  main()
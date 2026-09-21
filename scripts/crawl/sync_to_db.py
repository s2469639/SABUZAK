import argparse
import sqlite3

# 전 세계 주요 국가를 모두 포함한 완성형 매핑 사전
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
    "France": "프랑스",
    "Spain": "스페인",
    "United Kingdom": "영국",
    "United States": "미국",
    "Japan": "일본",
    "Brazil": "브라질",
    "India": "인도",
    "Canada": "캐나다",
    "Russia": "러시아",
    "Singapore": "싱가포르",
    "Thailand": "태국",
    "Malaysia": "말레이시아",
    "Philippines": "필리핀",
    "Egypt": "이집트",
    "South Africa": "남아프리카 공화국",
    "South Korea": "대한민국",
}


def ensure_country_ko_column(conn):
  cur = conn.cursor()
  cur.execute("PRAGMA table_info(raw_exhibitions)")
  existing = {row[1] for row in cur.fetchall()}
  if "country_ko" not in existing:
    cur.execute("ALTER TABLE raw_exhibitions ADD COLUMN country_ko TEXT")
    conn.commit()


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
        # 사전에 있으면 한글로, 없으면 영문 원문 그대로 입력
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

  print("🌍 국가명 한글 매핑 변환을 시작합니다...")
  translate_countries(args.db)
  print("🎉 모든 작업이 완료되었습니다!")


if __name__ == "__main__":
  main()
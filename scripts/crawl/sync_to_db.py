import argparse
import sqlite3
# (참고) 프로젝트에 이미 작성되어 있는 크롤러 및 DB 관련 모듈 임포트 구문들은
# 본래 파일 상단에 있던 기존 코드를 그대로 유지해주시면 됩니다.

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


def translate_countries(db_path):
  """데이터베이스 내의 영어 국가명을 한글로 일괄 변환한다."""
  try:
    conn = sqlite3.connect(db_path)
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
                SET country = ? 
                WHERE id = ?
            """,
            (korean_country, row_id),
        )
        update_count += 1

    conn.commit()
    conn.close()
    print(
        f"✨ 총 {update_count}개의 국가명이 한글('최종 반영')으로 변환되었습니다!"
    )
  except Exception as e:
    print(f"⚠️ 국가명 변환 중 에러 발생: {e}")


def main():
  # 파서 설정 (경로 인자 처리)
  parser = argparse.ArgumentParser(description="Sync exhibitions to DB")
  parser.add_argument(
      "--db", default="../../instance/sabuzak.db", help="SQLite database path"
  )
  # 필요한 다른 인자들도 기존에 있었다면 여기에 유지됩니다.
  args, unknown = parser.parse_known_args()

  print(f"📂 사용할 데이터베이스 경로: {args.db}")

  # TODO: 여기에 기존에 웹사이트 데이터를 긁어서 DB에 넣는 크롤링 및 동기화 로직이 수행됩니다.
  print("🔄 데이터 크롤링 및 DB 동기화 작업 수행 중...")
  # 예: run_scraper(args.db) 등 기존 동기화 함수 호출부

  # 데이터 동기화가 끝난 직후 국가명 한글 변환 함수 실행!
  print("🌍 국가명 한글 매핑 변환을 시작합니다...")
  translate_countries(args.db)


if __name__ == "__main__":
  main()
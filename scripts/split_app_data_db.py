"""
instance/sabuzak.db 안에 같이 있던 users/products 테이블을
instance/app_data.db 로 분리 이전하는 1회성 스크립트.

sabuzak.db 쪽 users/products는 이 스크립트 실행 후 삭제한다
(더 이상 그쪽에서 안 쓰임 - config.py가 이제 이 테이블들을
app_data.db(SQLALCHEMY_BINDS["app_data"])에서 읽도록 바뀌었기 때문).

사용법 (sabuzak 루트에서):
    python scripts/split_app_data_db.py
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OLD_DB = BASE_DIR / "instance" / "sabuzak.db"
NEW_DB = BASE_DIR / "instance" / "app_data.db"


def main():
    if not OLD_DB.exists():
        print(f"기존 DB가 없습니다: {OLD_DB}")
        return

    con = sqlite3.connect(NEW_DB)
    cur = con.cursor()
    cur.execute("ATTACH DATABASE ? AS old", (str(OLD_DB),))

    tables = [row[0] for row in cur.execute(
        "SELECT name FROM old.sqlite_master WHERE type='table' AND name IN ('users','products')"
    ).fetchall()]

    if not tables:
        print("옮길 users/products 테이블이 old DB에 없습니다 (이미 분리됐거나 처음부터 없었음).")
        con.close()
        return

    for table in tables:
        print(f"{table} 복사 중...")
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(f"CREATE TABLE {table} AS SELECT * FROM old.{table}")
        count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  -> {count}건 이전 완료")

    con.commit()
    cur.execute("DETACH DATABASE old")
    con.close()

    print(f"\n완료: {NEW_DB} 에 users/products 저장됨.")
    print("확인 후, 기존 sabuzak.db의 users/products 테이블은 아래처럼 직접 지우면 됩니다:")
    print(f'  sqlite3 "{OLD_DB}" "DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS products;"')


if __name__ == "__main__":
    main()

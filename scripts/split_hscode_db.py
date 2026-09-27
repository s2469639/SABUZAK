"""
instance/sabuzak.db 안에 같이 있던 hs0code_master/ntm_measures 테이블을
instance/hscode.db 로 분리 이전하는 1회성 스크립트.

사용법 (sabuzak 루트에서):
    python scripts/split_hscode_db.py
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OLD_DB = BASE_DIR / "instance" / "sabuzak.db"
NEW_DB = BASE_DIR / "instance" / "hscode.db"

TABLES = ("hs0code_master", "ntm_measures")


def main():
    if not OLD_DB.exists():
        print(f"기존 DB가 없습니다: {OLD_DB}")
        return

    con = sqlite3.connect(NEW_DB)
    cur = con.cursor()
    cur.execute("ATTACH DATABASE ? AS old", (str(OLD_DB),))

    existing = [
        row[0]
        for row in cur.execute(
            "SELECT name FROM old.sqlite_master WHERE type='table' AND name IN (?, ?)",
            TABLES,
        ).fetchall()
    ]

    if not existing:
        print("옮길 테이블이 old DB에 없습니다 (이미 분리됐거나 처음부터 없었음).")
        con.close()
        return

    for table in existing:
        print(f"{table} 복사 중...")
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(f"CREATE TABLE {table} AS SELECT * FROM old.{table}")
        count = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  -> {count}건 이전 완료")

    con.commit()
    cur.execute("DETACH DATABASE old")
    con.close()

    print(f"\n완료: {NEW_DB} 에 hs0code_master/ntm_measures 저장됨.")
    print("확인 후, 기존 sabuzak.db 쪽은 아래처럼 지우면 됩니다:")
    print(
        f'  sqlite3 "{OLD_DB}" "DROP TABLE IF EXISTS hs0code_master; '
        f'DROP TABLE IF EXISTS ntm_measures;"'
    )


if __name__ == "__main__":
    main()

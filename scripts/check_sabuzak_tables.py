import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "instance" / "sabuzak.db"
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"{DB} 안의 테이블: {tables}")

if "users" in tables:
    count = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"users 테이블 존재, {count}건")
else:
    print("users 테이블이 없습니다.")

con.close()

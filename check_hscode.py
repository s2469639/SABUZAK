import os
import sqlite3

DB_PATH = os.path.join("instance", "hscode.db")

if not os.path.exists(DB_PATH):
    print(f"파일이 없습니다: {DB_PATH}")
    print("-> scripts/split_hscode_db.py를 실행했는지, 또는 hscode_recommend/make_db.py로")
    print("   생성한 sabuzak.db를 instance/hscode.db로 옮겼는지 확인해보세요.")
    raise SystemExit(1)

conn = sqlite3.connect(DB_PATH)
try:
    total = conn.execute("SELECT COUNT(*) FROM hs0code_master").fetchone()[0]
    print(f"hs0code_master 전체 행 수: {total}")

    for keyword in ("김", "유과", "약과"):
        rows = conn.execute(
            "SELECT hscode, name_ko FROM hs0code_master WHERE name_ko LIKE ? LIMIT 5",
            (f"%{keyword}%",),
        ).fetchall()
        print(f"\n'{keyword}' 검색 결과 ({len(rows)}건):")
        for r in rows:
            print(" ", r)
except sqlite3.OperationalError as e:
    print(f"쿼리 실패: {e}")
    print("-> hs0code_master 테이블이 이 DB에 없는 것 같습니다.")
finally:
    conn.close()

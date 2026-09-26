import sqlite3

conn = sqlite3.connect("instance/sabuzak.db")
rows = conn.execute(
    "SELECT TRIM(scale), COUNT(*) FROM raw_exhibitions GROUP BY TRIM(scale)"
).fetchall()
for r in rows:
    print(r)
conn.close()

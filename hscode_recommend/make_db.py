import sqlite3
import pandas as pd

print("관세청 엑셀 데이터 읽는 중...")
df = pd.read_excel("관세청_HS부호_20260101 (1).xlsx")

# 엑셀의 컬럼 구조를 분석하여 프로그램이 어떤 이름으로 찾든 다 매칭되도록 복제합니다.
# 1번 열(HS부호 계열) -> hscode, HS부호 로 동시 저장
if "HS부호" in df.columns:
    df["hscode"] = df["HS부호"]
else:
    df["hscode"] = df.iloc[:, 0]

# 4번 열(한글품목명 계열) -> name_ko, hsk_name, 한글품목명 로 동시 저장
if "한글품목명" in df.columns:
    df["name_ko"] = df["한글품목명"]
    df["hsk_name"] = df["한글품목명"]
else:
    if len(df.columns) >= 4:
        df["name_ko"] = df.iloc[:, 3]
        df["hsk_name"] = df.iloc[:, 3]

# SQLite DB에 hs0code_master 테이블로 저장
conn = sqlite3.connect("sabuzak.db")
df.to_sql("hs0code_master", conn, if_exists="replace", index=False)
conn.close()

print("✨ 모든 컬럼 호환성 매핑 및 DB 적재 완료!")
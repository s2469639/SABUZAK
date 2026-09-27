import sqlite3
import pandas as pd

# 1. 관세청 엑셀 파일 읽기
df = pd.read_excel("관세청_HS부호_20260101 (1).xlsx")

# [디버깅용] 엑셀 파일에 실제 어떤 열 이름들이 들어있는지 출력해 확인합니다
print("엑셀 파일의 원래 열 이름들:", df.columns.tolist())

# 2. 관세청 엑셀의 컬럼 구조에 맞춰 프로그램이 읽을 수 있는 이름(hscode, name_ko)으로 강제 변경
# (관세청 엑셀 양식에 따라 첫 번째 컬럼이 세번, 세 번째 컬럼이 품명인 경우를 대응)
if len(df.columns) >= 3:
    df.columns = ["hscode", "hsk_name", "name_ko"] + list(df.columns[3:])
elif len(df.columns) == 2:
    df.columns = ["hscode", "name_ko"] + list(df.columns[2:])

# 3. SQLite DB에 hs0code_master 테이블로 저장
conn = sqlite3.connect("../instance/sabuzak.db")
df.to_sql("hs0code_master", conn, if_exists="replace", index=False)
conn.close()

print("✨ 관세청 마스터 데이터 컬럼 매핑 및 DB 적재 완료!")
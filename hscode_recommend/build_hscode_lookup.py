#!/usr/bin/env python3
"""
data.go.kr에서 내려받은 "관세청_HS부호" 파일(xlsx/csv)을 읽어서
hscode_master.db의 hscode_master 테이블에 저장하는 배치 스크립트.

왜 실시간 API 대신 파일을 쓰나:
    - HS코드 품목명은 거의 안 바뀌는 참조 데이터라 매번 API 호출할 필요가 없음
    - 파일은 활용신청 승인 없이 로그인만 하면 바로 받을 수 있음
    - 1만 개 넘는 HS코드를 한 번에 다 받아서 로컬 DB에 넣어두는 게
      매번 API로 하나씩 조회하는 것보다 빠르고 안정적임

사전 준비:
    1) https://www.data.go.kr/data/15049722/fileData.do 에서 로그인 후
       "관세청_HS부호" 파일(xlsx)을 내려받는다
    2) pip install pandas openpyxl (requirements.txt에 이미 포함됨)

실행:
    python build_hscode_lookup.py --file 관세청_HS부호.xlsx

    # 컬럼명을 자동으로 못 찾으면 아래처럼 직접 지정
    python build_hscode_lookup.py --file 관세청_HS부호.xlsx \
        --hscode-col "HS부호" --name-ko-col "한글품목명" --name-en-col "영문품목명"

    # 일단 컬럼 목록만 보고 싶으면
    python build_hscode_lookup.py --file 관세청_HS부호.xlsx --list-columns
"""

import argparse
import os
import sqlite3
import sys

import pandas as pd

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hscode_master.db")

HSCODE_COL_HINTS = ["HS부호", "HS10단위부호", "HS코드", "hscode", "HS_CD", "HS부호(10단위)"]
NAME_KO_COL_HINTS = ["한글품목명", "한글 품목명", "품목명(한글)", "품명"]
NAME_EN_COL_HINTS = ["영문품목명", "영문 품목명", "품목명(영문)", "영문품명"]


def _guess_column(columns, hints):
    for hint in hints:
        if hint in columns:
            return hint
    for col in columns:
        for hint in hints:
            if hint.replace(" ", "") in str(col).replace(" ", ""):
                return col
    return None


def load_file(path):
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return pd.read_excel(path, dtype=str)  # dtype=str: HS코드 앞자리 0 유실 방지


def ensure_table(conn):
    conn.execute("DROP TABLE IF EXISTS hscode_master")
    conn.execute(
        """
        CREATE TABLE hscode_master (
            hscode TEXT PRIMARY KEY,
            name_ko TEXT,
            name_en TEXT
        )
        """
    )


def main():
    parser = argparse.ArgumentParser(description="관세청_HS부호 파일 -> hscode_master 테이블")
    parser.add_argument("--file", required=True, help="data.go.kr에서 내려받은 xlsx/csv 경로")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--hscode-col", help="HS코드 컬럼명 직접 지정 (자동 인식 실패 시)")
    parser.add_argument("--name-ko-col", help="한글 품목명 컬럼명 직접 지정")
    parser.add_argument("--name-en-col", help="영문 품목명 컬럼명 직접 지정")
    parser.add_argument("--list-columns", action="store_true", help="컬럼 목록만 출력하고 종료")
    parser.add_argument("--yes", action="store_true", help="확인 절차 없이 바로 실행")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"오류: 파일을 찾을 수 없습니다: {args.file}")
        sys.exit(1)

    print(f"파일 읽는 중: {args.file}")
    df = load_file(args.file)
    print(f"컬럼 목록: {list(df.columns)}")
    print(f"행 개수: {len(df)}")

    if args.list_columns:
        return

    hscode_col = args.hscode_col or _guess_column(df.columns, HSCODE_COL_HINTS)
    name_ko_col = args.name_ko_col or _guess_column(df.columns, NAME_KO_COL_HINTS)
    name_en_col = args.name_en_col or _guess_column(df.columns, NAME_EN_COL_HINTS)

    missing = [
        label for label, col in [("HS코드", hscode_col), ("한글 품목명", name_ko_col)] if not col
    ]
    if missing:
        print(f"\n오류: 자동으로 못 찾은 컬럼이 있습니다: {missing}")
        print("--hscode-col, --name-ko-col 옵션으로 직접 지정해주세요.")
        print(f"(전체 컬럼 목록: {list(df.columns)})")
        sys.exit(1)

    print("\n[인식된 컬럼]")
    print(f"  HS코드     -> {hscode_col!r}")
    print(f"  한글 품목명 -> {name_ko_col!r}")
    print(f"  영문 품목명 -> {name_en_col!r} {'(없으면 빈 값으로 저장)' if not name_en_col else ''}")

    if not args.yes:
        answer = input("\n이대로 진행할까요? (y/N): ").strip().lower()
        if answer != "y":
            print("취소했습니다.")
            return

    rows = []
    for _, row in df.iterrows():
        hscode = str(row[hscode_col]).strip() if pd.notna(row[hscode_col]) else None
        if not hscode or not hscode.isdigit():
            continue
        name_ko = str(row[name_ko_col]).strip() if pd.notna(row[name_ko_col]) else ""
        name_en = ""
        if name_en_col and pd.notna(row[name_en_col]):
            name_en = str(row[name_en_col]).strip()
        rows.append((hscode, name_ko, name_en))

    if not rows:
        print("오류: 유효한 행을 하나도 못 찾았습니다. 컬럼 지정이 맞는지 확인해주세요.")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    ensure_table(conn)
    conn.executemany(
        "INSERT OR REPLACE INTO hscode_master (hscode, name_ko, name_en) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    print(f"\n완료: {len(rows)}건을 hscode_master 테이블에 저장했습니다 ({args.db}).")


if __name__ == "__main__":
    main()

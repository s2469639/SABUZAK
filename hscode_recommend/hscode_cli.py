#!/usr/bin/env python3
"""hscode_recommend.py 단독 테스트용 CLI.

이 파일은 새 페이지에 HS코드 추천 기능을 끼워넣기 전에, 그 기능이 이
폴더 안에서 독립적으로 잘 동작하는지 확인하는 용도입니다. 실제로 다른
페이지에 넣을 때는 hscode_recommend.py의 recommend_hscodes()만
import해서 쓰면 됩니다 (이 CLI 파일은 참고만 하면 됨).

사전 준비:
    pip install -r requirements.txt
    .env 파일에 OPENAI_API_KEY 설정 (Tavily 키는 이 기능엔 필요 없음)

실행:
    python hscode_cli.py --product 김부각
    python hscode_cli.py --product "이상한 신제품"
"""

import argparse
import sqlite3

from env_setup import ensure_required_keys
from hscode_recommend import get_openai_client, recommend_hscodes
from build_hscode_lookup import DEFAULT_DB_PATH


def main():
    parser = argparse.ArgumentParser(description="제품명 -> HS코드 후보 추천 (독립 기능)")
    parser.add_argument("--product", required=True, help="예: 김부각")
    args = parser.parse_args()

    ensure_required_keys()  # OPENAI_API_KEY만 있으면 됨 (없으면 여기서 물어봄)

    client = get_openai_client()

    # hscode_master(관세청 공식 데이터)가 있으면 검증에 활용. 없어도 동작함.
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        candidates = recommend_hscodes(client, args.product, conn=conn)
    finally:
        conn.close()

    print(f"[{args.product}] HS코드 후보 (AI 추정 - 실제 신고 시 관세사/관세청 사전심사로 재확인 필요)")
    print("=" * 60)
    for c in candidates:
        verified = "✅ 공식 확인" if c.get("verified") else "⚠️ 미확인"
        official = f" ({c['official_name']})" if c.get("official_name") else ""
        print(f"- {c['hscode']} [{c.get('confidence')}] {verified}{official}")
        print(f"    {c.get('reason')}")


if __name__ == "__main__":
    main()

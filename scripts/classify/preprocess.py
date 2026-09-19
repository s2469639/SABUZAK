#!/usr/bin/env python3
"""
raw_exhibitions(SQLite)의 박람회를 OpenAI API로 분류해서 같은 DB에 저장하는 스크립트.

scripts/crawl/sync_to_db.py 로 크롤링/적재를 마친 뒤 이 스크립트를 실행하면:
    - 아직 분류 안 된 박람회 (classified_at이 비어있음)
    - 크롤링으로 내용이 갱신됐는데 분류는 그대로인 박람회 (last_updated_at > classified_at)
  만 골라서 OpenAI에 보내 분류하고, 그 결과를 continent/food_yn/scale/keywords/intro_ko
  컬럼에 저장합니다. 이미 최신으로 분류된 건 다시 부르지 않아 API 비용을 아낍니다.

name/country/city/venue는 원문(영문) 그대로 둡니다 (고유명사라 번역 대상이 아님).
country는 화면에 보여줄 때만 app/services/country_names.py의 정적 매핑으로 한글
표시(매핑에 없으면 원문 그대로). intro(상세설명)만 이 스크립트가 분류와 같은 호출로
한국어로 번역해서 intro_ko에 저장합니다.

사전 준비:
    pip install openai python-dotenv
    .env 파일에 다음을 넣어두세요:
        OPENAI_API_KEY=your_key   (또는 LLM_API_KEY)

실행:
    python preprocess.py                          # 기본 DB(../../instance/sabuzak.db), 미분류/재분류 필요분만
    python preprocess.py --db ../../instance/sabuzak.db
    python preprocess.py --limit 5                # 연습/테스트용으로 5건만
    python preprocess.py --force                  # 이미 분류된 것도 전부 재분류
    python preprocess.py --model gpt-4o-mini       # 모델 지정(기본값은 gpt-4o)
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "instance", "sabuzak.db"
)
DEFAULT_MODEL = "gpt-4o"


def get_client():
    load_dotenv()
    # OPENAI_API_KEY 또는 LLM_API_KEY 지원
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        print("오류: OPENAI_API_KEY가 설정되어 있지 않습니다 (.env 파일 확인).")
        sys.exit(1)
    return OpenAI(api_key=api_key)


def fetch_targets(conn, force: bool, limit: int):
    cur = conn.cursor()
    if force:
        query = """
            SELECT id, name, country, website, audience_note, intro
            FROM raw_exhibitions
            WHERE is_active = 1
            ORDER BY id
        """
        cur.execute(query)
    else:
        query = """
            SELECT id, name, country, website, audience_note, intro
            FROM raw_exhibitions
            WHERE is_active = 1
              AND (classified_at IS NULL OR last_updated_at > classified_at)
            ORDER BY id
        """
        cur.execute(query)

    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def build_prompt(name, country, website, audience_note, intro):
    return f"""
    당신은 글로벌 박람회 데이터 분석 전문가입니다. 아래 박람회 정보를 바탕으로 5가지 항목을 정확히 처리해주세요.

    [박람회 정보]
    - 박람회명(name): {name}
    - 국가(country): {country}
    - 웹사이트(website): {website}
    - 참관대상 원문(audience note): {audience_note or '(정보 없음)'}
    - 소개(intro): {intro}

    [처리 조건]
    1) 대륙: 해당 국가가 속한 대륙 (예: 아시아, 유럽, 북미, 남미, 아프리카, 오세아니아 등)
    2) food_yn: 식품류 전시회 여부 (True 또는 False)
       - TRUE: 가공식품, 과자/스낵, 베이커리, 디저트, 음료, 주류, 유기농/비건, HORECA 식자재 등 사람이 섭취하는 완제품 및 식음료 원료 전시회
       - FALSE: 식품 가공기계, 포장 장비, 냉동·냉장 설비, 가구, 가전, 패션, 리빙, 농업 생산 설비 등
    3) 규모: '대', '중', '소', '미상' 중 택 1
       - 대: 참가기업 1,000개 사 이상 또는 방문객 30,000명 이상
       - 중: 참가기업 300 ~ 999개 사, 방문객 10,000 ~ 29,999명
       - 소: 참가기업 300개 사 미만, 방문객 10,000명 미만
       - 미상: 통계 미공개 또는 신생 행사
    4) 키워드: 아래 표준 키워드 풀에서 가장 적절한 단어 정확히 5개를 골라 쉼표(,)로 구분하여 작성
       [표준 키워드 풀]
       - 산업/품목군: 식품/음료종합, 제과/베이커리, 가공식품, 건강/기능성, 주류/음료, 수산/해양식품, 축산/육가공, 식자재, 식품원료/소재
       - 라이프/트렌드: 웰니스/비건, 친환경/유기농, 호스피탈리티, 외식/HORECA, 프리미엄미식, 지역특산물
       - 비식품/설비: 식품가공/설비, 포장기술, 식품테크, 소비재종합, 라이프스타일, 가든/인테리어, 농업/스마트팜
    5) intro_ko: 위 소개(intro)를 자연스러운 한국어로 번역. 박람회명·지명·기관명 등 고유명사는
       번역하지 말고 원문 그대로 표기 (예: "Summer Fancy Food Show"는 그대로 유지)

    반드시 아래 JSON 형식으로만 응답해주세요:
    {{
      "대륙": "...",
      "food_yn": true,
      "규모": "...",
      "키워드": "키워드1, 키워드2, 키워드3, 키워드4, 키워드5",
      "intro_ko": "..."
    }}
    """


def classify_row(client, model, row):
    _, name, country, website, audience_note, intro = row
    prompt = build_prompt(name, country, website, audience_note, intro)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def save_classification(conn, exhibition_id, result, ts):
    conn.execute(
        """
        UPDATE raw_exhibitions
        SET continent=?, food_yn=?, scale=?, keywords=?, intro_ko=?, classified_at=?
        WHERE id=?
        """,
        (
            result.get("대륙", "미상"),
            1 if result.get("food_yn") else 0,
            result.get("규모", "미상"),
            result.get("키워드", ""),
            result.get("intro_ko", ""),
            ts,
            exhibition_id,
        ),
    )
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="OpenAI로 박람회 분류 -> raw_exhibitions에 저장")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--force", action="store_true", help="이미 분류된 것도 전부 재분류")
    parser.add_argument("--limit", type=int, default=0, help="테스트용: 최대 N건만 처리 (0=전체)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {args.db}")

    client = get_client()
    conn = sqlite3.connect(args.db)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(raw_exhibitions)")}
    if not {"classified_at", "intro_ko"} <= cols:
        raise RuntimeError(
            "이 DB는 classified_at/intro_ko 컬럼이 없는 예전 스키마입니다. 먼저 "
            "`python ../crawl/sync_to_db.py --db <이 DB 경로>`를 한 번 실행해서 "
            "새 스키마로 마이그레이션한 뒤 다시 시도해주세요."
        )

    targets = fetch_targets(conn, args.force, args.limit)
    if not targets:
        print("분류할 신규/변경 항목이 없습니다. (모두 최신 상태)")
        conn.close()
        return

    print(f"분류 대상: {len(targets)}건")
    success = 0
    failed = 0
    for i, row in enumerate(targets, 1):
        exhibition_id, name = row[0], row[1]
        print(f"[{i}/{len(targets)}] {name}")
        try:
            result = classify_row(client, args.model, row)
            ts = datetime.now(timezone.utc).isoformat()
            save_classification(conn, exhibition_id, result, ts)
            print(
                f"  -> {result.get('대륙')} / food_yn={result.get('food_yn')} / "
                f"{result.get('규모')} / {result.get('키워드')}"
            )
            success += 1
        except Exception as e:
            print(f"  -> 실패: {e}")
            failed += 1
        time.sleep(0.3)  # API rate limit 여유

    conn.close()
    print(f"\n완료: 성공 {success}건, 실패 {failed}건")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""raw_exhibitions에서 audience_type(B2B/B2C)이 비어있는 박람회를 채우는 스크립트.

audience_type 컬럼은 지금까지 아무 스크립트도 채운 적이 없어서 전부 비어있다
(원문 참관대상 텍스트는 audience_note에 크롤링 시점에 이미 들어있음 -
tradefairdates_scraper.py의 "참관대상" 필드). 이 스크립트는 그 audience_note
원문으로 B2B/B2C를 정하고, 최대한 API 호출 없이(=토큰 절약) 처리한다.

기준 (우선순위대로):
    1) audience_note 원문에 trade/professional/industry 계열 키워드만 있으면
       "B2B", public/consumer/general 계열 키워드만 있으면 "B2C", 두 계열이
       다 있으면(예: "trade visitors + public weekend") "B2B/B2C" - API 호출
       없이 텍스트 매칭만으로 정한다 (대부분 이 단계에서 끝남).
    2) audience_note가 비어있거나 애매해서 키워드로 못 정하면, 박람회명·
       국가·소개(intro)로 AI(gpt-4o-mini)에게 물어본다. 이때도 기본값은
       "B2B"로 둔다 - 이 DB의 박람회 대부분이 식품 전문 무역박람회라
       B2B 비중이 원래 높고, 명확히 일반 소비자 대상이라는 근거가 없으면
       B2B로 보는 게 실제 오분류가 적다.
    3) 그래도 AI가 못 정하면(이름도 낯설고 정보가 전혀 없음) "B2B"를
       최종 기본값으로 저장한다 - "미상"으로 두지 않는다 (사용자 요청:
       비어있는 건 다 채워달라).

실행:
    python fill_audience_type.py                 # 기본 DB, 비어있는 전체
    python fill_audience_type.py --limit 20       # 테스트용 20건만
    python fill_audience_type.py --dry-run        # 저장하지 않고 결과만 출력
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from dotenv import load_dotenv

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "instance", "sabuzak.db"
)
DEFAULT_MODEL = "gpt-4o-mini"
MAX_TEXT_CHARS = 400  # 판단에는 앞부분이면 충분 (토큰 절약)

# audience_note 원문 키워드 (tradefairdates.com은 영문 기준으로 적어둠)
B2B_PATTERNS = re.compile(
    r"\b(trade|professional|industry|business|b2b)\b.*\b(visitor|only|exclusive)\b"
    r"|\b(trade\s+visitors?\s+only|professionals?\s+only|industry\s+only)\b",
    re.I,
)
B2C_PATTERNS = re.compile(
    r"\b(public|consumer|general\s+public|open\s+to\s+the\s+public|b2c)\b",
    re.I,
)


def keyword_guess(audience_note):
    """audience_note 원문 텍스트만으로 판단 (API 호출 없음). 못 정하면 None."""
    text = (audience_note or "").strip()
    if not text:
        return None
    is_b2b = bool(B2B_PATTERNS.search(text))
    is_b2c = bool(B2C_PATTERNS.search(text))
    if is_b2b and is_b2c:
        return "B2B/B2C"
    if is_b2b:
        return "B2B"
    if is_b2c:
        return "B2C"
    return None


def get_client():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        print("오류: OPENAI_API_KEY가 설정되어 있지 않습니다 (.env 파일 확인).")
        sys.exit(1)
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def fetch_targets(conn, limit: int):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, country, audience_note, intro
        FROM raw_exhibitions
        WHERE is_active = 1 AND (audience_type IS NULL OR audience_type = '')
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def _trim(text, n=MAX_TEXT_CHARS):
    return (text or "").strip()[:n]


def build_prompt(name, country, audience_note, intro):
    return f"""박람회 하나의 참관 대상이 B2B(업계 관계자 전용 무역박람회)인지
B2C(일반 소비자도 입장 가능)인지, 아니면 둘 다(B2B/B2C, 예: 평일은 업계
전용이고 주말은 일반 공개)인지 판단해주세요.

[정보]
- 박람회명: {name}
- 국가: {country}
- 참관대상 원문: {_trim(audience_note, 200) or '(정보 없음)'}
- 소개: {_trim(intro)}

[기본 원칙]
- 식품/농산물 관련 국제 무역박람회는 대부분 바이어·유통업체·요식업 관계자
  대상의 B2B 행사입니다. 명확히 일반 소비자 대상(입장권 판매, 시식/체험
  행사, "공개 행사" 등)이라는 근거가 없으면 기본적으로 "B2B"로 판단하세요.
- 정보가 부족해서 확신이 안 서도 "B2B"를 답하세요 (이 판단은 절대
  "모름"으로 남겨두지 마세요).

반드시 아래 JSON 형식으로만, 다른 설명 없이 응답하세요:
{{"참관대상": "B2B" | "B2C" | "B2B/B2C"}}
"""


def ai_guess(client, model, name, country, audience_note, intro):
    prompt = build_prompt(name, country, audience_note, intro)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(response.choices[0].message.content)
    value = str(data.get("참관대상", "")).strip()
    return value if value in ("B2B", "B2C", "B2B/B2C") else "B2B"


def save_audience_type(conn, exhibition_id, value):
    conn.execute("UPDATE raw_exhibitions SET audience_type=? WHERE id=?", (value, exhibition_id))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="audience_type(B2B/B2C)이 비어있는 박람회를 채움")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0, help="테스트용: 최대 N건만 처리 (0=전체)")
    parser.add_argument("--dry-run", action="store_true", help="DB에 저장하지 않고 결과만 출력")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {args.db}")

    conn = sqlite3.connect(args.db)
    targets = fetch_targets(conn, args.limit)
    if not targets:
        print("audience_type이 비어있는 박람회가 없습니다.")
        conn.close()
        return

    print(f"대상: {len(targets)}건")

    client = None
    counts = {"B2B": 0, "B2C": 0, "B2B/B2C": 0}
    from_keyword = 0
    from_ai = 0
    failed = 0

    for i, (exhibition_id, name, country, audience_note, intro) in enumerate(targets, 1):
        value = keyword_guess(audience_note)
        source = "키워드"
        if value:
            from_keyword += 1
        else:
            if client is None:
                client = get_client()
            try:
                value = ai_guess(client, args.model, name, country, audience_note, intro)
                from_ai += 1
                source = "AI"
                time.sleep(0.2)
            except Exception as e:
                print(f"[{i}/{len(targets)}] {name} -> 실패: {e}")
                failed += 1
                continue

        counts[value] += 1
        print(f"[{i}/{len(targets)}] {name} -> {value} ({source})")
        if not args.dry_run:
            save_audience_type(conn, exhibition_id, value)

    conn.close()
    print(
        f"\n완료: B2B {counts['B2B']} · B2C {counts['B2C']} · B2B/B2C {counts['B2B/B2C']} · "
        f"실패 {failed} (키워드로 {from_keyword}건, AI 호출 {from_ai}건)"
    )
    if args.dry_run:
        print("(--dry-run: DB에는 저장하지 않았습니다)")


if __name__ == "__main__":
    main()

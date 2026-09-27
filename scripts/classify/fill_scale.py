#!/usr/bin/env python3
"""raw_exhibitions에서 scale(규모)이 '미상'인 박람회만 골라 채우는 스크립트.

preprocess.py는 continent/food_yn/scale/keywords/intro_ko 5가지를 한 번에
분류하는데, scale만 다시 채우자고 5개를 통째로 재호출하면 이미 맞게 분류된
나머지 4개까지 토큰을 또 쓰게 된다. 이 스크립트는 "규모" 하나만 다시 묻는
훨씬 짧은 프롬프트로, scale='미상'인 행만 골라서 그 컬럼 하나만 갱신한다
(토큰 절약 + API 비용 절약이 핵심 목적).

기준:
    1) 웹사이트/intro/audience_note 원문에 참가기업 수·방문객 수·"유럽 최대"
       같은 규모 관련 문구가 있으면 그걸 근거로 판단한다.
    2) 그런 문구가 전혀 없으면, 박람회명·국가·주최 형태 같은 간접 정보로
       최선의 추정을 한다 — "추정"이라는 딱지는 화면에도 DB에도 남기지 않고,
       그냥 최종 값(대/중/소)만 저장한다.
    3) 그래도 정말 아무 단서가 없으면(이름도 생소하고 설명도 없는 경우)
       그때만 '미상'을 유지한다 - 근거 없이 찍는 것보다는 낫다고 판단.

토큰 절약을 위한 장치:
    - 기본 모델을 gpt-4o-mini로 함 (gpt-4o preprocess.py 대비 훨씬 저렴)
    - intro/audience_note를 각각 MAX_INTRO_CHARS자로 잘라서 보냄
      (규모 판단에는 도입부 몇 문장이면 충분하고, 뒷부분 장문 소개까지
      다 보낼 필요가 없음)
    - scale 컬럼 하나만 SELECT/UPDATE (continent 등 이미 있는 값은 건드리지
      않음 -> 재분류 대상이 아니라서 classified_at도 그대로 둔다)

실행:
    python fill_scale.py                       # 기본 DB, 미상 전체
    python fill_scale.py --limit 20             # 테스트용 20건만
    python fill_scale.py --model gpt-4o-mini
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from dotenv import load_dotenv
from openai import OpenAI

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "instance", "sabuzak.db"
)
DEFAULT_MODEL = "gpt-4o-mini"
MAX_INTRO_CHARS = 500  # 규모 판단용이라 앞부분만으로 충분 (토큰 절약)


def get_client():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        print("오류: OPENAI_API_KEY가 설정되어 있지 않습니다 (.env 파일 확인).")
        sys.exit(1)
    return OpenAI(api_key=api_key)


def fetch_targets(conn, limit: int):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, country, website, audience_note, intro
        FROM raw_exhibitions
        WHERE is_active = 1 AND (scale = '미상' OR scale IS NULL OR scale = '')
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def _trim(text, n=MAX_INTRO_CHARS):
    text = (text or "").strip()
    return text[:n]


def build_prompt(name, country, website, audience_note, intro):
    return f"""박람회 하나의 "규모"를 반드시 대/중/소 중 하나로 답해주세요.
"미상"은 사실상 쓰지 않는다고 생각하세요 — 아래 [정보]에 이름과 국가는
항상 있으니, 그것만으로도 3번 기준(간접 추정)을 적용해 대/중/소 중 하나를
고를 수 있습니다.

[판단 순서 - 1번부터 확인해서 처음 해당하는 걸 근거로 쓰세요]
1) 참가기업 수·방문객 수 같은 숫자가 [정보]에 있으면 [규모 기준]의 숫자와
   비교해서 그대로 판정
2) 숫자는 없지만 "세계 최대/최고", "유럽 1위", "아시아 최대" 같은 규모를
   뒷받침하는 표현이 있으면 "대"로 판정
3) 위 둘 다 없으면 아래 간접 신호로 추정 (이게 대부분의 경우입니다):
   - 박람회명에 "World", "International", "Global", "Expo"(대형 종합
     박람회 느낌)가 들어있고 참가자가 여러 나라라면 최소 "중" 이상으로
   - 박람회명이 특정 품목 하나(예: 빵, 커피, 초콜릿 하나만)에 집중된
     전문 소형 전시회 느낌이면 "소"
   - 독일·프랑스·이탈리아·미국·중국·영국처럼 박람회 산업이 발달한
     주요국에서 열리는 업력이 오래된 느낌의 행사면 최소 "중"
   - 그 외 애매하면 "소"를 기본값으로 선택 (대부분의 지역/신생 박람회가
     실제로 소규모이므로, 확신 없을 때는 과장하지 않는 쪽이 안전합니다)
4) "미상"은 박람회명조차 의미를 알 수 없는 코드성 문자열이고 국가·설명이
   전부 비어있어 정말 아무 것도 판단할 수 없을 때만 쓰세요.

[정보]
- 박람회명: {name}
- 국가: {country}
- 웹사이트: {website}
- 참관대상: {_trim(audience_note, 200) or '(정보 없음)'}
- 소개: {_trim(intro) or '(정보 없음)'}

[규모 기준]
- 대: 참가기업 1,000개 사 이상 또는 방문객 30,000명 이상
- 중: 참가기업 300~999개 사, 방문객 10,000~29,999명
- 소: 참가기업 300개 사 미만, 방문객 10,000명 미만

반드시 아래 JSON 형식으로만, 다른 설명 없이 응답하세요:
{{"규모": "대" | "중" | "소" | "미상"}}
"""


def classify_scale(client, model, row):
    _, name, country, website, audience_note, intro = row
    prompt = build_prompt(name, country, website, audience_note, intro)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(response.choices[0].message.content)
    scale = str(data.get("규모", "")).strip()
    return scale if scale in ("대", "중", "소", "미상") else "미상"


def save_scale(conn, exhibition_id, scale):
    conn.execute("UPDATE raw_exhibitions SET scale=? WHERE id=?", (scale, exhibition_id))
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="규모(scale)가 '미상'인 박람회만 골라 AI로 채움")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0, help="테스트용: 최대 N건만 처리 (0=전체)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {args.db}")

    client = get_client()
    conn = sqlite3.connect(args.db)

    targets = fetch_targets(conn, args.limit)
    if not targets:
        print("규모가 '미상'인 박람회가 없습니다.")
        conn.close()
        return

    print(f"대상: {len(targets)}건 (모델: {args.model})")
    counts = {"대": 0, "중": 0, "소": 0, "미상": 0}
    failed = 0
    for i, row in enumerate(targets, 1):
        exhibition_id, name = row[0], row[1]
        try:
            scale = classify_scale(client, args.model, row)
            save_scale(conn, exhibition_id, scale)
            counts[scale] += 1
            print(f"[{i}/{len(targets)}] {name} -> {scale}")
        except Exception as e:
            print(f"[{i}/{len(targets)}] {name} -> 실패: {e}")
            failed += 1
        time.sleep(0.2)

    conn.close()
    print(
        f"\n완료: 대 {counts['대']} · 중 {counts['중']} · 소 {counts['소']} · "
        f"여전히 미상 {counts['미상']} · 실패 {failed}"
    )


if __name__ == "__main__":
    main()

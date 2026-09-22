#!/usr/bin/env python3
"""
sabuzak.db(raw_exhibitions) 내용을 브라우저에서 확인만 하는 초간단 미리보기 대시보드.

- 로그인/DB모델/템플릿 구조 없이 파일 하나로 바로 실행됩니다.
- 나중에 팀원들이 만들 본격 Flask 앱(app/ 구조)과는 완전히 독립적이라
  이 파일을 지워도 본 프로젝트에 아무 영향 없습니다. "데이터 잘 들어갔나" 확인용.
- OpenAI 분류 결과(대륙/식품여부/규모/키워드/한글소개)와 연락처(이메일/전화)까지
  전부 표시합니다. DB에 아직 없는 컬럼(예전 스키마)은 그냥 빈 칸으로 나옵니다.

사전 준비:
    pip install flask

실행:
    python preview_dashboard.py --db ../../instance/sabuzak.db
    (콘솔에 뜨는 http://127.0.0.1:5050 주소를 브라우저로 열기)
"""

import argparse
import os
import re
import sqlite3

from flask import Flask, render_template_string, request

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabuzak.db")
UNKNOWN_DATE = 99999999

app = Flask(__name__)
app.config["DB_PATH"] = DEFAULT_DB_PATH

PAGE_TEMPLATE = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>사부작 - 박람회 데이터 미리보기</title>
<style>
  body { font-family: -apple-system, "Malgun Gothic", sans-serif; margin: 24px; background: #f7f7f8; color: #222; }
  h1 { font-size: 20px; }
  .summary { color: #555; margin-bottom: 16px; }
  .filters { margin-bottom: 16px; }
  .filters a { margin-right: 8px; padding: 4px 10px; border-radius: 12px; background: #eee; text-decoration: none; color: #333; font-size: 13px; }
  .filters a.active { background: #333; color: #fff; }
  table { border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  th, td { padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 13px; text-align: left; vertical-align: top; white-space: nowrap; }
  th { background: #fafafa; position: sticky; top: 0; }
  tbody tr { cursor: pointer; }
  tr:hover { background: #eef4ff; }
  .inactive { opacity: 0.45; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #eef; color: #338; white-space: nowrap; }
  .badge-food { background: #efe; color: #383; }
  .badge-nonfood { background: #f5f5f5; color: #888; }
  .keywords { max-width: 220px; white-space: normal; }
  .keywords .badge { margin: 1px 2px 1px 0; }
  a.site { color: #2563eb; text-decoration: none; }
  table-wrap { overflow-x: auto; }
  .stats { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
  .stat-card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); padding: 10px 16px; min-width: 110px; }
  .stat-card .num { font-size: 20px; font-weight: 700; }
  .stat-card .num.low { color: #c33; }
  .stat-card .label { font-size: 12px; color: #888; margin-top: 2px; }
  .hint { font-size: 12px; color: #999; margin-bottom: 12px; }
</style>
</head>
<body>
  <h1>사부작 박람회 데이터 미리보기 (개발용)</h1>
  <div class="summary">
    총 {{ total }}건 (활성 {{ active }} / 비활성 {{ total - active }})
  </div>

  <div class="stats">
    {% for label, count in field_stats %}
    <div class="stat-card">
      <div class="num {{ 'low' if total and count < total * 0.5 else '' }}">{{ count }} / {{ total }}</div>
      <div class="label">{{ label }}</div>
    </div>
    {% endfor %}
  </div>

  <div class="filters">
    <a href="?category=" class="{{ 'active' if not selected_category else '' }}">전체</a>
    {% for cat in categories %}
      <a href="?category={{ cat }}" class="{{ 'active' if selected_category == cat else '' }}">{{ cat }}</a>
    {% endfor %}
  </div>
  <div class="hint">행을 클릭하면 소개/연락처 등 상세정보를 볼 수 있습니다.</div>
  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>#</th><th>전시회명</th><th>기간</th><th>국가</th><th>도시</th>
        <th>대륙</th><th>식품</th><th>규모</th><th>키워드</th>
        <th>카테고리</th><th>상태</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr class="{{ '' if r.is_active else 'inactive' }}" onclick="location.href='/exhibition/{{ r.id }}'">
        <td>{{ r.id }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.period_display }}</td>
        <td>{{ r.country_ko or r.country }}</td>
        <td>{{ r.city }}</td>
        <td>{{ r.continent or '' }}</td>
        <td>
          {% if r.food_yn == 1 %}<span class="badge badge-food">식품</span>
          {% elif r.food_yn == 0 %}<span class="badge badge-nonfood">비식품</span>
          {% endif %}
        </td>
        <td>{{ r.scale or '' }}</td>
        <td class="keywords">
          {% for kw in (r.keywords or '').split(',') if kw.strip() %}<span class="badge">{{ kw.strip() }}</span>{% endfor %}
        </td>
        <td><span class="badge">{{ r.category }}</span></td>
        <td>{{ '활성' if r.is_active else '비활성' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  </div>
</body>
</html>
"""


DETAIL_TEMPLATE = """
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{{ r.name }} - 상세정보</title>
<style>
  body { font-family: -apple-system, "Malgun Gothic", sans-serif; margin: 24px; background: #f7f7f8; color: #222; max-width: 720px; }
  a.back { color: #2563eb; text-decoration: none; font-size: 13px; }
  h1 { font-size: 22px; margin: 12px 0 4px; }
  .sub { color: #888; margin-bottom: 20px; }
  .card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 20px; margin-bottom: 16px; }
  .row { display: flex; padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
  .row:last-child { border-bottom: none; }
  .label { width: 120px; flex-shrink: 0; color: #888; font-size: 13px; }
  .value { flex: 1; font-size: 14px; word-break: break-word; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #eef; color: #338; margin-right: 4px; }
  .badge-food { background: #efe; color: #383; }
  a.site { color: #2563eb; }
  .prose { line-height: 1.7; }
  .prose p { margin: 0 0 10px; }
  .prose p:last-child { margin-bottom: 0; }
  .card h3 { font-size: 13px; color: #888; margin: 0 0 8px; font-weight: 600; }
</style>
</head>
<body>
  <a class="back" href="/{{ '?category=' + category if category else '' }}">&larr; 목록으로</a>
  <h1>{{ r.name }}</h1>
  <div class="sub">#{{ r.id }} · {{ '활성' if r.is_active else '비활성' }} · {{ r.category }}</div>

  <div class="card">
    <div class="row"><div class="label">기간</div><div class="value">{{ r.period_display }}</div></div>
    <div class="row"><div class="label">개최국</div><div class="value">{{ r.country_ko or r.country }}{% if r.country_ko %} ({{ r.country }}){% endif %}</div></div>
    <div class="row"><div class="label">도시</div><div class="value">{{ r.city }}</div></div>
    <div class="row"><div class="label">베뉴</div><div class="value">{{ r.venue }}</div></div>
    <div class="row"><div class="label">참관대상</div><div class="value">{{ r.audience_note or '' }}</div></div>
  </div>

  <div class="card">
    <div class="row"><div class="label">대륙</div><div class="value">{{ r.continent or '(미분류)' }}</div></div>
    <div class="row"><div class="label">식품여부</div><div class="value">
      {% if r.food_yn == 1 %}<span class="badge badge-food">식품</span>
      {% elif r.food_yn == 0 %}<span class="badge">비식품</span>
      {% else %}(미분류){% endif %}
    </div></div>
    <div class="row"><div class="label">규모</div><div class="value">{{ r.scale or '(미분류)' }}</div></div>
    <div class="row"><div class="label">키워드</div><div class="value">
      {% for kw in (r.keywords or '').split(',') if kw.strip() %}<span class="badge">{{ kw.strip() }}</span>{% endfor %}
    </div></div>
  </div>

  <div class="card">
    <div class="row"><div class="label">웹사이트</div><div class="value">
      {% if r.website %}<a class="site" href="https://{{ r.website }}" target="_blank">{{ r.website }}</a>{% else %}(없음){% endif %}
    </div></div>
    <div class="row"><div class="label">이메일</div><div class="value">{{ r.organizer_email or '(못찾음)' }}</div></div>
    <div class="row"><div class="label">전화</div><div class="value">{{ r.organizer_phone or '(못찾음)' }}</div></div>
  </div>

  <div class="card">
    <h3>소개 (한글)</h3>
    {% if r.intro_ko_paragraphs %}
      <div class="prose">{% for p in r.intro_ko_paragraphs %}<p>{{ p }}</p>{% endfor %}</div>
    {% else %}
      <div class="prose" style="color:#aaa">(번역 안 됨)</div>
    {% endif %}
  </div>

  <div class="card">
    <h3>소개 (원문)</h3>
    {% if r.intro_paragraphs %}
      <div class="prose">{% for p in r.intro_paragraphs %}<p>{{ p }}</p>{% endfor %}</div>
    {% else %}
      <div class="prose" style="color:#aaa">(없음)</div>
    {% endif %}
  </div>

  <div class="card">
    <div class="row"><div class="label">상세페이지</div><div class="value"><a class="site" href="{{ r.detail_url }}" target="_blank">{{ r.detail_url }}</a></div></div>
    <div class="row"><div class="label">분류 시각</div><div class="value">{{ r.classified_at or '' }}</div></div>
    <div class="row"><div class="label">최근 갱신</div><div class="value">{{ r.last_updated_at or '' }}</div></div>
  </div>
</body>
</html>
"""


def format_period(start_date, end_date):
    """YYYYMMDD 정수(또는 None) -> 사람이 읽는 기간 문자열."""

    def fmt_one(d):
        if d is None or d == UNKNOWN_DATE:
            return None
        d = int(d)
        year, month, day = d // 10000, (d // 100) % 100, d % 100
        if day == 32:  # 일자 미상 sentinel (tradefairdates_scraper.py 참고)
            return f"{year:04d}-{month:02d}"
        return f"{year:04d}-{month:02d}-{day:02d}"

    start_str = fmt_one(start_date)
    end_str = fmt_one(end_date)

    if not start_str and not end_str:
        return "날짜 미정"
    if start_str == end_str or not end_str:
        return start_str or "날짜 미정"
    return f"{start_str} ~ {end_str}"


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?다요음함])\s+(?=[A-Z가-힣\"'(])")


def paragraphize(text: str, sentences_per_paragraph: int = 2):
    """길게 이어진 소개 텍스트를 문장 단위로 끊어서 몇 문장씩 문단으로 묶는다.
    (크롤링/번역 결과가 줄바꿈 없이 한 덩어리 문자열이라 그대로 보여주면 읽기 힘듦)"""
    text = (text or "").strip()
    if not text:
        return []

    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if not sentences:
        return [text]

    paragraphs = []
    for i in range(0, len(sentences), sentences_per_paragraph):
        paragraphs.append(" ".join(sentences[i : i + sentences_per_paragraph]))
    return paragraphs


def get_conn():
    return sqlite3.connect(app.config["DB_PATH"])


def available_columns(cur):
    cur.execute("PRAGMA table_info(raw_exhibitions)")
    return {row[1] for row in cur.fetchall()}


def row_to_dict(row):
    d = dict(row)
    if "start_date" in d or "end_date" in d:
        d["period_display"] = format_period(d.get("start_date"), d.get("end_date"))
    else:
        # 아주 예전 스키마(period 하나로만 있던 시절) 호환
        d["period_display"] = d.get("period", "")
    return d


@app.route("/")
def index():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cols = available_columns(cur)

    cur.execute("SELECT COUNT(*) FROM raw_exhibitions")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM raw_exhibitions WHERE is_active = 1")
    active = cur.fetchone()[0]

    # 컬럼별 분류/보강 현황 (상단 통계 카드용). DB에 아직 없는 컬럼은 자동으로 건너뜀.
    field_stat_defs = [
        ("대륙", "continent"),
        ("식품여부", "food_yn"),
        ("규모", "scale"),
        ("키워드", "keywords"),
        ("한글소개", "intro_ko"),
        ("한글국가명", "country_ko"),
        ("이메일", "organizer_email"),
        ("전화", "organizer_phone"),
    ]
    field_stats = []
    for label, col in field_stat_defs:
        if col not in cols:
            continue
        if col == "food_yn":
            cur.execute("SELECT COUNT(*) FROM raw_exhibitions WHERE food_yn IS NOT NULL")
        else:
            cur.execute(
                f"SELECT COUNT(*) FROM raw_exhibitions WHERE {col} IS NOT NULL AND {col} != ''"
            )
        field_stats.append((label, cur.fetchone()[0]))

    cur.execute("SELECT DISTINCT category FROM raw_exhibitions ORDER BY category")
    categories = [r[0] for r in cur.fetchall()]

    selected_category = request.args.get("category", "").strip()
    if selected_category:
        cur.execute(
            "SELECT * FROM raw_exhibitions WHERE category = ? ORDER BY id DESC",
            (selected_category,),
        )
    else:
        cur.execute("SELECT * FROM raw_exhibitions ORDER BY id DESC")
    raw_rows = cur.fetchall()
    conn.close()

    rows = [row_to_dict(r) for r in raw_rows]

    return render_template_string(
        PAGE_TEMPLATE,
        rows=rows,
        total=total,
        active=active,
        field_stats=field_stats,
        categories=categories,
        selected_category=selected_category,
    )


@app.route("/exhibition/<int:exhibition_id>")
def detail(exhibition_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM raw_exhibitions WHERE id = ?", (exhibition_id,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return f"id={exhibition_id} 인 박람회를 찾을 수 없습니다.", 404

    r = row_to_dict(row)
    r["intro_paragraphs"] = paragraphize(r.get("intro"))
    r["intro_ko_paragraphs"] = paragraphize(r.get("intro_ko"))
    return render_template_string(
        DETAIL_TEMPLATE, r=r, category=request.args.get("category", "")
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"경고: DB 파일이 없습니다: {args.db}")
        print("먼저 python sync_to_db.py 를 실행해서 데이터를 채워주세요.")

    app.config["DB_PATH"] = args.db
    print(f"http://127.0.0.1:{args.port} 에서 확인하세요")
    app.run(debug=True, port=args.port)


if __name__ == "__main__":
    main()

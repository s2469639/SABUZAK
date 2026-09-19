#!/usr/bin/env python3
"""
sabuzak.db(raw_exhibitions) 내용을 브라우저에서 확인만 하는 초간단 미리보기 대시보드.

- 로그인/DB모델/템플릿 구조 없이 파일 하나로 바로 실행됩니다.
- 나중에 팀원들이 만들 본격 Flask 앱(app/ 구조)과는 완전히 독립적이라
  이 파일을 지워도 본 프로젝트에 아무 영향 없습니다. "데이터 잘 들어갔나,
  분류가 제대로 됐나" 확인용.
- pandas로 전체 테이블을 읽어 요약 통계(대륙별/규모별/식품여부별 건수,
  분류 완료 비율)까지 보여줍니다.

사전 준비:
    pip install flask pandas

실행:
    python preview_dashboard.py
    (콘솔에 뜨는 http://127.0.0.1:5050 주소를 브라우저로 열기)

옵션:
    python preview_dashboard.py --db ../../instance/sabuzak.db --port 5050
"""

import argparse
import os
import sqlite3

import pandas as pd
from flask import Flask, render_template_string, request

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "instance", "sabuzak.db"
)

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
  h2 { font-size: 15px; margin: 24px 0 8px; }
  .summary { color: #555; margin-bottom: 16px; }
  .stat-grid { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
  .stat-card { background: #fff; border-radius: 8px; padding: 10px 14px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); min-width: 150px; }
  .stat-card .label { font-size: 11px; color: #888; margin-bottom: 4px; }
  .stat-card .rows span { display: block; font-size: 12px; }
  .stat-card .rows span b { display: inline-block; min-width: 26px; text-align: right; margin-right: 6px; color: #2563eb; }
  .filters { margin-bottom: 16px; }
  .filters a { margin-right: 8px; padding: 4px 10px; border-radius: 12px; background: #eee; text-decoration: none; color: #333; font-size: 13px; }
  .filters a.active { background: #333; color: #fff; }
  table { border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  th, td { padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 13px; text-align: left; vertical-align: top; }
  th { background: #fafafa; position: sticky; top: 0; }
  tr:hover { background: #fbfbfb; }
  .inactive { opacity: 0.45; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #eef; color: #338; }
  .badge.yes { background: #e7f7ec; color: #1a7a3c; }
  .badge.no { background: #fdecec; color: #a33; }
  .badge.unclassified { background: #f2f2f2; color: #888; }
  .intro { max-width: 320px; color: #555; }
  a.site { color: #2563eb; text-decoration: none; }
</style>
</head>
<body>
  <h1>사부작 박람회 데이터 미리보기 (개발용)</h1>
  <div class="summary">
    총 {{ total }}건 (활성 {{ active }} / 비활성 {{ total - active }}) ·
    분류 완료 {{ classified }}건 / 미분류 {{ total - classified }}건
  </div>

  <h2>컬럼별 분류 현황 (pandas 집계)</h2>
  <div class="stat-grid">
    <div class="stat-card">
      <div class="label">대륙 (continent)</div>
      <div class="rows">
        {% for label, count in continent_counts %}
          <span><b>{{ count }}</b>{{ label }}</span>
        {% endfor %}
      </div>
    </div>
    <div class="stat-card">
      <div class="label">규모 (scale)</div>
      <div class="rows">
        {% for label, count in scale_counts %}
          <span><b>{{ count }}</b>{{ label }}</span>
        {% endfor %}
      </div>
    </div>
    <div class="stat-card">
      <div class="label">식품 전시회 여부 (food_yn)</div>
      <div class="rows">
        {% for label, count in food_yn_counts %}
          <span><b>{{ count }}</b>{{ label }}</span>
        {% endfor %}
      </div>
    </div>
    <div class="stat-card">
      <div class="label">카테고리 (category, 크롤링 출처)</div>
      <div class="rows">
        {% for label, count in category_counts %}
          <span><b>{{ count }}</b>{{ label }}</span>
        {% endfor %}
      </div>
    </div>
    <div class="stat-card">
      <div class="label">거래유형 (audience_type, 규칙 기반·AI 미사용)</div>
      <div class="rows">
        {% for label, count in audience_type_counts %}
          <span><b>{{ count }}</b>{{ label }}</span>
        {% endfor %}
      </div>
    </div>
  </div>

  <div class="filters">
    <a href="?category=&status={{ selected_status }}" class="{{ 'active' if not selected_category else '' }}">전체</a>
    {% for cat in categories %}
      <a href="?category={{ cat }}&status={{ selected_status }}" class="{{ 'active' if selected_category == cat else '' }}">{{ cat }}</a>
    {% endfor %}
  </div>
  <div class="filters">
    <a href="?category={{ selected_category }}&status=" class="{{ 'active' if not selected_status else '' }}">분류상태: 전체</a>
    <a href="?category={{ selected_category }}&status=classified" class="{{ 'active' if selected_status == 'classified' else '' }}">분류완료만 ({{ classified }})</a>
    <a href="?category={{ selected_category }}&status=unclassified" class="{{ 'active' if selected_status == 'unclassified' else '' }}">미분류만 ({{ total - classified }})</a>
  </div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>전시회명</th><th>기간</th><th>국가</th><th>도시</th><th>베뉴</th>
        <th>참관대상</th><th>거래유형</th><th>대륙</th><th>food_yn</th><th>규모</th><th>키워드</th>
        <th>카테고리</th><th>웹사이트</th><th>소개(intro_ko 있으면 그걸로)</th><th>상태</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr class="{{ '' if r.is_active else 'inactive' }}">
        <td>{{ r.id }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.period_display }}</td>
        <td>{{ r.country }}</td>
        <td>{{ r.city }}</td>
        <td>{{ r.venue }}</td>
        <td>{{ r.audience_note }}</td>
        <td>{% if r.audience_type and r.audience_type != '미상' %}<span class="badge">{{ r.audience_type }}</span>{% endif %}</td>
        <td>{{ r.continent or '' }}</td>
        <td>
          {% if r.classified_at %}
            <span class="badge {{ 'yes' if r.food_yn else 'no' }}">{{ '식품' if r.food_yn else '비식품' }}</span>
          {% else %}
            <span class="badge unclassified">미분류</span>
          {% endif %}
        </td>
        <td>{{ r.scale or '' }}</td>
        <td>{{ r.keywords or '' }}</td>
        <td><span class="badge">{{ r.category }}</span></td>
        <td>{% if r.website %}<a class="site" href="https://{{ r.website }}" target="_blank">{{ r.website }}</a>{% endif %}</td>
        <td class="intro">{{ r.intro_ko or r.intro }}</td>
        <td>{{ '활성' if r.is_active else '비활성' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


def _format_period(start_date, end_date):
    """start_date/end_date(YYYYMMDD 정수)를 표시용 문자열로.
    scripts/crawl/tradefairdates_scraper.UNKNOWN_DATE(99999999)와 같은 sentinel 규칙."""
    UNKNOWN_DATE = 99999999

    def fmt(ymd):
        if not ymd or ymd == UNKNOWN_DATE:
            return "날짜 미정"
        year, month, day = ymd // 10000, (ymd // 100) % 100, ymd % 100
        if day == 32:
            return f"{year}년 {month}월(일자 미정)"
        return f"{year:04d}-{month:02d}-{day:02d}"

    if not start_date or start_date == UNKNOWN_DATE:
        return "날짜 미정"
    if start_date == end_date:
        return fmt(start_date)
    return f"{fmt(start_date)} ~ {fmt(end_date)}"


def _value_counts(df, column, top_n=8):
    """pandas value_counts를 (라벨, 건수) 튜플 리스트로. 결측치는 '(미분류)'로 표시.

    food_yn은 SQLite에 NULL 섞인 0/1로 저장돼 있어서 pandas가 float(0.0/1.0)로
    읽어들이는데, fillna로 문자열을 섞은 뒤에 0/1 여부를 판단하면 이미 float+문자열이
    뒤섞여 있어서 판별이 안 된다 -> food_yn/1(True)/0(False) 여부는 fillna 전에 먼저
    "식품"/"비식품"으로 바꾼 뒤에 결측치를 채운다."""
    if column not in df.columns:
        return []
    series = df[column]
    if column == "food_yn":
        series = series.map({1: "식품", 1.0: "식품", True: "식품", 0: "비식품", 0.0: "비식품", False: "비식품"})
    series = series.fillna("(미분류)")
    counts = series.value_counts().head(top_n)
    return list(counts.items())


def get_conn():
    return sqlite3.connect(app.config["DB_PATH"])


@app.route("/")
def index():
    conn = get_conn()

    # pandas로 전체 테이블을 읽어 컬럼별 분류 통계 집계
    df = pd.read_sql_query("SELECT * FROM raw_exhibitions", conn)
    total = len(df)
    active = int(df["is_active"].sum()) if "is_active" in df.columns else 0
    classified = int(df["classified_at"].notna().sum()) if "classified_at" in df.columns else 0

    continent_counts = _value_counts(df, "continent")
    scale_counts = _value_counts(df, "scale")
    food_yn_counts = _value_counts(df, "food_yn")
    category_counts = _value_counts(df, "category")
    audience_type_counts = _value_counts(df, "audience_type")

    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT category FROM raw_exhibitions ORDER BY category")
    categories = [r[0] for r in cur.fetchall()]

    selected_category = request.args.get("category", "").strip()
    selected_status = request.args.get("status", "").strip()  # "" / "classified" / "unclassified"

    where = []
    params = []
    if selected_category:
        where.append("category = ?")
        params.append(selected_category)
    if selected_status == "classified":
        where.append("classified_at IS NOT NULL")
    elif selected_status == "unclassified":
        where.append("classified_at IS NULL")

    query = "SELECT * FROM raw_exhibitions"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id ASC"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    rows_with_period = []
    for r in rows:
        row = dict(r)
        row["period_display"] = _format_period(row.get("start_date"), row.get("end_date"))
        rows_with_period.append(row)

    return render_template_string(
        PAGE_TEMPLATE,
        rows=rows_with_period,
        total=total,
        active=active,
        classified=classified,
        categories=categories,
        selected_category=selected_category,
        continent_counts=continent_counts,
        scale_counts=scale_counts,
        food_yn_counts=food_yn_counts,
        category_counts=category_counts,
        audience_type_counts=audience_type_counts,
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

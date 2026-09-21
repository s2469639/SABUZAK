
#!/usr/bin/env python3
"""
sabuzak.db(raw_exhibitions) 내용을 브라우저에서 확인만 하는 초간단 미리보기 대시보드.

- 로그인/DB모델/템플릿 구조 없이 파일 하나로 바로 실행됩니다.
- 나중에 팀원들이 만들 본격 Flask 앱(app/ 구조)과는 완전히 독립적이라
  이 파일을 지워도 본 프로젝트에 아무 영향 없습니다. "데이터 잘 들어갔나" 확인용.

사전 준비:
    pip install flask

실행:
    python preview_dashboard.py
    (콘솔에 뜨는 http://127.0.0.1:5050 주소를 브라우저로 열기)

옵션:
    python preview_dashboard.py --db ../instance/sabuzak.db --port 5050
"""

import argparse
import os
import sqlite3

from flask import Flask, render_template_string, request

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabuzak.db")

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
  th, td { padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 13px; text-align: left; vertical-align: top; }
  th { background: #fafafa; position: sticky; top: 0; }
  tr:hover { background: #fbfbfb; }
  .inactive { opacity: 0.45; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #eef; color: #338; }
  .intro { max-width: 340px; color: #555; }
  a.site { color: #2563eb; text-decoration: none; }
</style>
</head>
<body>
  <h1>사부작 박람회 데이터 미리보기 (개발용)</h1>
  <div class="summary">
    총 {{ total }}건 (활성 {{ active }} / 비활성 {{ total - active }})
  </div>
  <div class="filters">
    <a href="?category=" class="{{ 'active' if not selected_category else '' }}">전체</a>
    {% for cat in categories %}
      <a href="?category={{ cat }}" class="{{ 'active' if selected_category == cat else '' }}">{{ cat }}</a>
    {% endfor %}
  </div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>전시회명</th><th>기간</th><th>국가</th><th>도시</th><th>베뉴</th>
        <th>카테고리</th><th>웹사이트</th><th>소개</th><th>상태</th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr class="{{ '' if r.is_active else 'inactive' }}">
        <td>{{ r.id }}</td>
        <td>{{ r.name }}</td>
        <td>{{ r.period }}</td>
        <td>{{ r.country }}</td>
        <td>{{ r.city }}</td>
        <td>{{ r.venue }}</td>
        <td><span class="badge">{{ r.category }}</span></td>
        <td>{% if r.website %}<a class="site" href="https://{{ r.website }}" target="_blank">{{ r.website }}</a>{% endif %}</td>
        <td class="intro">{{ r.intro }}</td>
        <td>{{ '활성' if r.is_active else '비활성' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""


def get_conn():
    return sqlite3.connect(app.config["DB_PATH"])


@app.route("/")
def index():
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM raw_exhibitions")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM raw_exhibitions WHERE is_active = 1")
    active = cur.fetchone()[0]
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
    rows = cur.fetchall()
    conn.close()

    return render_template_string(
        PAGE_TEMPLATE,
        rows=rows,
        total=total,
        active=active,
        categories=categories,
        selected_category=selected_category,
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

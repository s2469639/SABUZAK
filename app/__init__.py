import re
from datetime import datetime, timedelta, timezone

from flask import Flask, redirect, url_for
from sqlalchemy import inspect, text

from app.extensions import db, login_manager


def split_points(text_, limit=4):
    """v15(트렌드 조사/부스 컨셉)의 리테일 분석 긴 문장을 불릿용으로 나눈다
    (문장 끝·쉼표 기준, 너무 짧게 쪼개지면 원문 그대로). v15/app.py 원본 그대로."""
    text_ = str(text_ or "").strip()
    if not text_:
        return []
    parts = [p.strip(" .·-") for p in re.split(r"(?<=[.!?。])\s+|(?<=다)\.\s*|\s*[;·•]\s*|\n+", text_)]
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        parts = [p.strip() for p in text_.split(", ") if p.strip()]
    if len(parts) <= 1 or any(len(p) < 4 for p in parts):
        return [text_]
    return parts[:limit]


def chips(text_, limit=6):
    """'400g, 밀키트, 멸치 육수와 생면 포함' -> 칩 목록. v15/app.py 원본 그대로."""
    parts = [p.strip() for p in re.split(r"[,/·]|\s+\+\s+", str(text_ or "")) if p.strip()]
    return parts[:limit]


def format_kdate(value):
    """YYYYMMDD(int/str) -> '2026.09.22'. 값이 없거나 형식이 다르면 원본 그대로 반환.
    크롤링 원본에 날짜가 없어서 UNKNOWN_DATE(99999999) 센티널로 저장된 경우
    "9999.99.99"처럼 날짜인 척 보이는 걸 막기 위해 "일정 미정"으로 표시한다."""
    if not value:
        return ""
    s = str(value)
    if s == "99999999":
        return "일정 미정"
    if len(s) != 8 or not s.isdigit():
        return s
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}"


def format_kdate_range(start, end):
    """start_date/end_date(YYYYMMDD) 쌍 -> '2026.09.22 ~ 2026.09.24'.
    둘 다 UNKNOWN_DATE(99999999)이거나 비어있으면 "일정 미정 ~ 일정 미정"처럼
    안 보이게 "일정 미정" 하나로 합쳐서 보여준다."""
    start_s, end_s = str(start or ""), str(end or "")
    if start_s in ("", "99999999") and end_s in ("", "99999999"):
        return "일정 미정"
    return f"{format_kdate(start)} ~ {format_kdate(end)}"


def usd_short(value):
    """차트 눈금/막대 위에 쓸 짧은 금액 표기 (예: 7,829,826,046 -> $7.8B).
    un_v6/app.py의 usd_short 필터 그대로."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    a = abs(v)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"${v / div:,.1f}{suffix}"
    return f"${v:,.0f}"


def pct(value):
    """점유율 표시. 1% 미만은 소수점을 더 보여주고, 아주 작으면 '<0.01%'로 표시해
    "0.0%(없음)"와 "조금 있음"이 구분되게 한다. un_v6/app.py의 pct 필터 그대로."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if v == 0:
        return "0%"
    a = abs(v)
    if a < 0.01:
        return "<0.01%"
    if a < 1:
        return f"{v:.2f}%"
    return f"{v:.1f}%"


def kst(value):
    """ISO 시각(UTC) -> '2026-09-23 20:36 (한국시간)'. un_v6/app.py의 kst 필터 그대로."""
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M (한국시간)")


def _sync_missing_columns(db):
    """db.create_all()은 없는 테이블만 만들고, 이미 있는 테이블에 모델에서
    새로 추가된 컬럼(예: Exhibition.hero_image_url)은 반영하지 않는다.
    이 프로젝트엔 별도 마이그레이션 도구(Alembic 등)가 없어서, 기존
    SQLite DB 파일을 쓰는 로컬/운영 환경에서 "no such column" 에러가
    반복적으로 났다. 여기서 SQLite ALTER TABLE ADD COLUMN으로 누락된
    컬럼만 안전하게(NULL 허용 컬럼만) 보충한다."""
    for bind_key, metadata in db.metadatas.items():
        engine = db.engines[bind_key]
        if engine.dialect.name != "sqlite":
            continue
        inspector = inspect(engine)
        for table in metadata.tables.values():
            if not inspector.has_table(table.name):
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                if not column.nullable and column.server_default is None:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def create_app(config_object="config.Config"):
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config.setdefault("SECRET_KEY", "dev-secret-key-change-me")
    if app.config["SECRET_KEY"] == "dev-secret-key-change-me" and not app.debug:
        # 배포 환경에서 SECRET_KEY 환경변수를 안 넣으면 로그인 세션이 누구나
        # 아는 키로 서명돼서 위조 가능해진다. 조용히 넘어가지 않고 로그에
        # 크게 경고를 남긴다 (서버 기동 자체는 막지 않음 - 로컬 테스트 등
        # SECRET_KEY 없이도 돌려봐야 하는 경우가 있어서).
        app.logger.warning(
            "!!! SECRET_KEY 환경변수가 설정되지 않아 기본값을 쓰고 있습니다. "
            "배포 환경이라면 지금 바로 SECRET_KEY를 랜덤 값으로 설정하세요 "
            "(예: python -c \"import secrets; print(secrets.token_hex(32))\")."
        )
    app.jinja_env.filters["kdate"] = format_kdate
    app.jinja_env.globals["kdate_range"] = format_kdate_range
    app.jinja_env.filters["usd_short"] = usd_short
    app.jinja_env.filters["pct"] = pct
    app.jinja_env.filters["kst"] = kst
    app.jinja_env.filters["split_points"] = split_points
    app.jinja_env.filters["chips"] = chips

    @app.route("/")
    def root():
        return redirect(url_for("auth.login"))

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.routes.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.routes.mypage import bp as mypage_bp
    app.register_blueprint(mypage_bp)

    from app.routes.exhibition import bp as exhibition_bp
    app.register_blueprint(exhibition_bp)

    from app.routes.concept import bp as concept_bp
    app.register_blueprint(concept_bp)

    from app.routes.drafts import bp as drafts_bp
    app.register_blueprint(drafts_bp)

    from app.routes.trend_v2 import api_bp as trend_v2_api_bp, pages_bp as trend_v2_pages_bp
    app.register_blueprint(trend_v2_pages_bp)
    app.register_blueprint(trend_v2_api_bp)

    from app.routes.buyers import (
        buyer_gmail_bp,
        buyer_profile_bp,
        contacts_bp,
        followup_bp,
        mail_template_bp,
    )
    app.register_blueprint(contacts_bp)
    app.register_blueprint(followup_bp)
    app.register_blueprint(mail_template_bp)
    app.register_blueprint(buyer_profile_bp)
    app.register_blueprint(buyer_gmail_bp)

    # 나머지 blueprint(proposal, crawl)는
    # 구현되는 대로 여기에 register_blueprint 하면 됩니다.

    with app.app_context():
        db.create_all()
        _sync_missing_columns(db)

    return app

from datetime import datetime, timedelta, timezone

from flask import Flask, redirect, url_for
from sqlalchemy import inspect, text

from app.extensions import db, login_manager


def format_kdate(value):
    """YYYYMMDD(int/str) -> '2026.09.22'. 값이 없거나 형식이 다르면 원본 그대로 반환."""
    if not value:
        return ""
    s = str(value)
    if len(s) != 8 or not s.isdigit():
        return s
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}"


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
    app.jinja_env.filters["kdate"] = format_kdate
    app.jinja_env.filters["usd_short"] = usd_short
    app.jinja_env.filters["pct"] = pct
    app.jinja_env.filters["kst"] = kst

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

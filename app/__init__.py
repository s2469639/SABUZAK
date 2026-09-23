from flask import Flask, redirect, url_for

from app.extensions import db, login_manager


def format_kdate(value):
    """YYYYMMDD(int/str) -> '2026.09.22'. 값이 없거나 형식이 다르면 원본 그대로 반환."""
    if not value:
        return ""
    s = str(value)
    if len(s) != 8 or not s.isdigit():
        return s
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}"


def create_app(config_object="config.Config"):
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config.setdefault("SECRET_KEY", "dev-secret-key-change-me")
    app.jinja_env.filters["kdate"] = format_kdate

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

    return app

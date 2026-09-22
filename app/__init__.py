from flask import Flask, redirect, url_for

from app.extensions import db, login_manager


def create_app(config_object="config.Config"):
    app = Flask(__name__)
    app.config.from_object(config_object)

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

    # 나머지 blueprint(exhibition, concept, proposal, drafts,
    # mypage, buyers, crawl)는 구현되는 대로 여기에 register_blueprint 하면 됩니다.

    with app.app_context():
        db.create_all()

    return app

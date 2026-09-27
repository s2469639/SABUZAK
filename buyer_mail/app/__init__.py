import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, redirect, request, url_for
from flask_login import current_user

from app.extensions import db, login_manager

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")

    os.makedirs(app.instance_path, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "sabuzaktest.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 명함 이미지 업로드 크기 제한

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import Exhibition, User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import bp as auth_bp
    from app.routes.contacts import bp as contacts_bp
    from app.routes.followup import bp as followup_bp
    from app.routes.mail_template import bp as mail_template_bp
    from app.routes.profile import bp as profile_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(contacts_bp)
    app.register_blueprint(followup_bp)
    app.register_blueprint(mail_template_bp)
    app.register_blueprint(profile_bp)

    # 박람회 더미 데이터: 본 프로젝트 연동 전까지 임시로 채워둠
    DUMMY_EXHIBITIONS = [
        "SIAL Paris 2026",
        "Gulfood Dubai 2026",
        "Foodex Japan 2026",
        "ANUGA Cologne 2026",
        "Seoul Food 2026",
    ]

    with app.app_context():
        db.create_all()
        if not Exhibition.query.first():
            db.session.add_all(Exhibition(name=name) for name in DUMMY_EXHIBITIONS)
            db.session.commit()

    # 127.0.0.1과 localhost는 브라우저 쿠키 저장소가 서로 달라서, 세션이 저장된 주소와
    # Google OAuth 리디렉션 주소(.env의 GOOGLE_REDIRECT_URI)가 다르면 로그인이 매번 한 번씩
    # 실패한다. 접속 주소를 항상 GOOGLE_REDIRECT_URI 쪽 호스트로 통일시켜 이 문제를 막는다.
    canonical_host = urlparse(os.environ.get("GOOGLE_REDIRECT_URI", "")).netloc
    ALIAS_HOSTS = {"127.0.0.1", "localhost"}

    @app.before_request
    def _canonicalize_host():
        # POST/PUT/DELETE 등은 리디렉션 시 브라우저가 GET으로 바꿔버려 요청이 깨지므로
        # 페이지 이동(GET/HEAD)에만 적용한다.
        if request.method not in ("GET", "HEAD"):
            return None
        if not canonical_host or request.host == canonical_host:
            return None
        current_hostname = request.host.split(":")[0]
        canonical_hostname = canonical_host.split(":")[0]
        if current_hostname in ALIAS_HOSTS and canonical_hostname in ALIAS_HOSTS:
            return redirect(request.url.replace(request.host, canonical_host, 1))
        return None

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("contacts.list_contacts"))
        return redirect(url_for("auth.login"))

    return app

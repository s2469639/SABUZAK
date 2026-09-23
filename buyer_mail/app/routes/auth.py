from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user

from app.extensions import db
from app.models import User
from app.services.google_oauth import build_flow, encrypt_token, fetch_userinfo

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login():
    return render_template("login.html")


@bp.route("/auth/google")
def google_login():
    flow = build_flow()
    # access_type=offline + prompt=consent 이어야 매번 refresh_token을 받을 수 있다
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["oauth_state"] = state
    session["code_verifier"] = flow.code_verifier
    return redirect(auth_url)


@bp.route("/auth/google/callback")
def google_callback():
    state = session.get("oauth_state")
    if not state or state != request.args.get("state"):
        flash("로그인 요청이 유효하지 않습니다. 다시 시도해주세요.")
        return redirect(url_for("auth.login"))

    flow = build_flow()
    flow.code_verifier = session.get("code_verifier")
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials

    if not credentials.refresh_token:
        flash("Gmail 발송 권한 승인이 필요합니다. 다시 로그인해주세요.")
        return redirect(url_for("auth.login"))

    userinfo = fetch_userinfo(credentials)
    google_id = userinfo["id"]

    user = User.query.filter_by(google_id=google_id).first()
    if user is None:
        user = User(google_id=google_id, google_email=userinfo["email"], name=userinfo.get("name", userinfo["email"]))

    user.google_email = userinfo["email"]
    user.google_refresh_token = encrypt_token(credentials.refresh_token)

    db.session.add(user)
    db.session.commit()

    login_user(user)
    return redirect(url_for("contacts.list_contacts"))


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

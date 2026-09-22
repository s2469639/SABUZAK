from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "danger")
            return render_template("auth/login.html", email=email)

        login_user(user, remember=bool(request.form.get("remember")))
        next_url = request.args.get("next")
        return redirect(next_url or url_for("dashboard.index"))

    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        name = request.form.get("name", "").strip()
        company = request.form.get("company", "").strip()

        form_data = {"email": email, "name": name, "company": company}

        if not email or not password or not name:
            flash("이메일, 비밀번호, 이름은 필수 입력 항목입니다.", "danger")
            return render_template("auth/register.html", **form_data)

        if password != password_confirm:
            flash("비밀번호가 일치하지 않습니다.", "danger")
            return render_template("auth/register.html", **form_data)

        if User.query.filter_by(email=email).first() is not None:
            flash("이미 가입된 이메일입니다.", "danger")
            return render_template("auth/register.html", **form_data)

        user = User(email=email, name=name, company=company or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("회원가입이 완료되었습니다.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("auth.login"))

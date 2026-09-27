from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import EmailTemplate
from app.services.llm import revise_email_template

bp = Blueprint("mail_template", __name__)

VERSIONS = (1, 2, 3)


def _get_version(version: int) -> EmailTemplate:
    template = EmailTemplate.query.filter_by(version=version, user_id=current_user.id).first()
    if template is None:
        # 이 사용자에게 아직 아무 버전도 없으면 처음 만드는 버전을 기본 활성으로 지정
        is_first_ever = EmailTemplate.query.filter_by(user_id=current_user.id).count() == 0
        template = EmailTemplate(version=version, user_id=current_user.id, is_active=is_first_ever)
        db.session.add(template)
        db.session.commit()
    return template


@bp.route("/template")
@login_required
def home():
    active = EmailTemplate.query.filter_by(user_id=current_user.id, is_active=True).first()
    version = active.version if active else 1
    return redirect(url_for("mail_template.edit_template", version=version))


@bp.route("/template/<int:version>")
@login_required
def edit_template(version):
    if version not in VERSIONS:
        version = 1
    template = _get_version(version)
    all_versions = [_get_version(v) for v in VERSIONS]
    return render_template(
        "template_edit.html", template=template, all_versions=all_versions, version=version
    )


@bp.route("/template/<int:version>/save", methods=["POST"])
@login_required
def save(version):
    template = _get_version(version)
    template.subject = request.form["subject"]
    template.body = request.form["body"]
    template.updated_at = datetime.utcnow()
    db.session.commit()
    flash(f"버전 {version} 템플릿이 저장되었습니다.")
    return redirect(url_for("mail_template.edit_template", version=version))


@bp.route("/template/<int:version>/revise", methods=["POST"])
@login_required
def revise(version):
    template = _get_version(version)
    instruction = request.form.get("instruction", "").strip()

    try:
        subject, body = revise_email_template(
            instruction,
            template.subject or "",
            template.body or "",
            sender_company=current_user.company_name or "",
            product_description=current_user.product_description or "",
        )
    except Exception as exc:
        flash(f"템플릿 수정에 실패했습니다: {exc}")
        return redirect(url_for("mail_template.edit_template", version=version))

    template.subject = subject
    template.body = body
    template.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("mail_template.edit_template", version=version))


@bp.route("/template/<int:version>/label", methods=["POST"])
@login_required
def rename(version):
    template = _get_version(version)
    template.label = request.form.get("label", "").strip() or None
    db.session.commit()
    return redirect(url_for("mail_template.edit_template", version=version))


@bp.route("/template/<int:version>/activate", methods=["POST"])
@login_required
def activate(version):
    EmailTemplate.query.filter(
        EmailTemplate.user_id == current_user.id, EmailTemplate.version != version
    ).update({"is_active": False})
    template = _get_version(version)
    template.is_active = True
    db.session.commit()
    flash(f"버전 {version}이(가) 발송용 템플릿으로 설정되었습니다.")
    return redirect(url_for("mail_template.edit_template", version=version))

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Contact, EmailTemplate, FollowupEmail
from app.services.llm import revise_individual_email
from app.services.mailer import send_via_gmail
from app.services.mailmerge import render_email

bp = Blueprint("followup", __name__)

TEMPLATE_VERSIONS = (1, 2, 3)


def _get_owned_contact(contact_id):
    return Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()


def _get_active_template():
    return EmailTemplate.query.filter_by(user_id=current_user.id, is_active=True).first()


def _resolve_template(contact):
    """이 바이어에게 지정된 선호 버전이 있으면 그걸, 없으면 발송용(활성) 버전을 쓴다."""
    if contact.preferred_template_version:
        template = EmailTemplate.query.filter_by(
            version=contact.preferred_template_version, user_id=current_user.id
        ).first()
        if template and template.subject and template.body:
            return template
    return _get_active_template()


def _fill_contact_from_template(contact, template):
    subject, body = render_email(template.subject, template.body, contact, current_user)
    followup = contact.followup or FollowupEmail(contact_id=contact.id)
    followup.subject = subject
    followup.body = body
    followup.status = "draft"
    followup.template_version = template.version
    followup.generated_at = datetime.utcnow()
    followup.sent_at = None

    db.session.add(followup)
    db.session.commit()
    return followup


@bp.route("/contacts/<int:contact_id>/followup")
@login_required
def view_followup(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None:
        template = _resolve_template(contact)
        if template is None or not template.subject or not template.body:
            flash("먼저 메일 템플릿을 작성해주세요.")
            return redirect(url_for("mail_template.home"))
        followup = _fill_contact_from_template(contact, template)

    templates_by_version = {t.version: t for t in EmailTemplate.query.filter(
        EmailTemplate.version.in_(TEMPLATE_VERSIONS), EmailTemplate.user_id == current_user.id
    ).all()}
    return render_template(
        "followup_edit.html",
        contact=contact,
        followup=followup,
        template_versions=TEMPLATE_VERSIONS,
        templates_by_version=templates_by_version,
    )


@bp.route("/contacts/<int:contact_id>/followup/fill", methods=["POST"])
@login_required
def fill_from_template(contact_id):
    contact = _get_owned_contact(contact_id)
    if contact.followup and contact.followup.status == "sent":
        flash("이미 발송된 메일은 다시 채울 수 없습니다. 재발송을 이용해주세요.")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    version = request.form.get("version", type=int)

    if version:
        template = EmailTemplate.query.filter_by(version=version, user_id=current_user.id).first()
        if template is None or not template.subject or not template.body:
            flash(f"버전 {version} 템플릿에 아직 내용이 없습니다.")
            return redirect(url_for("followup.view_followup", contact_id=contact.id))
    else:
        template = _resolve_template(contact)
        if template is None or not template.subject or not template.body:
            flash("먼저 메일 템플릿을 작성해주세요.")
            return redirect(url_for("mail_template.home"))

    _fill_contact_from_template(contact, template)
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@bp.route("/contacts/<int:contact_id>/followup/revise", methods=["POST"])
@login_required
def revise(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None or not followup.subject or not followup.body:
        flash("먼저 내용을 채워주세요.")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))
    if followup.status == "sent":
        flash("이미 발송된 메일은 수정할 수 없습니다. 재발송을 이용해주세요.")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    instruction = request.form.get("instruction", "").strip()
    try:
        subject, body = revise_individual_email(
            instruction,
            followup.subject,
            followup.body,
            sender_company=current_user.company_name or "",
            product_description=current_user.product_description or "",
        )
    except Exception as exc:
        flash(f"AI 수정에 실패했습니다: {exc}")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    followup.subject = subject
    followup.body = body
    if followup.status != "sent":
        followup.status = "edited"
    db.session.commit()
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@bp.route("/contacts/<int:contact_id>/followup/save", methods=["POST"])
@login_required
def save(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None:
        flash("먼저 템플릿으로 채워주세요.")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))
    if followup.status == "sent":
        flash("이미 발송된 메일은 수정할 수 없습니다. 재발송을 이용해주세요.")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    followup.subject = request.form["subject"]
    followup.body = request.form["body"]
    followup.status = "edited"
    db.session.commit()
    flash("내용이 저장되었습니다.")
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@bp.route("/contacts/<int:contact_id>/followup/send", methods=["POST"])
@login_required
def send(contact_id):
    contact = _get_owned_contact(contact_id)
    followup = contact.followup
    if followup is None or not followup.subject or not followup.body:
        flash("발송할 내용이 없습니다.")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    try:
        send_via_gmail(current_user, contact.email, followup.subject, followup.body)
    except Exception as exc:
        followup.status = "failed"
        db.session.commit()
        flash(f"발송에 실패했습니다: {exc}")
        return redirect(url_for("followup.view_followup", contact_id=contact.id))

    followup.status = "sent"
    followup.sent_at = datetime.utcnow()
    followup.last_sent_at = followup.sent_at
    followup.dismissed = False
    db.session.commit()
    flash(f"{contact.email} 로 메일을 발송했습니다.")
    return redirect(url_for("contacts.list_contacts"))


@bp.route("/contacts/<int:contact_id>/followup/compose_new", methods=["POST"])
@login_required
def compose_new(contact_id):
    """이미 보낸 바이어에게 새 메일 초안을 템플릿에서 다시 만들고, 수정 화면으로 이동한다
    (여기서 바로 발송하지 않고 검토·수정 후 직접 발송하도록 한다)."""
    contact = _get_owned_contact(contact_id)
    template = _resolve_template(contact)
    if template is None or not template.subject or not template.body:
        flash("먼저 메일 템플릿을 작성해주세요.")
        return redirect(url_for("mail_template.home"))

    _fill_contact_from_template(contact, template)
    return redirect(url_for("followup.view_followup", contact_id=contact.id))


@bp.route("/contacts/<int:contact_id>/followup/dismiss_stale", methods=["POST"])
@login_required
def dismiss_stale(contact_id):
    contact = _get_owned_contact(contact_id)
    if contact.followup:
        contact.followup.dismissed = True
        db.session.commit()
    return redirect(url_for("contacts.list_contacts"))


@bp.route("/contacts/send_selected", methods=["POST"])
@login_required
def send_selected():
    ids = request.form.getlist("contact_ids", type=int)
    if not ids:
        flash("선택된 바이어가 없습니다.")
        return redirect(url_for("contacts.list_contacts"))

    contacts = Contact.query.filter(
        Contact.id.in_(ids), Contact.user_id == current_user.id
    ).all()

    sent, failed, skipped = 0, 0, 0
    for contact in contacts:
        template = _resolve_template(contact)
        if template is None or not template.subject or not template.body:
            skipped += 1
            continue

        subject, body = render_email(template.subject, template.body, contact, current_user)
        followup = contact.followup or FollowupEmail(contact_id=contact.id)
        followup.subject = subject
        followup.body = body
        followup.template_version = template.version
        followup.generated_at = datetime.utcnow()

        try:
            send_via_gmail(current_user, contact.email, subject, body)
            followup.status = "sent"
            followup.sent_at = datetime.utcnow()
            followup.last_sent_at = followup.sent_at
            followup.dismissed = False
            sent += 1
        except Exception:
            followup.status = "failed"
            failed += 1

        db.session.add(followup)
        db.session.commit()

    message = f"선택 발송 완료: 성공 {sent}건, 실패 {failed}건 (선택 {len(contacts)}건 중)"
    if skipped:
        message += f" — 템플릿 없음으로 {skipped}건 건너뜀"
    flash(message)
    return redirect(url_for("contacts.list_contacts"))

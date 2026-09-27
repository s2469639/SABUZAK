from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Contact, EmailTemplate, Exhibition
from app.services.card_scan import scan_business_card

bp = Blueprint("contacts", __name__)

STALE_DAYS = 21


def _is_stale(contact: Contact) -> bool:
    followup = contact.followup
    if not followup or followup.status != "sent" or not followup.sent_at or followup.dismissed:
        return False
    return datetime.utcnow() - followup.sent_at >= timedelta(days=STALE_DAYS)


@bp.route("/contacts")
@login_required
def list_contacts():
    query = Contact.query.filter_by(user_id=current_user.id)
    exhibition_id = request.args.get("exhibition_id", type=int)
    if exhibition_id:
        query = query.filter_by(exhibition_id=exhibition_id)
    sort = request.args.get("sort", "desc")
    if sort not in ("asc", "desc"):
        sort = "desc"
    order = Contact.created_at.asc() if sort == "asc" else Contact.created_at.desc()
    contacts = query.order_by(order).all()

    stale = [c for c in contacts if _is_stale(c)]
    others = [c for c in contacts if not _is_stale(c)]
    contacts = stale + others
    stale_ids = {c.id for c in stale}
    stale_days = {c.id: (datetime.utcnow() - c.followup.sent_at).days for c in stale}

    exhibitions = Exhibition.query.order_by(Exhibition.name).all()
    active_template = EmailTemplate.query.filter_by(user_id=current_user.id, is_active=True).first()
    has_usable_template = bool(active_template and active_template.subject and active_template.body)
    template_labels = {
        t.version: t.label for t in EmailTemplate.query.filter_by(user_id=current_user.id).all()
    }
    return render_template(
        "contacts_list.html",
        contacts=contacts,
        exhibitions=exhibitions,
        selected_exhibition_id=exhibition_id,
        sort=sort,
        stale_ids=stale_ids,
        stale_days=stale_days,
        active_version=active_template.version if has_usable_template else None,
        template_labels=template_labels,
    )


@bp.route("/contacts/new", methods=["GET", "POST"])
@login_required
def new_contact():
    exhibitions = Exhibition.query.order_by(Exhibition.name).all()
    template_versions = (
        EmailTemplate.query.filter_by(user_id=current_user.id).order_by(EmailTemplate.version).all()
    )
    if request.method == "POST":
        contact = Contact(
            user_id=current_user.id,
            exhibition_id=int(request.form["exhibition_id"]),
            name=request.form["name"].strip(),
            company=request.form.get("company", "").strip(),
            position=request.form.get("position", "").strip(),
            email=request.form["email"].strip(),
            phone=request.form.get("phone", "").strip(),
            address=request.form.get("address", "").strip(),
            remarks=request.form.get("remarks", "").strip(),
            preferred_template_version=request.form.get("preferred_template_version", type=int),
        )
        db.session.add(contact)
        db.session.commit()
        flash("바이어가 등록되었습니다.")
        return redirect(url_for("contacts.list_contacts"))
    prefill = session.pop("card_prefill", None)
    return render_template(
        "contact_form.html",
        contact=None,
        exhibitions=exhibitions,
        prefill=prefill,
        template_versions=template_versions,
    )


@bp.route("/contacts/scan_card", methods=["POST"])
@login_required
def scan_card():
    image = request.files.get("card_image")
    if not image or not image.filename:
        flash("명함 이미지를 선택해주세요.")
        return redirect(url_for("contacts.new_contact"))
    if not (image.mimetype or "").startswith("image/"):
        flash("이미지 파일만 업로드할 수 있습니다.")
        return redirect(url_for("contacts.new_contact"))

    try:
        session["card_prefill"] = scan_business_card(image.read(), image.mimetype)
    except Exception as exc:
        flash(f"명함 인식에 실패했습니다: {exc}")

    return redirect(url_for("contacts.new_contact"))


@bp.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contact(contact_id):
    contact = Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()
    exhibitions = Exhibition.query.order_by(Exhibition.name).all()
    template_versions = (
        EmailTemplate.query.filter_by(user_id=current_user.id).order_by(EmailTemplate.version).all()
    )
    if request.method == "POST":
        contact.exhibition_id = int(request.form["exhibition_id"])
        contact.name = request.form["name"].strip()
        contact.company = request.form.get("company", "").strip()
        contact.position = request.form.get("position", "").strip()
        contact.email = request.form["email"].strip()
        contact.phone = request.form.get("phone", "").strip()
        contact.address = request.form.get("address", "").strip()
        contact.remarks = request.form.get("remarks", "").strip()
        contact.preferred_template_version = request.form.get("preferred_template_version", type=int)
        db.session.commit()
        flash("수정되었습니다.")
        return redirect(url_for("contacts.list_contacts"))
    return render_template(
        "contact_form.html",
        contact=contact,
        exhibitions=exhibitions,
        template_versions=template_versions,
    )


@bp.route("/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(contact_id):
    contact = Contact.query.filter_by(id=contact_id, user_id=current_user.id).first_or_404()
    db.session.delete(contact)
    db.session.commit()
    flash("삭제되었습니다.")
    return redirect(url_for("contacts.list_contacts"))

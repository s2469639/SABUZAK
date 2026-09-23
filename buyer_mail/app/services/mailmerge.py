from datetime import date


def render_email(subject_template: str, body_template: str, contact, sender) -> tuple[str, str]:
    replacements = {
        "{{name}}": contact.name,
        "{{company}}": contact.company or "",
        "{{exhibition}}": contact.exhibition.name if contact.exhibition else "",
        "{{date}}": date.today().strftime("%B %d, %Y"),
        "{{sender_name}}": sender.name or "",
        "{{sender_company}}": sender.company_name or "",
        "{{sender_position}}": sender.position or "",
    }
    subject = subject_template
    body = body_template
    for placeholder, value in replacements.items():
        subject = subject.replace(placeholder, value)
        body = body.replace(placeholder, value)
    return subject, body

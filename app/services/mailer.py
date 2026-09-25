import base64
from email.message import EmailMessage

import requests

from app.services.google_oauth import get_access_token

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def build_message(user, to_email: str, subject: str, body: str, attachments=None) -> EmailMessage:
    """attachments: [(파일명, content_type, 바이트), ...]"""
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = user.google_email
    message["Subject"] = subject
    message.set_content(body, charset="utf-8", cte="base64")

    for filename, content_type, data in attachments or []:
        maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
        message.add_attachment(
            data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename,
        )
    return message


def send_via_gmail(user, to_email: str, subject: str, body: str, attachments=None) -> None:
    access_token = get_access_token(user)

    message = build_message(user, to_email, subject, body, attachments)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    response = requests.post(
        GMAIL_SEND_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"raw": raw},
        timeout=60 if attachments else 15,
    )
    if not response.ok:
        raise RuntimeError(f"Gmail API {response.status_code}: {response.text}")

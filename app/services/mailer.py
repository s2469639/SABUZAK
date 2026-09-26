import base64
from email.mime.text import MIMEText

import requests

from app.services.google_oauth import get_access_token

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def send_via_gmail(user, to_email: str, subject: str, body: str) -> None:
    access_token = get_access_token(user)

    message = MIMEText(body)
    message["to"] = to_email
    message["from"] = user.google_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    response = requests.post(
        GMAIL_SEND_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"raw": raw},
        timeout=15,
    )
    if not response.ok:
        raise RuntimeError(f"Gmail API {response.status_code}: {response.text}")

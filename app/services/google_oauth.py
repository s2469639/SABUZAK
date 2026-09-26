import os

import requests
from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

# 로컬 개발은 http://localhost로만 돌아가서(HTTPS 없음) oauthlib의 기본
# "OAuth2는 HTTPS에서만" 체크를 꺼야 한다. 운영 배포 시 GOOGLE_REDIRECT_URI가
# https:// 주소가 되면 이 값과 무관하게 정상적으로 HTTPS로 통신한다.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# gmail.send는 발송 전용 최소 권한 (읽기/삭제 불가)
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.send",
]


def _client_config():
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def build_flow() -> Flow:
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=os.environ["GOOGLE_REDIRECT_URI"],
    )


def _fernet() -> Fernet:
    return Fernet(os.environ["TOKEN_ENCRYPT_KEY"].encode())


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def fetch_userinfo(credentials: Credentials) -> dict:
    resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_access_token(user) -> str:
    """저장된 refresh_token으로 매번 새 access_token을 발급받는다."""
    credentials = Credentials(
        token=None,
        refresh_token=decrypt_token(user.google_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    credentials.refresh(Request())
    return credentials.token

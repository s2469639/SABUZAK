import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    # 기본 DB(SQLALCHEMY_DATABASE_URI) = 박람회 데이터 전용
    #   raw_exhibitions
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'sabuzak.db')}"
    )

    # 별도 bind 2개 = 계정 데이터 / HS코드·관세 데이터
    SQLALCHEMY_BINDS = {
        # users, products
        "app_data": os.environ.get(
            "APP_DATABASE_URL",
            f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'app_data.db')}",
        ),
        # hs0code_master, ntm_measures
        "hscode_data": os.environ.get(
            "HSCODE_DATABASE_URL",
            f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'hscode.db')}",
        ),
    }

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 메일 첨부(합계 15MB 제한)보다 여유 있게, 이보다 큰 업로드는 요청 자체를 거부한다
    MAX_CONTENT_LENGTH = 30 * 1024 * 1024

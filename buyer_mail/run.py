import os

os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # 로컬 http 테스트용, 배포 시 제거

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)

import os

from dotenv import load_dotenv

load_dotenv(override=True)

from app import create_app

app = create_app()

if __name__ == "__main__":
    # FLASK_DEBUG=1을 .env에 넣으면 로컬 개발 중엔 디버거를 켤 수 있다.
    # 배포 환경(Render 등)에선 이 값을 절대 설정하면 안 됨 - 디버그 모드는
    # 에러 발생 시 외부에서 접근 가능한 인터랙티브 디버거(원격 코드 실행
    # 위험)를 켜버린다.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug)

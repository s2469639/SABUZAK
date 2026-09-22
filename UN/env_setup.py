"""API 키 확인/입력 도우미.

주의: 이 모듈은 input()/getpass()로 사용자 입력을 기다리므로, Flask가
"웹 요청을 처리하는 코드" 안에서는 절대 쓰면 안 된다. app.py/cli.py의
시작 지점에서만 호출한다.
"""

import os

from getpass import getpass

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

REQUIRED_KEYS = {
    "OPENAI_API_KEY": "OpenAI API 키",
    "UN_COMTRADE_SUBSCRIPTION_KEY": "UN Comtrade 무료 구독키 (comtradeplus.un.org 가입, 자동 승인)",
}


def ensure_required_keys():
    """필요한 키가 .env/환경변수에 없으면 터미널에서 직접 입력받는다."""
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)

    for env_name, label in REQUIRED_KEYS.items():
        if os.getenv(env_name):
            continue

        print(f"\n⚠️  {label}({env_name})가 설정되어 있지 않습니다.")
        value = getpass(f"{label}를 입력하세요 (입력값은 화면에 표시되지 않습니다): ").strip()
        if not value:
            print(f"오류: {label}가 입력되지 않았습니다.")
            raise SystemExit(1)

        os.environ[env_name] = value

        answer = input(".env 파일에 저장해서 다음부터 다시 안 물어보게 할까요? (y/N): ").strip().lower()
        if answer == "y":
            _save_to_env_file(env_name, value)
            print("  -> .env에 저장했습니다.")


def _save_to_env_file(env_name, value):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

    for i, line in enumerate(lines):
        if line.strip().startswith(f"{env_name}="):
            lines[i] = f"{env_name}={value}\n"
            break
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{env_name}={value}\n")

    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

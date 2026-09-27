"""API 키 확인/입력 도우미.

.env 위치: 이 파일이 있는 폴더부터 상위 폴더로 올라가며 가장 가까운 .env를 사용한다.
    SABUZAK/
    ├── .env            <- 여기 있는 파일을 찾아서 사용
    └── tavily_v5/
        └── env_setup.py

주의: 이 모듈의 ensure_required_keys()는 input()/getpass()로 사용자 입력을 기다리므로,
Flask 웹 요청 처리 코드 안에서는 쓰면 안 된다 (서버가 응답 없이 멈춤).
app.py/cli.py의 시작 지점에서만 호출한다.
"""

import os
from getpass import getpass
from pathlib import Path

REQUIRED_KEYS = {
    "OPENAI_API_KEY": "OpenAI API 키",
    "TAVILY_API_KEY": "Tavily API 키",
}


def find_env_path():
    """가장 가까운 상위 폴더의 .env 경로를 찾는다.
    없으면 저장소 최상위(.git이 있는 폴더)의 .env 경로를 반환한다 (새로 저장할 위치)."""
    here = Path(__file__).resolve().parent
    folders = [here, *here.parents]
    for folder in folders:
        if (folder / ".env").is_file():
            return str(folder / ".env")
    for folder in folders:
        if (folder / ".git").exists():
            return str(folder / ".env")
    return str(here.parent / ".env")


ENV_PATH = find_env_path()


def load_env():
    """.env를 읽는다. .env 값이 OS 환경변수보다 우선한다."""
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH, override=True)


def ensure_required_keys():
    """필요한 키가 .env/환경변수에 없으면 터미널에서 입력받는다."""
    load_env()
    print(f"사용 중인 .env: {ENV_PATH}" + ("" if os.path.exists(ENV_PATH) else " (파일 없음)"))

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
            print(f"  -> {ENV_PATH}에 저장했습니다.")


def _save_to_env_file(env_name, value):
    """.env 파일에서 해당 키 줄만 교체하고, 없으면 맨 끝에 추가한다."""
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

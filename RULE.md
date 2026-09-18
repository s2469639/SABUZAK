# 📋 Team Collaboration & Coding Rules (RULE.md)

이 문서는 팀 프로젝트의 원활한 협업과 코드 품질, 일관된 스타일 유지를 위한 규칙을 정의합니다. 모든 팀원은 아래 규칙을 준수해야 합니다.

**팀 구성**: PM 1명, 팀장 1명, 팀원 3명 (총 5명)
**배포 환경**: `main` + `develop` 이원화 운영

---

## 1. 기본 원칙

1. **공통 규칙 준수**: 전체 팀이 합의한 공통 규칙을 최우선으로 따릅니다.
2. **파트별 자율성**: 각자 맡은 파트 내에서는 필요에 따라 세부 구현 방식을 정할 수 있습니다.
3. **타인의 코드 수정 금지**: 다른 사람이 작성한 코드/파일은 임의로 수정하거나 삭제하지 않습니다. 수정이 필요할 경우 반드시 사전 협의를 거칩니다.
4. **브랜치 기반 작업**: 모든 작업은 개인 브랜치에서 진행하며, `main`/`develop`에 직접 커밋하거나 푸시하지 않습니다.
5. **역할 구분**:
   - **팀장**: 일정 관리, 이슈 우선순위 조정
   - **PM**: PR 최종 리뷰/머지 권한, `develop → main` 배포 승인
   - **팀원**: 개인 브랜치에서 기능 개발, PR 생성, 코드 리뷰 참여

---

## 2. 디렉토리 및 파일 구조 가이드

프로젝트 전반의 혼선을 방지하기 위해 역할별로 폴더를 명확히 분리합니다.

```text
root/
├── src/ (또는 app/)
│   ├── assets/          # 이미지, 아이콘, 폰트 등 정적 리소스
│   ├── components/      # 재사용 가능한 UI 컴포넌트
│   ├── pages/ (views/)  # 라우팅/화면 단위 페이지
│   ├── services/ (api/) # 외부 API 호출 및 통신 로직
│   ├── utils/           # 공통 함수, 헬퍼 함수
│   └── constants/       # 전역 상수 및 설정값
├── tests/               # 테스트 코드
├── .gitignore           # Git 제외 설정
├── README.md            # 프로젝트 개요 및 실행 방법
└── RULE.md              # 팀 협업 및 코딩 컨벤션
```

---

## 3. Streamlit / Flask 혼용 규칙

두 프레임워크를 함께 쓸 경우 역할을 명확히 분리합니다.

- **Flask**: API 서버 (데이터 처리, DB 연동, 비즈니스 로직) → `backend/` 하위에 위치
- **Streamlit**: 데이터 시각화, 데모/대시보드 UI → 별도 `dashboard/` 폴더로 분리 (Flask 앱과 물리적으로 분리 권장)

```text
root/
├── backend/             # Flask 서버
│   ├── app.py
│   ├── routes/
│   ├── services/
│   └── models/
├── dashboard/            # Streamlit 앱
│   ├── main.py
│   └── pages/
├── src/                  # 프론트엔드(React 등) 사용 시
├── tests/
├── .gitignore
├── README.md
└── RULE.md
```

- Flask와 Streamlit이 같은 데이터/유틸 함수를 쓸 경우, 로직은 `common/` 또는 `core/`에 두고 양쪽에서 import해서 사용 (중복 구현 금지)
- 포트 번호는 README.md에 명시 (예: Flask `:5000`, Streamlit `:8501`)
- 환경변수(`.env`)는 공통으로 관리하되, 프레임워크별 설정은 접두어로 구분 (`FLASK_`, `STREAMLIT_`)

---

## 4. 네이밍 컨벤션

### 4.1 변수 / 함수명
- **Python**: `snake_case` 사용 (예: `user_name`, `get_user_data()`)
- **JavaScript/React**: `camelCase` 사용 (예: `userName`, `getUserData()`)
- 불리언 변수는 `is_`, `has_`, `should_` 접두어 사용 (예: `is_valid`, `has_permission`)
- 약어 사용 지양, 의미가 명확한 이름 사용 (`usr` ❌ → `user` ✅)

### 4.2 상수
- 전역 상수는 `UPPER_SNAKE_CASE` (예: `MAX_RETRY_COUNT`, `API_BASE_URL`)
- `constants/` 폴더에 모아서 관리, 하드코딩 금지

### 4.3 클래스 / 컴포넌트명
- 클래스: `PascalCase` (예: `UserService`, `DataProcessor`)
- React 컴포넌트: `PascalCase` + 파일명도 동일하게 (예: `UserCard.jsx`)

### 4.4 파일 / 폴더명
- Python 파일: `snake_case.py`
- React 컴포넌트 파일: `PascalCase.jsx`
- 폴더명: 복수형 사용 (`components/`, `utils/`, `services/`)

### 4.5 API 라우트 / 엔드포인트
- RESTful 규칙 준수: `/api/users`, `/api/users/<id>`
- 동사 대신 명사 사용, 복수형 유지 (`/getUser` ❌ → `/users` ✅)

---

## 5. Git / GitHub 협업 규칙 (5인 팀 / 총 7개 브랜치)

### 5.1 브랜치 전략

총 **7개 브랜치**로 운영합니다: 메인 2개(`main`, `develop`) + 팀원별 개인 브랜치 5개.

| 브랜치 | 용도 | 비고 |
|---|---|---|
| `main` | 배포 가능한 최종 안정 버전 | 직접 push 금지, `develop`에서만 병합 |
| `develop` | 통합 개발 브랜치 (세컨더리) | 모든 기능 브랜치가 최종적으로 모이는 곳 |
| `feature/SY-기능명` | PM 작업 브랜치 | 
| `feature/HK-기능명` | 팀장 작업 브랜치 | 
| `feature/YJ-기능명` | 팀원1 작업 브랜치 | 
| `feature/GE-기능명` | 팀원2 작업 브랜치 | 
| `feature/JH-기능명` | 팀원3 작업 브랜치 | 

> 개인 브랜치명 앞에 담당자 식별자를 고정해 총 7개 브랜치가 한눈에 구분되도록 합니다. 버그 수정은 `fix/담당자-버그명` 형식을 동일하게 적용합니다 (예: `fix/mem2-chart-error`).

**작업 흐름**: 개인 브랜치 → PR → `develop` 병합 → (스프린트/마일스톤 단위로) PM 승인 후 `develop → main` 병합

### 5.2 커밋 메시지 규칙

타입: 무엇을 왜 바꿨는지 간결하게 설명 (명령조/명사형 종결 권장)

| 접두사 | 사용 목적 | 예시 |
| :--- | :--- | :--- |
| `feat` | 새로운 기능 개발 및 기존 기능 수정 | `feat: 사용자 프로필 페이지 추가` |
| `fix` | 버그, 에러, 화면 깨짐 등 오류 수정 | `fix: 메인 버튼 클릭 안 되는 현상 수정` |
| `chore` | 문서 작성/수정, 단순 코드 정리(잡무) | `chore: RULE.md 파일 업데이트` |

### 5.3 Pull Request 규칙

- **PR 방향**: 개인 브랜치 → `develop` (원칙), `develop` → `main`은 팀장 승인 하에 PM이 진행
- PR 제목은 커밋 메시지 규칙과 동일하게 작성
- PR 설명에 변경 사항, 테스트 방법, 관련 이슈 번호(`#12`) 명시
- **리뷰어 최소 1명 필수** — 5인 팀이므로 작성자를 제외한 팀장 또는 팀원 중 1명 이상 승인
- `develop → main` PR은 **팀장 + PM 모두 승인** 후 병합
- 본인 PR은 본인이 머지하지 않음 (셀프 머지 지양)
- 머지 방식은 `Squash and merge` 통일 (커밋 히스토리 정리)

### 5.4 이슈 관리

- 작업 시작 전 GitHub Issue 생성 → 브랜치명에 담당자+이슈 번호 포함 권장 (예: `feature/mem1-12-login-api`)
- 라벨 활용: `bug`, `feature`, `docs`, `urgent`, `pm-review`
- PM이 이슈 보드(Projects) 관리 및 스프린트 단위 우선순위 조정

### 5.5 .gitignore 필수 항목

```
__pycache__/
*.pyc
.env
venv/
.streamlit/secrets.toml
node_modules/
.DS_Store
```

---

## 6. 코드 스타일 / 린트

- Python: `black` + `flake8` (또는 `ruff`) 사용, 커밋 전 포맷팅 필수
- JavaScript: `eslint` + `prettier` 사용
- 들여쓰기: Python 4칸, JS 2칸 통일
- 커밋 전 `pre-commit` 훅 설정 권장 (포맷팅/린트 자동 검사)
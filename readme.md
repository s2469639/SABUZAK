# 사부작(SABUZAK) | K-전통스낵 해외 박람회 운영 자동화 대시보드

김부각·약과 등 K-전통스낵 수출기업 '사부작' 의 해외 박람회 운영 업무를 자동화하는 내부용 대시보드입니다. 해외 시장 조사, 박람회 일정 수집, 부스 컨셉 기획, 기안서 작성까지 하나의 화면에서 처리합니다.

# 제품군
사부작이 수출하는 5종 K-전통스낵입니다. 국가별 세부 HS코드·관세율은 박람회 상세 페이지의 HS코드 탭에서 확인합니다.

김부각	1905.90
유과	1905.90
약과	1905.90
누룽지칩	1904.90
고구마스틱	2005.99

# 화면 흐름
로그인 → 대시보드(세계 지도) → [대륙 클릭] → 대륙별 박람회 목록 → 박람회 상세
        → 부스 컨셉 기획 → 기안서 작성
        └ 작성 중인 박람회 (진행 상황 관리)
        └ 기타
            └ KOTRA 한국관 단체 참가 바로가기
            └ 정부 지원 사업 바로가기

① 대시보드 — 세계 지도에서 대륙을 클릭하면 해당 대륙의 박람회 목록 페이지로 이동 (권역: 아메리카 · 유럽 · 중동·아프리카 · 아시아 · 오세아니아)

② 대륙별 박람회 목록 — 선택한 대륙의 박람회를 목록으로 표시, 클릭 시 상세로 이동

③ 박람회 상세 — 4개 탭으로 구성
박람회 개요 — 개최지·장소·규모·카테고리·연간 방문객·참가 기업, 공식 소개
시장·트렌드 — 현재 환율, 시장 인사이트 카드(YoY 성장률 + 전략 제안)
HS코드 — 품목별 HS코드·관세율·필요 인증(HACCP 등)
수출 주의사항 — 필수/정보/주의 등급별 규제 카드(법령 근거 포함)

④ 부스 컨셉 기획 — 상세 데이터를 기반으로 AI가 부스 테마·슬로건, 핵심 셀링포인트, 이벤트 기획안 자동 생성 → 내용 수정 및 초안 저장 가능

⑤ 기안서 작성 — 컨셉을 바탕으로 참가 기안서 자동 생성 → 내용 수정 및 초안 저장 가능, PDF·Word 출력

⑥ 작성 중인 박람회 — 컨셉/기안서 진행 상태 관리 및 이어서 작성

# 주요 기능
세계 지도에서 대륙 클릭 → 대륙별 박람회 탐색
박람회 목록 날짜별·규모별 필터
박람회별 시장·규제·HS코드 정보 자동 정리
AI 부스 컨셉 자동 생성 후 수정·초안 저장
기안서 자동 작성 후 수정·초안 저장, PDF/Word 내보내기
작성 진행 상태(컨셉/기안서) 관리

## 기술 스택
- Backend — Python + Flask, Flask-Login(로그인), Flask-SQLAlchemy(DB)
- 데이터 처리 — pandas
- Frontend — Jinja2 템플릿 + HTML/CSS + 바닐라 JS (탭 전환, AI 생성 버튼, 초안 저장 등 AJAX)
- Database — SQLite (`instance/sabuzak.db`)
- 외부 연동 — 환율 API(실시간 환율), OpenAI API(부스 컨셉·기안서 생성, 박람회 자동 분류)

## 설치
한 번에 설치하려면:
```bash
./setup.sh
```
가상환경(.venv) 생성 (파이썬 3.11 기준) → `requirements.txt` 설치 → `.env` 생성(`.env.example` 복사) → DB 테이블 초기화까지 자동으로 처리합니다. 완료 후 `.env`에 `SECRET_KEY`, `OPENAI_API_KEY`를 채워주세요.

## 실행
```bash
source .venv/bin/activate
python run.py          # 기본 포트 5000
```

### raw_exhibitions 컬럼
DB 컬럼명은 영문으로 두고(SQL/ORM에서 매번 따옴표 처리를 안 해도 되고 다른 도구와의 호환성도 좋음), 화면에 한글로 보여주는 건 Jinja 템플릿의 라벨/필터가 담당합니다.

| 컬럼 | 화면 표시 | 설명 |
|---|---|---|
| id | 순번 | PK |
| detail_url | (비표시) | 크롤링 dedup용 내부 키 (tradefairdates.com 상세페이지 URL) |
| name | 박람회명 | |
| start_date / end_date | 시작일 / 종료일 | YYYYMMDD 숫자. 날짜 전체가 미상이면 `UNKNOWN_DATE`(99999999, 실존하는 모든 날짜보다 큰 sentinel), 연/월만 알고 일자가 미상이면 일(day)=`32`(예: 2027년 10월 중 → `20271032`)로 채움. **0을 미상 값으로 쓰면 오름차순 정렬에서 오히려 맨 앞으로 와버리므로 쓰지 않음** — 두 경우 모두 실제 날짜보다 큰 값이라 임박한 날짜 순 정렬 시 자연스럽게 맨 뒤로 감 |
| country | 국가 | DB에는 영문 원문 저장, 화면에는 `country_ko` 필터로 한글 표시 (예: Morocco → 모로코) |
| city / venue | 도시 / 장소 | 고유명사라 번역하지 않고 원문(영문) 그대로 표시 |
| audience_note | 참관대상 | 원문 그대로(예: "professional visitors only") |
| website | 웹사이트 | 박람회 공식 사이트 |
| intro | 상세설명(원문) | |
| intro_ko | 상세설명 | `preprocess.py`가 번역한 한국어 버전. 없으면 화면에서 `intro` 원문으로 대체 표시 |
| category | (비표시) | 크롤링 카테고리(내부용, 부분 크롤링 시 비활성화 범위 판단에 필요) |
| continent / food_yn / scale / keywords | 대륙 / food_yn / 규모 / 키워드 | `preprocess.py` 분류 결과 |
| classified_at | (비표시) | 마지막 분류 시각 (내부용, `preprocess.py`가 이미 분류된 건 건너뛰는 기준) |
| is_active | (비표시) | 최근 크롤링에서도 보였는지 |
| last_updated_at | 마지막 업데이트 | 박람회 상세 페이지에 표시 |

## 코드 구조
```
sabuzak/
├── app/                         # Flask 웹앱
│   ├── __init__.py              # create_app (앱 팩토리)
│   ├── extensions.py            # db, login_manager
│   ├── models.py                # Exhibition(=raw_exhibitions), ConceptDraft, ProposalDraft, User
│   ├── routes/
│   │   ├── auth.py              # 로그인/로그아웃
│   │   ├── dashboard.py         # 대시보드(세계 지도) · 대륙별 박람회 목록
│   │   ├── exhibition.py        # 박람회 상세 (개요·시장·HS코드·주의사항 + 환율)
│   │   ├── concept.py           # 부스 컨셉 생성 · 수정 · 초안 저장
│   │   ├── proposal.py          # 기안서 생성 · 수정 · 초안 저장 · PDF/Word 출력
│   │   ├── drafts.py            # 작성 중인 박람회 목록
│   │   └── crawl.py             # 크롤링 시작(POST /crawl/run) · 상태 조회(GET /crawl/status)
│   ├── services/
│   │   ├── data.py              # raw_exhibitions 조회/가공 (pandas)
│   │   ├── exchange.py          # 환율 API 호출 + 캐싱
│   │   ├── country_names.py     # 국가명 영문→한글 정적 매핑 (country_ko 필터)
│   │   ├── crawl_runner.py      # 백그라운드 스레드로 크롤링 실행 + 진행 상태 관리
│   │   ├── llm.py               # OpenAI 컨셉·기안서 생성
│   │   └── export.py            # PDF(weasyprint)/Word(python-docx) 출력
│   ├── templates/
│   │   ├── base.html            # 공통 레이아웃 (사이드바)
│   │   ├── login.html
│   │   ├── dashboard.html       # 세계 지도 (대륙 핀 클릭) + 크롤링 새로고침 버튼
│   │   ├── continent.html       # 대륙별 박람회 목록
│   │   ├── exhibition.html      # 상세 4탭
│   │   ├── concept.html         # 부스 컨셉 기획 (AI 생성·수정·저장)
│   │   ├── proposal.html        # 기안서 작성 (AI 생성·수정·저장·출력)
│   │   └── drafts.html          # 작성 중인 박람회
│   └── static/
│       ├── css/base.css
│       ├── js/                  # map.js(지도 핀), tabs.js(탭 전환), crawl.js(크롤링 버튼+스피너), concept.js, proposal.js
│       └── img/
├── scripts/                     # 데이터 파이프라인 (웹앱과 분리된 배치 스크립트)
│   ├── crawl/
│   │   ├── tradefairdates_scraper.py
│   │   ├── sync_to_db.py
│   │   └── multi_crawl_gui.py
│   └── classify/
│       └── preprocess.py        # 전처리 분류 기준
├── data/                        # HS코드·규제 등 정적 참조 데이터 (CSV 등, 준비 중)
├── instance/
│   └── sabuzak.db                # SQLite (git 미포함)
├── config.py
├── requirements.txt
├── run.py
├── .env.
└── README.md
```

# 데이터 소스
박람회 일정 — TradeFairDates
정부 지원금 — KATI(aT 농식품 수출정보), KOTRA 해외전시포털(gep.or.kr)
식품 규제 — 공공데이터포털(식품안전정보원 수출식품 부적합 사례)
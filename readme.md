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

# 기술 스택
Backend — Python + Flask
데이터 처리 — pandas
Frontend — Jinja2 템플릿 + HTML/CSS + 바닐라 JS (탭 전환·초안 저장 등)
Database — SQLite (초안 저장용, 별도 설치 불필요)
추가 설치 패키지

기존 python · flask · pandas 외에 아래 패키지가 필요합니다.

패키지	용도
Flask-SQLAlchemy	컨셉·기안서 초안 저장 (DB ORM)
requests	외부 API 호출 (박람회 일정 수집)
python-dotenv	환경변수(.env) 관리
anthropic (또는 openai)	LLM API — 컨셉·기안서 자동 생성
python-docx	기안서 Word(.docx) 출력
weasyprint	기안서 PDF 출력 (HTML → PDF)
bash
pip install flask flask-sqlalchemy pandas requests python-dotenv anthropic python-docx weasyprint

weasyprint는 시스템 라이브러리(GTK/Pango 등)가 필요할 수 있습니다. 설치가 번거로우면 pdfkit(+ wkhtmltopdf)로 대체 가능합니다.

환경 변수는 .env 파일에 설정합니다.
env
LLM_API_KEY=your_key
PREDICTHQ_API_KEY=your_key

실행 방법
bash
flask run          # 기본 포트 5000

# 코드 구조
sabuzak/
├── app/                          # Flask 웹앱 본체
│   ├── __init__.py               # create_app() 앱 팩토리 — DB/로그인 초기화, 라우트 등록
│   ├── extensions.py             # db(SQLAlchemy), login_manager 객체 선언
│   ├── models.py                 # DB 테이블 정의 (Exhibition, User, ConceptDraft, ProposalDraft)
│   ├── routes/                   # URL 하나당 함수 하나 (Flask 뷰)
│   │   ├── auth.py               # /login, /logout
│   │   ├── dashboard.py          # / (세계지도), /continent/<대륙> (목록)
│   │   ├── exhibition.py         # /exhibitions/<id> (상세 4탭)
│   │   ├── concept.py            # 부스 컨셉 생성·저장 API
│   │   ├── proposal.py           # 기안서 생성·저장·출력 API
│   │   ├── drafts.py             # /drafts (작성 중인 박람회 목록)
│   │   └── crawl.py              # /crawl/run, /crawl/status (대시보드 크롤링 버튼)
│   ├── services/                 # 라우트가 호출하는 실제 로직
│   │   ├── data.py               # raw_exhibitions 조회, 시장트렌드/HS코드/규제 데이터 가공
│   │   ├── exchange.py           # 실시간 환율 API 호출
│   │   ├── country_names.py      # 국가명 영→한 정적 매핑
│   │   ├── crawl_runner.py       # 크롤링을 백그라운드 스레드로 실행
│   │   ├── llm.py                # OpenAI로 컨셉/기안서 문구 생성
│   │   └── export.py             # 기안서 PDF/Word 출력
│   ├── templates/                # 화면 HTML (Jinja2)
│   └── static/                   # CSS/JS/이미지
│
├── scripts/                      # 웹앱과 별개로 터미널에서 실행하는 배치 스크립트
│   ├── crawl/                    # 박람회 목록 수집
│   │   ├── tradefairdates_scraper.py   # 목록 페이지 파싱 (이름/날짜/국가/참관대상)
│   │   └── sync_to_db.py               # 크롤링 결과 → DB 증분 저장
│   ├── classify/                 # AI 분류·번역
│   │   └── preprocess.py         # 대륙/food_yn/규모/키워드 분류 + intro 한국어 번역
│   └── market/                   # 무역통계·관세 데이터 (신규)
│       ├── comtrade_test1.py     # UN Comtrade — 국가별 수출액·YoY
│       ├── macmap_api.py         # macmap.org — 관세율·비관세조치(NTM)
│       └── proxy_server.py       # macmap 호출용 CORS 우회 프록시
│
├── legacy/                       # 안 쓰는 예전 버전 (참고용, 실행 안 함)
├── data/                         # 정적 참조 데이터 (CSV 등)
├── instance/
│   └── sabuzak.db                # 실제 DB 파일 (git에는 안 올라감)
├── config.py                     # DB 경로, SECRET_KEY 등 설정
├── requirements.txt              # pip 설치 목록
├── run.py                        # 앱 실행 진입점 (python run.py)
└── setup.sh                      # 설치 자동화 스크립트

# 데이터 소스
박람회 일정 — TradeFairDates
정부 지원금 — KATI(aT 농식품 수출정보), KOTRA 해외전시포털(gep.or.kr)
식품 규제 — 공공데이터포털(식품안전정보원 수출식품 부적합 사례)
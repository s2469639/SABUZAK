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
├── app/
│   ├── __init__.py
│   ├── extensions.py
│   ├── models.py
│   ├── config.py는 루트에 있음 (아래 참고)
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── exhibition.py
│   │   ├── concept.py
│   │   ├── proposal.py
│   │   ├── drafts.py
│   │   ├── mypage.py
│   │   ├── buyers.py
│   │   └── crawl.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── data.py
│   │   ├── exchange.py
│   │   ├── country_names.py
│   │   ├── crawl_runner.py
│   │   ├── llm.py
│   │   ├── export.py
│   │   ├── hscode.py
│   │   └── mailer.py
│   │
│   ├── templates/
│   │   ├── base.html                  # 공통 레이아웃 (사이드바+헤더 포함, 나머지가 다 상속)
│   │   ├── auth/
│   │   │   └── login.html             # 꼭 필요 (로그인 폼)
│   │   ├── dashboard/
│   │   │   ├── continent_map.html     # 꼭 필요 (지도)
│   │   │   └── expo_list.html         # 꼭 필요 (목록+필터)
│   │   ├── exhibition/
│   │   │   ├── detail.html            # 꼭 필요 (탭 4개를 include로 불러오는 껍데기)
│   │   │   ├── _tab_overview.html     # partial (detail.html 안에서만 쓰임)
│   │   │   ├── _tab_market.html       # partial
│   │   │   ├── _tab_trend.html        # partial
│   │   │   └── _tab_hscode.html       # partial
│   │   ├── concept/
│   │   │   └── booth_concept.html     # 꼭 필요 (별도 페이지)
│   │   ├── proposal/
│   │   │   └── proposal.html          # 꼭 필요 (기안서 작성/미리보기)
│   │   ├── drafts/
│   │   │   └── drafts_list.html       # 꼭 필요 (사이드바 눌렀을 때 뜨는 목록 페이지)
│   │   ├── mypage/
│   │   │   └── mypage.html            # 꼭 필요
│   │   └── buyers/
│   │       └── buyer_manage.html      # 꼭 필요
│   │
│   └── static/
│       ├── css/
│       │   └── style.css              # 전역 스타일 하나로 시작 (페이지별로 쪼개는 건 나중에)
│       ├── js/
│       │   └── tabs.js                # 탭 전환, 초안 저장 등 바닐라 JS
│       └── img/
│
├── scripts/
│   ├── crawl/
│   │   ├── tradefairdates_scraper.py
│   │   └── sync_to_db.py
│   ├── classify/
│   │   └── preprocess.py
│   └── market/
│       ├── comtrade_test1.py
│       ├── macmap_api.py
│       ├── proxy_server.py
│       ├── trend.py
│       ├── competitors.py
│       ├── market_research.py
│       ├── cli.py
│       └── env_setup.py
│
├── legacy/
├── data/
├── instance/
│   ├── sabuzak.db
│   └── market_research_cache.db
├── config.py
├── requirements.txt
├── run.py
└── .env(.gitignore)

# 데이터 소스
박람회 일정 — TradeFairDates
정부 지원금 — KATI(aT 농식품 수출정보), KOTRA 해외전시포털(gep.or.kr)
식품 규제 — 공공데이터포털(식품안전정보원 수출식품 부적합 사례)
# 사부작(SABUZAK) | K-전통스낵 해외 박람회 운영 자동화 대시보드

김부각·약과 등 K-전통스낵 수출기업 '사부작' 의 해외 박람회 운영 업무를 자동화하는 내부용 대시보드입니다. 해외 시장 조사, 박람회 일정 수집, 부스 컨셉 기획, 기안서 작성까지 하나의 화면에서 처리합니다.

# 화면 흐름
로그인 → 대시보드(세계 지도) → [대륙 클릭] → 대륙별 박람회 목록 → 박람회 상세
        → 부스 컨셉 기획 → 기안서 작성
        └ 작성 중인 박람회 (진행 상황 관리)

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
│   ├── __init__.py          # Flask 앱 생성 (create_app)
│   ├── routes/
│   │   ├── auth.py          # 로그인
│   │   ├── dashboard.py     # 대시보드(대륙 선택) · 대륙별 박람회 목록
│   │   ├── exhibition.py    # 박람회 상세 (개요·시장·HS코드·주의사항)
│   │   ├── concept.py       # 부스 컨셉 생성 · 수정 · 초안 저장
│   │   └── proposal.py      # 기안서 생성 · 수정 · 초안 저장 · PDF/Word 출력
│   ├── models.py            # DB 모델 (Exhibition, ConceptDraft, ProposalDraft)
│   ├── services/
│   │   ├── llm.py           # LLM API 호출 (컨셉·기안서 생성)
│   │   ├── data.py          # pandas 기반 데이터 처리
│   │   └── export.py        # PDF/Word 내보내기
│   ├── templates/
│   │   ├── base.html        # 공통 레이아웃 (사이드바)
│   │   ├── login.html
│   │   ├── dashboard.html   # 세계 지도 (대륙 클릭)
│   │   ├── continent.html   # 대륙별 박람회 목록
│   │   ├── exhibition.html  # 상세 4탭
│   │   ├── concept.html     # 부스 컨셉 기획 (수정·저장)
│   │   ├── proposal.html    # 기안서 작성 (수정·저장·출력)
│   │   └── drafts.html      # 작성 중인 박람회
│   └── static/
│       ├── css/
│       ├── js/              # 탭 전환, 초안 저장 등
│       └── img/
├── data/                    # 박람회·HS코드·규제 원본 데이터 (CSV 등)
├── config.py
├── requirements.txt
└── run.py

# 데이터 소스
박람회 일정 — TradeFairDates, 공공데이터포털(해외전시회 개최정보)
정부 지원금 — KATI(aT 농식품 수출정보), KOTRA 해외전시포털(gep.or.kr)
식품 규제 — 공공데이터포털(식품안전정보원 수출식품 부적합 사례)
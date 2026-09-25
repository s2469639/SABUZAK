# 페어메이트(FairMate)

중소 식품수출기업의 바이어 발굴을 위한 박람회 서칭 및 부스 컨셉 기획 원스탑 웹 서비스입니다. 마이페이지에서 자신의 제품(브랜드명·HS코드·원재료·인증·가격 등)을 등록하면, 해외 박람회 탐색·시장 조사·관세율/수출 규제 조회·부스 컨셉 기획·기안서 작성까지 하나의 화면에서 처리합니다.

특정 제품군(과자·스낵 등)에 고정된 서비스가 아니라, 식품 산업군에서 등록한 제품의 HS코드를 기준으로 관세율·수출 규제·시장 트렌드를 조회하는 범용 식품 수출 지원 플랫폼입니다.

# 제품 등록
사용자가 마이페이지에서 직접 제품을 등록합니다 (제품명, HS코드, 브랜드명, 제품 형태, 원재료, 보유 인증, 가격, 제품 강점).
- 엑셀(.xlsx) 업로드로 여러 제품을 한번에 등록 가능 (컬럼명만 맞으면 순서 무관)
- 체크된 제품만 시장 분석·부스 컨셉에 반영
- 국가별 세부 HS코드·관세율(FTA 협정세율 + MFN 기본세율)·수출 규제는 박람회 상세 페이지의 "HS코드 & 수출 주의사항" 탭에서 확인

# 화면 흐름
로그인 → 대시보드(세계 지도) → [대륙 클릭] → 대륙별 박람회 목록 → 박람회 상세
        → 부스 컨셉 기획 → 기안서 작성
        └ 마이페이지 (제품 등록/관리)
        └ 바이어 관리 (연락처·팔로업·메일 템플릿)
        └ 작성 중인 박람회 (진행 상황 관리)

① 대시보드 — 세계 지도에서 대륙을 클릭하면 해당 대륙의 박람회 목록 페이지로 이동 (권역: 아메리카 · 유럽 · 중동·아프리카 · 아시아 · 오세아니아)

② 대륙별 박람회 목록 — 선택한 대륙의 박람회를 목록으로 표시, 클릭 시 상세로 이동

③ 박람회 상세 — 탭으로 구성
박람회 개요 — 개최지·장소·규모·카테고리·연간 방문객·참가 기업, 공식 소개
시장 개요 — UN Comtrade 기반 교역 통계, 현재 환율
트렌드 조사 — 구글 트렌드·경쟁사·현지 뉴스 기반 시장 인사이트
HS코드 & 수출 주의사항 — 등록 제품별 HS코드·관세율(FTA 협정세율 + MFN 기본세율)·필요 인증·UNCTAD TRAINS 기반 수출 규제

④ 부스 컨셉 기획 — 상세 데이터를 기반으로 AI가 부스 테마·슬로건, 핵심 셀링포인트, 이벤트 기획안 자동 생성 → 내용 수정 및 초안 저장 가능

⑤ 기안서 작성 — 컨셉을 바탕으로 참가 기안서 자동 생성 → 내용 수정 및 초안 저장 가능, PDF·Word 출력

⑥ 마이페이지 — 제품 등록/수정/삭제, 엑셀 일괄 등록

⑦ 바이어 관리 — 바이어 연락처, 팔로업 이메일, 메일 템플릿 관리 (Gmail 연동)

# 주요 기능
- 세계 지도에서 대륙 클릭 → 대륙별 박람회 탐색, 날짜별·규모별 필터
- 마이페이지에서 제품 등록(개별/엑셀 일괄) → 등록 제품 기준으로 관세율·규제·시장 자동 조회
- 박람회별 시장·규제·HS코드 정보 자동 정리 (UN Comtrade, UNCTAD TRAINS, 관세청 FTA/MFN 관세율)
- AI 부스 컨셉 자동 생성 후 수정·초안 저장
- 기안서 자동 작성 후 수정·초안 저장, PDF/Word 내보내기
- 바이어 연락처·팔로업 메일 관리 (Gmail 연동)

# 기술 스택
Backend — Python + Flask
데이터 처리 — pandas, openpyxl(엑셀 업로드/관세율표 파싱)
Frontend — Jinja2 템플릿 + HTML/CSS + 바닐라 JS
Database — SQLite (Flask-SQLAlchemy, 바인드 2개: 기본 DB + app_data.db)
LLM — OpenAI API (시장 트렌드 키워드 추출·경쟁사 분석, 부스 컨셉·기안서 생성)

패키지 설치: `pip install -r requirements.txt`

환경 변수는 `.env` 파일에 설정합니다 (OPENAI_API_KEY, TAVILY_API_KEY, WTO_API_KEY 등 — 각 서비스 모듈 상단 주석 참고).

# 실행 방법
```
flask run          # 기본 포트 5000
```
또는 `python run.py`

# 코드 구조
```
SABUZAK/
├── app/
│   ├── __init__.py            # create_app(), 블루프린트 등록, SQLite 자동 컬럼 보정
│   ├── extensions.py
│   ├── models.py               # User, Product, Exhibition, NtmMeasure, HsCodeMaster 등
│   │
│   ├── routes/
│   │   ├── auth.py             # 로그인/회원가입
│   │   ├── dashboard.py        # 세계 지도 대시보드
│   │   ├── exhibition.py       # 박람회 상세, 시장/HS코드 탭, 관세율 동기화
│   │   ├── trend_v2.py         # 트렌드 조사 + 부스 컨셉(v15/ 로직 그대로 재사용, 3D 부스 뷰어 포함)
│   │   ├── concept.py          # 부스 컨셉 기획 (기존 시스템 - concept.py/booth_concept.py 계열, trend_v2와 별개로 유지 중)
│   │   ├── drafts.py           # 작성 중인 박람회(초안) 목록
│   │   ├── mypage.py           # 제품 등록/수정/삭제, 엑셀 일괄 등록
│   │   └── buyers.py           # 바이어 연락처/팔로업/메일템플릿/Gmail 연동 (블루프린트 여러 개)
│   │
│   ├── services/
│   │   ├── hscode.py           # 박람회 상세의 HS코드 탭 컨텍스트 조립
│   │   ├── tariff_lookup.py    # FTA 협정세율 + MFN 기본세율 조회 (scripts/market/*.csv 기반)
│   │   ├── trains_client.py    # UNCTAD TRAINS 수출 규제 조회
│   │   ├── un_comtrade.py      # UN Comtrade 교역 통계
│   │   ├── wto_client.py       # WTO 국가별 평균 관세율(참고용)
│   │   ├── kr_customs.py       # 관세청 HS코드 마스터 연동
│   │   ├── booth_concept.py    # 부스 컨셉 AI 생성 (기존 concept.py 계열)
│   │   ├── exchange.py         # 환율 조회
│   │   ├── openai_client.py    # OpenAI 클라이언트 래퍼
│   │   ├── mailer.py / mail_llm.py / mailmerge.py / google_oauth.py / attachments.py / card_scan.py
│   │   └── macmap_client.py
│   │
│   ├── prompts/, schemas/      # LLM 프롬프트 템플릿, 구조화 출력 스키마
│   │
│   ├── templates/
│   │   ├── base.html, auth_base.html
│   │   ├── auth/                (login.html, register.html)
│   │   ├── dashboard/            (continent_map.html, expo_list.html, index.html)
│   │   ├── exhibition/           (detail.html + _tab_market.html, _tab_trend.html 등 partial)
│   │   ├── concept/               (booth_concept.html)
│   │   ├── drafts/                (drafts_list.html)
│   │   ├── mypage/                (mypage.html)
│   │   └── buyers/                (buyer_manage.html, contact_form.html 등)
│   │
│   └── static/
│       ├── css/style.css, un_dashboard.css
│       ├── js/                   (tabs.js, mypage.js, dashboard.js, attach_menu.js 등)
│       └── img/
│
├── scripts/
│   ├── crawl/          # 박람회 일정 수집
│   ├── classify/        # 박람회 분류/전처리
│   └── market/          # 관세율 데이터 원천 (build_mfn_rates.py, *_FTA_협정세율_*.csv, mfn_base_rates.csv 등)
│
├── v15/                       # 트렌드 조사 + 부스 컨셉(3D 뷰어 포함) 원본 로직 (app/routes/trend_v2.py가 그대로 재사용)
├── un_v6/                    # UN Comtrade 대시보드 관련 별도 모듈
├── instance/                 # SQLite DB, 캐시 파일 (git 미포함)
├── config.py
├── requirements.txt
├── run.py
└── .env (git 미포함)
```

# 데이터 소스
박람회 일정 — TradeFairDates
정부 지원금 — KATI(aT 농식품 수출정보), KOTRA 해외전시포털(gep.or.kr)
식품 규제 — UNCTAD TRAINS
관세율 — 관세청 국가별 관세율표(FTA/MFN, `scripts/market/`), WTO Tariff Download Facility, WTO Timeseries API(국가 평균 참고용)
시장 통계 — UN Comtrade

## 크롤링 자동화 (대시보드 버튼)
대시보드의 "크롤링 새로고침" 버튼을 누르면 POST /crawl/run이 별도 스레드에서
scripts/crawl/sync_to_db.py의 크롤링·동기화 함수를 실행합니다. 브라우저는
2초 간격으로 GET /crawl/status를 조회해 진행 상태(스피너)를 표시하고,
끝나면 신규/업데이트/비활성 건수를 보여줍니다. 여러 명이 동시에 눌러도
서버에서 락으로 막아 한 번에 하나만 실행됩니다. 상세페이지(--details)까지는
버튼에서 돌리지 않으며(느림), 필요하면 아래 CLI로 별도 실행하세요.

일부 카테고리의 크롤링 자체가 실패(네트워크 오류 등)하면 그 카테고리는
"이번에 확인해봤더니 없어짐" 처리 대상에서 제외됩니다 — 안 그러면 일시적인
장애로 기존 데이터가 통째로 비활성 처리되는 사고가 날 수 있습니다.

## 데이터 파이프라인 (CLI, 앱과 분리된 배치 스크립트)
웹 요청-응답과 무관한 주기적 배치 작업은 scripts/에 따로 둡니다. 실행 순서는 아래와 같습니다.

# 1. tradefairdates.com에서 박람회 크롤링 → raw_exhibitions 테이블에 증분 동기화
#    (예전 스키마의 DB라면 첫 실행 때 데이터를 보존하며 자동으로 새 스키마로 마이그레이션됨)
python scripts/crawl/sync_to_db.py --db instance/sabuzak.db --details

# 2. OpenAI로 분류 (대륙 / food_yn / 규모 / 키워드) → 같은 DB에 바로 저장
#    아직 분류 안 됐거나, 크롤링으로 내용이 갱신된 것만 골라서 처리 (재분류 비용 절감)
python scripts/classify/preprocess.py --db instance/sabuzak.db
- scripts/crawl/tradefairdates_scraper.py — 단일 카테고리 페이지 크롤러 (다른 스크립트가 모듈로 불러다 씀). 개최기간 원문을 start_date/end_date(YYYYMMDD 숫자)로도 변환하고, p.zutritt(참관대상 원문, 예: "professional visitors only")도 함께 수집
- scripts/crawl/sync_to_db.py — 7개 카테고리 통합 크롤링 + raw_exhibitions 증분 동기화 (이름이 같아도 날짜가 바뀌면 업데이트, 목록에서 사라진 항목은 삭제 대신 비활성 처리)
- scripts/crawl/multi_crawl_gui.py — 위 크롤링을 수동으로 실행할 때 쓰는 내부용 GUI(tkinter) 도구, CSV로도 저장 가능
- scripts/classify/preprocess.py — raw_exhibitions를 직접 읽고 분류 결과를 그대로 저장(continent/food_yn/scale/keywords/intro_ko 컬럼 UPDATE, 같은 API 호출 안에서 한 번에 처리). classified_at 컬럼으로 이미 분류된 건 건너뛰고, 크롤링으로 last_updated_at이 갱신된 것만 다시 분류함. --force로 전체 재분류, --limit N으로 연습용 소량 테스트 가능. 거래고객 유형(B2B/B2C)은 별도 분류 없이 raw_exhibitions의 참관대상 원문 컬럼을 그대로 보여주는 쪽으로 대체함
- app/services/country_names.py — 국가명 영문→한글 정적 매핑(AI 호출 없음, country_ko Jinja 필터로 노출). name/city/venue는 고유명사라 번역하지 않고 원문 그대로 둠, country만 화면 표시 시 이 매핑을 거침 (매핑에 없는 국가는 원문 그대로)

legacy/classify_with_openai.py(예전 영문 컬럼, B2B/B2C 자체 분류)와 legacy/make_sample_csv.py(CSV 샘플 추출용)는 preprocess.py가 DB를 직접 읽고 쓰게 되면서 더 이상 쓰지 않습니다.

app/models.py의 Exhibition 모델은 sync_to_db.py가 채우고 preprocess.py가 분류 결과를 더하는 raw_exhibitions 테이블을 그대로 매핑해서 읽습니다.
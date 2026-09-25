# dashboard_v10 — 해외 박람회 준비 통합 대시보드

여러 폴더의 기능을 **한 화면**에 모은 대시보드입니다. 각 폴더의 코드는 수정하지 않고 그대로 불러와 씁니다.

| 섹션 | 내용 | 가져오는 곳 |
|---|---|---|
| 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링 | Google 트렌드(pytrends) 연관 검색어 → 미디어 유입·구매 의도·경쟁 인식·취식 상황 분류, 전년 대비 검색량 배지 | `trend_usp_v1` (분류·배지 단계까지만) |
| 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석 | 경쟁 제품·현지 가격(USD·원화 환산)·판매 채널·가격 전략 | `j_test/retail_research.py` (`booth_solution`은 쓰지 않음) |
| 3. 현지 웹 자료 조사 요약 | 소비자·경쟁 제품·바이어·유통·박람회·부스 4개 요약 카드. **"기사 N건 보기"를 누르면 오른쪽 사이드바**가 열리고 탭으로 질문별 근거 기사(원문·번역·출처 링크)를 봄 | `tavily_v9` (Tavily 주요 사이트 우선 검색) |
| 4. 부스 컨셉 기획 | Tavily 조사를 쓰지 않고, 입력 정보 + OpenAI 자체 조사로 기획자 초안 → 바이어 채점 → 수정. R번호를 누르면 사이드바의 "OpenAI 조사 메모" 탭이 열림 | `tavily_v9` (페르소나·스킬 문서) |

섹션 1, 2, 3·4는 **동시에** 실행되고, 하나가 실패해도 나머지는 표시됩니다(실패한 섹션은 오류 문구 표시).

## 실행

```bash
cd dashboard_v10
python -m pip install -r requirements.txt
python app.py                 # http://127.0.0.1:5060 (포트 변경: DASHBOARD_V10_PORT=5061 python app.py)
python -m unittest discover -s tests -v    # 오프라인 테스트 (네트워크 불필요)
```
`.env`(상위 `SABUZAK/.env` 공유)에 `OPENAI_API_KEY`, `TAVILY_API_KEY`가 필요합니다.

## 입력

제품명·진출 대상 국가(필수), 제품 강점·주요 원료·보유 인증·가격대, 박람회명·사이트(선택).
국가는 한국어(말레이시아)·영어(Malaysia) 모두 됩니다. 섹션마다 필요한 형식으로 자동 변환합니다
(j_test는 한국어 국가명으로 통화를 찾고, tavily_v9는 영문 국가명으로 국가·주요 사이트를 판정).

## 구조

```
dashboard_v10/
├── app.py            Flask 화면
├── pipeline.py       세 작업 동시 실행 + 사이드바용 근거 기사 묶기
├── trend_adapter.py  섹션 1(trend_usp_v1 함수 조합)·섹션 2(j_test 호출) 연결
├── country_names.py  한국어·영문 국가명 변환
└── templates/dashboard.html
```

- `trend_usp_v1`과 `tavily_v9`가 모두 `constants`라는 패키지를 가지고 있어, `trend_adapter.py`가 trend_usp를 먼저 불러온 뒤
  이름을 정리하고 `tavily_v9`를 불러옵니다. **`pipeline.py`에서 `trend_adapter`를 먼저 import하는 순서를 바꾸지 마세요.**
- `j_test/`는 전달받은 파일을 그대로 저장소에 넣은 것입니다(`retail_research.py`, `app.py`, `templates/index.html`, `requirements.txt`).
  j_test를 고치면 이 대시보드에도 그대로 반영됩니다. 예전 brotli 환경 대응을 위해 OpenAI 클라이언트만 바깥에서 바꿔 끼웁니다(원본 수정 없음).

## 비용·시간

한 번 분석할 때 세 작업이 동시에 돌아서, 가장 느린 작업(보통 섹션 3·4, 2~4분)만큼 걸립니다.
- 섹션 1: Google 요청 약 5~8회 + gpt-4o-mini 3회
- 섹션 2: gpt-4o-mini 1~2회 + Tavily 1회
- 섹션 3·4: tavily_v9와 같음 (Tavily 검색 + gpt-4o-mini, 부스 기획 gpt-4o 4~5회 + OpenAI 웹 검색)

## 한계

- 실제 API로는 검증하지 못했습니다(개발 환경 네트워크 차단). 각 폴더의 가짜 응답으로만 검증했습니다.
- 섹션 2의 가격은 j_test 로직 그대로입니다. 실측가를 못 찾으면 입력 가격대 ±15% "타깃 세그먼트 추정가"로 표시됩니다.

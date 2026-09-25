# dashboard_v10b — v10 + 상위 OpenAI 모델

v10과 화면·흐름이 **똑같고, OpenAI 모델만 바꿨습니다.** v11(Claude)과 같은 입력으로 나란히 비교하려고 만든 버전입니다.

| 역할 | v10 | v10b 기본값 | 바꾸는 법 (.env) |
|---|---|---|---|
| 4번 부스 기획 + 부스용 자체 웹 조사 | gpt-4o | **gpt-6-astra** (추론 깊이 medium) | `V10B_BOOTH_MODEL`, `V10B_BOOTH_EFFORT` |
| 1번 분류 · 2번 리테일 · 3번 발췌·요약 | gpt-4o-mini | **gpt-5.6-terra** (추론 깊이 low) | `V10B_TASK_MODEL`, `V10B_TASK_EFFORT` |

```bash
cd dashboard_v10b
python -m pip install -r requirements.txt
python app.py                 # http://127.0.0.1:5067 (v10=5065, v11=5066과 동시에 띄워 비교 가능)
python -m unittest discover -s tests -v
```
시작할 때 설정한 모델이 내 계정 목록에 있는지 확인해서 출력합니다.

## 어떻게 바꾸나 (model_upgrade.py)
각 폴더(trend_usp_v1, j_test, tavily_v9) 코드는 고치지 않고, OpenAI 클라이언트를 감싸서
- 코드에 적힌 `gpt-4o-mini` → 일반 작업 모델, `gpt-4o` → 부스 모델로 바꿔 보냅니다.
- 추론형 모델(gpt-5·gpt-6·o 시리즈)이 받지 않는 `temperature`를 빼고 추론 깊이(`reasoning_effort`)를 넣습니다.
- **모델 ID가 없거나 계정에서 막혀 있으면 자동으로 대체**합니다.
  부스: gpt-5.6-sol → gpt-5.5 → gpt-4.1 → gpt-4o / 일반 작업: gpt-5.6-luna → gpt-4.1-mini → gpt-4o-mini.
  실제로 쓰인 모델은 4번 섹션 아래에 표시됩니다.
- 모델이 특정 파라미터(예: 추론 깊이)를 거부하면 빼고 다시 보냅니다.
- 조사 결과는 v10과 따로 저장(`research_cache.db`)해서 gpt-4o로 만든 예전 결과가 섞이지 않습니다.

## 비용·시간 (추정)
- gpt-6-astra: 100만 토큰당 입력 $10 / 출력 $50 (gpt-4o의 약 4~5배). gpt-5.6-terra: $2 / $12 (gpt-4o-mini의 약 13~20배).
- 3번 섹션은 발췌·요약 호출이 많아 비용 증가가 가장 큽니다. 비용이 부담되면 `V10B_TASK_MODEL=gpt-4o-mini`로
  부스 기획만 상위 모델을 쓰세요.
- 추론형 모델이라 v10보다 느립니다(3~6분). `V10B_BOOTH_EFFORT=high`로 올리면 품질↑·시간↑.

## 한계
- 모델 ID·가격은 2026년 9월 웹 검색(OpenAI 공지·개발자 블로그)으로 확인했습니다. 공식 문서 사이트는 개발 환경에서 막혀 직접 확인하지 못했고,
  실제 API 호출도 하지 못했습니다(가짜 응답으로만 테스트). ID가 다르면 자동 대체되지만, 시작 시 출력되는 모델 확인 결과를 꼭 보세요.

---

아래는 v10 README입니다(섹션 구성·입력·구조는 그대로).

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
python app.py                 # http://127.0.0.1:5065 (포트 변경: DASHBOARD_V10_PORT=5066 python app.py)
```
5060·5061은 크롬 계열 브라우저가 전화(SIP)용 포트라 막아 두어(`ERR_UNSAFE_PORT`) 쓰지 않습니다. 포트를 바꿀 때도 이 두 번호는 피하세요.
```
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

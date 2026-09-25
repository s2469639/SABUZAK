# v12 — 페어메이트 해외 박람회 준비 통합 대시보드

**다른 폴더를 불러오지 않는 단독 폴더**입니다. trend_usp_v1·j_test·tavily_v9에서 필요한 코드만 복사해 합쳤습니다.
`.env`는 최상위 `SABUZAK/.env`를 읽습니다(`OPENAI_API_KEY`, `TAVILY_API_KEY`).

```bash
cd v12
python -m pip install -r requirements.txt
python app.py                                   # http://127.0.0.1:5068 (포트 변경: V12_PORT)
python -m unittest discover -s tests -v         # 오프라인 테스트
```

## 섹션과 사용하는 API
| 섹션 | 내용 | API |
|---|---|---|
| 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링 | 연관 검색어 → 4분류(2×2) + 전년 대비 검색량 | pytrends + OpenAI |
| 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 | 경쟁 제품·가격·채널·피칭 | OpenAI + Tavily |
| 3. 현지 시장 트렌드 분석 | 소비자·경쟁·바이어·박람회 4카드 + 근거 기사 사이드바 | Tavily + OpenAI |
| 4. 부스 컨셉 기획 | 초안 → 바이어 채점 → 수정 | **상위 OpenAI 모델만** (입력 정보 + OpenAI 자체 웹 검색, 1~3번 결과는 쓰지 않음) |

### 섹션 2 가격 찾기 (3단계)
1. Tavily로 현지 유통몰 판매가 검색 → 배지 **실측가 (Tavily)**
2. 못 찾으면 OpenAI 웹 검색 → 배지 **AI 웹 검색가** (출처 링크 표시. 모델이 적은 URL이 실제 검색 인용에 없으면 인정하지 않음)
3. 그래도 못 찾으면 입력 가격대 ±15% → 배지 **타깃 세그먼트 추정가**

가격 문구에서 숫자와 통화를 읽어 USD·원화로 환산합니다(용량 400g 같은 숫자는 제외).

## 모델 (.env로 변경)
| 변수 | 기본값 | 용도 |
|---|---|---|
| `V12_BOOTH_MODEL` / `V12_BOOTH_EFFORT` | `gpt-6-astra` / `medium` | 4번 부스 기획 + 부스용 자체 웹 조사 |
| `V12_TASK_MODEL` / `V12_TASK_EFFORT` | `gpt-5.6-terra` / `low` | 1~3번 분류·요약·가격 |

`model_upgrade.py`가 추론형 모델이 받지 않는 `temperature`를 빼고 추론 깊이를 넣습니다.
모델 ID가 없거나 계정에서 막혀 있으면 자동 대체합니다(부스: gpt-5.6-sol → gpt-5.5 → gpt-4.1 → gpt-4o,
일반: gpt-5.6-luna → gpt-4.1-mini → gpt-4o-mini). 시작할 때 모델 사용 가능 여부를 터미널에 출력합니다.

## 로딩 화면·진행률
"분석 실행"을 누르면 분석이 서버 뒤에서 돌고(`/start`), 화면이 1초마다 `/progress`로 진행률을 받아
링을 채웁니다. %는 섹션별 **실제로 끝난 단계 수**로 계산합니다(비중: 트렌드 20, 리테일 10, 시장 트렌드 45, 부스 25).
끝나면 `/result/<작업 id>`로 이동합니다. 자바스크립트가 꺼져 있으면 예전처럼 끝날 때까지 기다린 뒤 결과를 보여줍니다.
작업은 서버 메모리에 2시간 보관되므로, 서버를 다시 시작하면 진행 중이던 작업은 사라집니다.

## 저장(캐시)
`cache.db` 하나에 조사 결과(30일)·부스 기획(30일)·Google 트렌드 응답을 저장합니다. "캐시 무시하고 새로 조사"를 체크하면 새로 만듭니다.

## 파일
```
v12/
├── app.py              화면·작업 시작·진행률·결과
├── pipeline.py         네 섹션 동시 실행, 진행률, 부스 캐시
├── sections.py         섹션 1(trend_usp 조합)·섹션 2(retail_research) 연결
├── trend_usp.py        (trend_usp_v1) Google 트렌드 수집·분류
├── retail_research.py  (j_test 기반) 리테일·가격 3단계
├── research.py         (tavily_v9) Tavily 조사·요약 + 부스 기획(진행률 훅, include_booth 추가)
├── skill_loader.py, skills/booth_marketing/   부스 기획 방법·채점표
├── constants/          국가 프로필·주요 사이트·페르소나 (두 폴더의 constants를 합침)
├── model_upgrade.py, env_setup.py, http_compat.py, country_names.py
└── templates/dashboard.html, tests/
```

## 한계
- 실제 API로는 실행해 보지 못했습니다(가짜 응답 테스트 12개로 검증). 모델 ID·가격은 2026년 9월 웹 검색으로 확인했습니다.
- 섹션 2 프롬프트는 j_test 원본 그대로라 "맑은 국물 생면" 예시 기준이 들어 있습니다(면류가 아닌 제품에는 맞지 않을 수 있음).

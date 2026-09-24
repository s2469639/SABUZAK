# trend_tavily_v1 — 검색 트렌드 + 웹 자료 결합 진단 (실험 폴더)

`trend_usp_v1`(Google 트렌드 연관 검색어)과 `tavily_v5`(Tavily 웹 자료 원문 발췌)를
**동시에 실행하고, 서로의 결과를 코드로 교차 확인**했을 때 어떤 화면이 나오는지 보기 위한 폴더입니다.

- 두 폴더의 코드는 **수정하지 않고 그대로 불러와서** 씁니다 (`combined.py`의 `_load_modules`).
  원본을 고치면 이 폴더에도 그대로 반영됩니다.
- 교차 확인은 추가 API 호출 없이 **코드로만** 합니다.

## 실행

```bash
pip install -r requirements.txt
# .env (상위 SABUZAK/.env 공유)에 OPENAI_API_KEY, TAVILY_API_KEY 필요
python app.py                   # http://127.0.0.1:5090  (포트 변경: TREND_TAVILY_PORT=5091 python app.py)
python cli.py --name 약과 --country 미국 --strengths "손에 안 묻는 식감" --exhibition "Summer Fancy Food Show"
python -m unittest discover -s tests -v   # 오프라인 테스트 (네트워크 불필요)
```

## 결합 방식

| 무엇을 | 어떻게 | 화면 |
|---|---|---|
| 동시 실행 | 두 분석을 병렬 실행. 한쪽이 실패해도 다른 쪽 결과는 표시 | 상단 경고 |
| 경쟁 제품 교차 확인 | trend가 찾은 경쟁 제품 이름(name, search_term)이 Tavily 발췌 **원문**에 단어 단위로 등장하면 연결 | USP 표 "웹 출처" 열 (원문·번역·링크) |
| 가격 교차 확인 | 연결된 발췌에 가격 표현이 있으면 표시. AI 추정 가격의 **금액**이 원문 금액과 같으면 "웹 출처와 일치" | USP 표 가격 칸 |
| 바이어 체크포인트 | Tavily Q3(바이어·유통)에 근거 있는 포인트가 있으면 그것을 쓰고, 없으면 trend의 AI 참고 체크포인트 | 피칭 월 카드 |
| 소비자·경쟁·박람회 | Tavily Q1·Q2·Q4 카드 포인트(출처 링크 포함)를 관련 섹션 아래에 붙임 | 웹 자료 패널 |
| 부스 | Tavily 부스 핵심 메시지·근거를 trend 부스 카드 아래에 붙임 | 웹 자료 기반 부스 포인트 |

상단 요약 카드: USP 경쟁 제품 중 웹 출처로도 확인된 수, 경쟁 후보 웹 확인 수, 웹 발췌 수(대상 국가), 근거가 있는 웹 자료 질문 수.

## 알려진 한계

- **실제 API로는 검증하지 못했습니다** (개발 환경에서 Google·OpenAI·Tavily 접속 차단). 가짜 응답으로만 검증했습니다.
- 소요 시간: 두 분석을 병렬로 돌려도 느린 쪽(보통 트렌드 2~3분)만큼 걸립니다. Tavily 크레딧도 함께 소모됩니다.
- 경쟁 제품 연결은 이름 문자열 일치라서, 발췌가 브랜드를 다르게 표기하면(예: 약칭) 연결되지 않습니다.
- `tavily_v5`는 영문 국가명으로 국가·권역을 판정하므로, trend 국가 프로필의 영문 별칭(United States 등)으로 바꿔서 넘깁니다.

# v13 — 페어메이트 트렌드 조사 탭 & 부스 컨셉 기획 (분리 버전)

v12를 바탕으로 **트렌드 조사(1~3번)**와 **부스 컨셉(4번)**을 서로 다른 작업·화면으로 나눈 단독 폴더입니다.
사부작 메인 웹의 "트렌드 조사" 탭과 "부스 컨셉 기획" 버튼 페이지에 대응합니다.
`.env`는 최상위 `SABUZAK/.env`를 읽습니다(`OPENAI_API_KEY`, `TAVILY_API_KEY`).

```bash
cd v13
python -m pip install -r requirements.txt
python app.py                                   # http://127.0.0.1:5069 (포트 변경: V13_PORT)
python -m unittest discover -s tests -v         # 오프라인 테스트
```

## 화면
| 주소 | 내용 |
|---|---|
| `/` → `/trend/<id>` | 트렌드 조사: 1. 검색 트렌드 4단계 클러스터링 · 2. 리테일 벤치마킹 & 가격 · 3. 현지 시장 트렌드 분석. 오른쪽 위 주황색 **부스 컨셉 기획 →** 버튼 |
| `/booth/<id>` | 부스 컨셉: Executive Summary(빅 아이디어·슬로건·Key Actions·KPI) · 전략 근거 · Execution Plan 탭 · Visitor Journey 탭 · 운영 리스크 점검/추가 확인 요청 사항 체크리스트 |
| `/booth` | 부스 컨셉만 따로 실행 (쿼리 문자열로 입력값 미리 채우기 가능) |

- 트렌드 조사를 시작하면 **부스 기획도 뒤에서 함께 시작**합니다. 버튼을 누를 때 대부분 이미 끝나 있고, 아직이면 로딩 화면에서 이어서 기다립니다.
- 로딩 화면: 진행률 링(%) + 지금 하는 일(쉬운 문구, 도구 이름 없음) + 진행 라벨(진행 중 파랑 ● / 완료 초록 ✓) + 슬로건.
- 부스 페이지 **근거 표시** 스위치: 켜면 문장마다 근거(R번호 = 조사 메모, 기업 = 입력 정보, 기획 제안 = 아이디어)가 보입니다. 설정과 체크리스트 체크 상태는 브라우저에 기억됩니다.

## JSON API (메인 웹 연동용)
| 요청 | 응답 |
|---|---|
| `POST /api/trend/start` (입력값 form 또는 JSON) | `{job_id, booth_job_id}` |
| `POST /api/booth/start` | `{job_id}` |
| `GET /api/<trend|booth>/<id>/progress` | `{status, percent, message, chips, error}` |
| `GET /api/<trend|booth>/<id>` | `{status, error, result}` |

입력값: `name`, `country`(필수), `strengths`, `ingredients`, `certifications`, `price`, `exhibition_name`, `exhibition_website`, `force`.

## 데이터 저장
- 끝난 작업의 전체 결과(화면에 없는 바이어 채점·검토 의견 포함)는 `results/<trend|booth>_<id>.json`에 저장합니다. 화면에는 표시하지 않습니다.
- `cache.db`: 조사 결과·부스 기획(30일)·Google 트렌드 응답 캐시.

## v12에서 달라진 점
- 1~3번과 4번 분리 (`services.py`의 `run_trend` / `run_booth`, 작업·진행률은 `jobs.py`)
- 섹션 1: 안내 배너 아이콘을 `i` 기호로
- 섹션 2: 라벨 위·내용 아래 구성, 스펙 칩, 소비자 페인 포인트 박스, 큰 가격, 바이어 피칭 인용 박스
- 섹션 4: 라벨·안내문·바이어 채점표·원본 데이터 제거, Executive Summary / Execution Plan / Visitor Journey 구성
- 부스 기획 AI 출력에 `key_actions`(3개)와 단계별 Visitor Journey(`headline·goal·visitor·staff·props·message`) 추가
- 로딩 문구를 사용자용 쉬운 문구로 (`jobs.FRIENDLY`)

## 모델
v12와 같습니다: 부스 `gpt-6-astra`(V13에서도 `.env`의 `V12_BOOTH_MODEL`/`V12_BOOTH_EFFORT`로 변경), 나머지 `gpt-5.6-terra`(`V12_TASK_MODEL`).

## 한계
- 실제 API로는 실행해 보지 못했습니다(가짜 응답 테스트 18개로 검증).
- 작업 상태는 서버 메모리에 2시간 보관합니다. 서버를 다시 시작하면 진행 중이던 작업과 결과 화면 주소는 사라집니다(파일로 저장한 결과는 남음).

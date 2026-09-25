# dashboard_v11 — 해외 박람회 준비 통합 대시보드 (Claude 마케팅 에이전트)

v10과 같은 한 화면 대시보드입니다. 달라진 점은 **4번 부스 컨셉 기획을 OpenAI 대신 Claude API가 맡는다**는 것입니다.
Claude 마케팅 플러그인의 `/marketing:competitive-brief`처럼, 먼저 경쟁사를 조사해 빈틈을 찾고 그 빈틈을 부스 전략으로 연결합니다.

| 섹션 | 내용 | 가져오는 곳 |
|---|---|---|
| 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링 | Google 트렌드 연관 검색어 분류, 전년 대비 검색량 배지 | `trend_usp_v1` (v10과 같음) |
| 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석 | 경쟁 제품·현지 가격·판매 채널·가격 전략 | `j_test` (v10과 같음) |
| 3. 현지 웹 자료 조사 요약 | 4개 요약 카드 + 오른쪽 사이드바 근거 기사 | `tavily_v9` (**OpenAI 부스 기획은 건너뜀**) |
| 4. 부스 컨셉 기획 | **Claude 마케팅 에이전트**: 경쟁 브리프 → 기획 → 바이어 채점 → 수정 | `claude_booth.py` (새로 만듦) |

네 섹션은 동시에 실행되고, 하나가 실패해도 나머지는 표시됩니다.

## 실행

```bash
cd dashboard_v11
python -m pip install -r requirements.txt        # anthropic 패키지가 새로 필요
python app.py                                    # http://127.0.0.1:5066 (포트 변경: DASHBOARD_V11_PORT=5067)
python -m unittest discover -s tests -v          # 오프라인 테스트
```
`.env`(상위 `SABUZAK/.env` 공유)에 `OPENAI_API_KEY`, `TAVILY_API_KEY`에 더해 **`ANTHROPIC_API_KEY`**가 필요합니다.
없으면 시작할 때 물어보고 `.env`에 저장할 수 있습니다. 키는 https://console.anthropic.com 에서 발급합니다.
Claude 웹 검색을 쓰려면 Console의 조직 설정에서 **web search가 켜져 있어야** 합니다(꺼져 있으면 자동으로 모델 지식만으로 조사).

## 4번 섹션: Claude 마케팅 에이전트 흐름

```
사용자 입력 (제품·국가·박람회·강점·원료·인증·가격)
  │
  ① 경쟁 브리프  ── Claude + 웹 검색(web_search 서버 도구, 대상 국가 위치 지정)
  │               경쟁사 파악 → 경쟁사별 프로필 → 메시지 비교 → 포지셔닝 빈틈 → 이기는 방법 + 조사 메모(R번호)
  ② 기획자 초안  ── 빈틈을 빅 아이디어로: 전략 뼈대(인사이트·타깃 바이어·빅 아이디어·RTB) + 6개 실행 항목·동선·KPI
  ③ 바이어 채점  ── 미국 대형 유통 MD 페르소나가 채점표 6개 항목을 1~5점 채점
  ④ 수정         ── 4점 미만 항목이 있을 때만 고침 (모두 4점 이상이면 생략)
```
- Tavily 조사(3번)는 부스 기획에 넘기지 않습니다(v9·v10과 같은 원칙). Claude가 스스로 조사합니다.
- 화면에는 경쟁 브리프(경쟁 제품 표, 빈틈, 경쟁사가 다 하는 말, 우리만의 증명 포인트, 바이어 반론 대응)가 부스 컨셉 위에 추가됩니다.
- R번호를 누르면 사이드바의 "Claude 조사 메모" 탭이 열립니다. 메모마다 출처 상태를 표시합니다:
  `웹 출처`(실제 검색 결과에 있는 URL) · `출처 미확인`(Claude가 적은 URL이 검색 결과에 없음) · `AI 지식`.
- 결과는 `booth_cache.db`에 30일간 저장됩니다. "캐시 무시하고 새로 조사"를 체크하면 다시 만듭니다.

### 스킬 문서 (시스템 프롬프트)
- `skills/competitive_brief/SKILL.md` — `/marketing:competitive-brief` 방법론을 박람회 부스용으로 옮긴 문서(한국어).
  Claude Code 플러그인 스킬은 API에서 직접 부를 수 없어서, 같은 방법을 문서로 만들어 시스템 프롬프트에 넣었습니다.
- 실제 플러그인 스킬 문서가 있으면 `skills/<폴더명>/SKILL.md`(+ 참고 `*.md`)로 넣고 `CLAUDE_AGENT_SKILL=<폴더명>`으로 바꿔 쓸 수 있습니다.
- 부스 기획 방법·채점표는 `tavily_v9/skills/booth_marketing/`을 그대로 씁니다.

### Claude API 설정
| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `CLAUDE_BOOTH_MODEL` | `claude-opus-5` | 모델 |
| `CLAUDE_BOOTH_EFFORT` | `high` | 조사·기획·수정의 사고 깊이 (`low`/`medium`/`high`/`xhigh`/`max`) |
| `CLAUDE_REVIEW_EFFORT` | `medium` | 채점 단계 |
| `CLAUDE_WEB_SEARCH` | `1` | `0`이면 웹 검색 없이 모델 지식만 |
| `CLAUDE_WEB_SEARCH_MAX_USES` | `8` | 조사 한 번에 쓰는 최대 검색 횟수 |
| `CLAUDE_FALLBACKS` | `1` | 서버 측 대체 모델. Claude가 안전 분류기로 요청을 거절하면 같은 호출 안에서 권장 대체 모델로 다시 실행 |
| `CLAUDE_REVISE_BELOW` | `4` | 이 점수 미만 항목이 있으면 수정 |

적응형 사고(adaptive thinking), 스트리밍, 시스템 프롬프트 캐시를 씁니다. 웹 검색이 길어져 중간에 멈추면(`pause_turn`) 자동으로 이어서 진행합니다.
대체 모델이 쓰이면 화면에 "대체 모델 사용" 표시가 나옵니다.

## 비용·시간

- 섹션 4: Claude 호출 3~4회(+ pause_turn 이어가기) + 웹 검색 최대 8회. 보통 2~5분. `claude-opus-5`($5·$25 / 100만 토큰) 기준 1회 분석에 대략 1~3달러 안팎(추정, 웹 검색은 1,000회당 10달러 별도)
  (입력 길이·검색 횟수에 따라 다름). 비용을 줄이려면 `CLAUDE_BOOTH_EFFORT=medium`, `CLAUDE_WEB_SEARCH_MAX_USES=4`.
- 섹션 1·2·3: v10과 같음. 3번은 OpenAI 부스 기획(gpt-4o 4~5회)을 건너뛰어 v10보다 저렴합니다.
- 화면의 부스 섹션 아래에 모델·effort·웹 검색 횟수가 표시되고, 원본 JSON의 `booth.usage`에서 토큰 수를 볼 수 있습니다.

## 한계

- 실제 Claude API로는 검증하지 못했습니다(개발 환경에 키 없음). 가짜 Anthropic 응답으로 흐름을 테스트했고,
  실제 SDK(anthropic 1.8)가 만드는 요청 형식(헤더·파라미터·pause_turn 이어가기)은 가짜 HTTP 서버로 확인했습니다.
- 섹션 1·2·3은 여전히 OpenAI(gpt-4o-mini)를 씁니다.

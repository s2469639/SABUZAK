# trend_usp_v1 — 연관 검색어 기반 시장 트렌드 · USP · 부스 컨셉 진단 (독립 실행 폴더)

한국 수출기업이 제품 스펙(한국어)과 진출 국가를 입력하면,
**현지 소비자가 현지 언어로 검색한 Google 연관 검색어**를 수집해
① 4단계 클러스터링 ② 경쟁 대체재 대비 USP 매트릭스 ③ 박람회 부스 컨셉을 **한국어로** 제공합니다.

> 원칙: 수집은 현지 소비자의 언어로, 분석·전달은 한국어로.
> (단, 부스 슬로건·바이어 피칭 문구는 바이어 언어 원문 + 한국어 번역)

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env            # OPENAI_API_KEY 입력 (상위 SABUZAK/.env 공유도 가능)
python app.py                   # http://127.0.0.1:5080
python cli.py --name 김밥 --country 일본 --strengths "냉동 후에도 밥이 굳지 않음" --certifications HACCP
python cli.py --name 약과 --country 미국 --json   # 전체 JSON
python -m unittest discover -s tests -v          # 오프라인 테스트 (네트워크 불필요)
```

포트: Flask `:5080` (`TREND_USP_PORT`로 변경 가능)

## 파이프라인

| 단계 | 처리 | 주체 |
|---|---|---|
| ⓪ 국가 프로필 | `constants/country_profiles.py` (35개국: ISO 코드, 검색 언어, 바이어 언어, Google 신뢰도). 없는 국가는 LLM 추정 | 코드 |
| ① 시드 검색어 | 현지어·현지 문자 + 로마자/영문 표기 최대 3개, 상위 카테고리 1개 | LLM |
| ② 연관 검색어 수집 | pytrends `related_queries` (최근 12개월). 부족하면 `seed@국가 → category@국가 → seed@글로벌` 순으로 확장 | 코드 |
| ③ 전처리 | 중복 병합, 시드 제외, 급상승 우선 정렬, Breakout(+5000%↑) 표시, 최대 25개 | 코드 |
| ④ 4단계 분류 | Culture Trigger / Intent Funnel(인지·탐색·구매 전환) / Perception / Habit & TPO + 제외. 번호로만 참조 → 목록에 없는 검색어는 폐기 | LLM + 코드 검증 |
| ⑤ 배지 수치 | 5년 주간 시계열에서 **최근 13주 평균 vs 1년 전 같은 13주 평균 (YoY)**. 기저가 작으면 "데이터 부족" | 코드 |
| ⑥ USP·부스 | 입력 스펙만 근거로 USP 작성, 근거 항목 표시. 입력하지 않은 인증이 문구에 나오면 경고 | LLM + 코드 검증 |

- Google 트렌드가 완전히 실패하면 LLM이 검색어를 추정하고 화면에 **"AI 추정"**으로 표시합니다 (수치 배지 없음).
- 중국·러시아처럼 Google 점유율이 낮은 국가는 결과 상단에 신뢰도 경고가 고정됩니다.
- pytrends 응답은 `.cache/`에 24시간 캐시됩니다. 화면의 "캐시 무시" 또는 `--force`로 새로 조회.

## 알려진 한계

- **실제 Google Trends / OpenAI 응답으로는 아직 검증하지 않았습니다.** 개발 환경의 네트워크가
  두 서비스를 차단해 가짜 응답(`tests/test_offline.py`)으로만 검증했습니다. 처음 실행 시
  `python cli.py ... --debug`로 로그를 확인해 주세요.
- pytrends는 비공식 라이브러리라 429(요청 과다)가 잦습니다. 한 번 분석에 Google 요청이 약 3~8회 발생합니다.
- Google 트렌드 수치는 절대 검색량이 아니라 0~100 상대 지수입니다.

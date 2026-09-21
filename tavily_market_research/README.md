# tavily_market_research — 시장·트렌드 조사 (독립 실행 폴더)

제품명 + 국가를 입력하면 Tavily로 최근 시장 트렌드를 검색하고 한국어로
요약해주는 기능입니다. HS코드 추천 기능은 여기 없습니다 (별도 폴더
`hscode_recommend`에 완전히 분리되어 있습니다).

## ⚠️ 먼저 확인하세요

이전 저장소 사고로 키가 노출됐을 수 있다면, 키를 재발급(revoke 후 재발급)
받으세요.
- https://platform.openai.com/api-keys
- https://app.tavily.com

## 설치

```bash
python -m venv .venv
source .venv/bin/activate        # Windows(cmd): .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env를 열어서 OPENAI_API_KEY, TAVILY_API_KEY를 채워넣으세요
# (안 채워도 됩니다 - 실행할 때 터미널에서 직접 물어봅니다)
```

## 실행

**웹 화면:**
```bash
python app.py
```
브라우저에서 http://127.0.0.1:5050 접속

**터미널:**
```bash
python cli.py --product 김부각 --country "United States"
```

## 기능

1. 제품명 + 국가 입력
2. 제품명 기반 검색 키워드 5개 생성 (OpenAI)
3. Tavily로 국가별 최신 뉴스 검색 (클릭 가능한 출처 링크 포함)
4. 검색 결과를 한국어로 요약

결과는 `market_research_cache.db`(SQLite)에 30일간 캐싱됩니다.

## 파일 구조

```
tavily_market_research/
├── app.py                  # Flask 웹 화면
├── cli.py                  # 터미널 CLI
├── market_research.py      # 핵심 로직 (키워드 생성, Tavily 검색, 한국어 요약)
├── env_setup.py            # API 키 확인/입력 도우미
├── templates/
│   └── market_research.html
├── requirements.txt
├── .env.example
└── .gitignore
```

# hscode_recommend — HS코드 후보 추천 (독립 실행 폴더)

제품명만 주면 OpenAI가 HS코드 후보를 추천합니다. 시장·트렌드 조사
기능(`tavily_market_research` 폴더)과는 완전히 별개이며, Tavily 키는
필요 없고 OpenAI 키만 있으면 됩니다.

## ⚠️ 먼저 확인하세요

이전 저장소 사고로 키가 노출됐을 수 있다면, 키를 재발급(revoke 후 재발급)
받으세요. https://platform.openai.com/api-keys

## 설치

```bash
python -m venv .venv
source .venv/bin/activate        # Windows(cmd): .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env를 열어서 OPENAI_API_KEY를 채워넣으세요
# (안 채워도 됩니다 - 실행할 때 터미널에서 직접 물어봅니다)
```

## 실행 (단독 테스트)

```bash
python hscode_cli.py --product 김부각
python hscode_cli.py --product "이상한 신제품"
```

## 다른 페이지에 삽입하는 법

이 폴더의 파일들을 여러분의 다른 프로젝트/페이지 코드가 있는 곳에 복사해서
(`hscode_recommend.py`, `hscode_lookup.py`, `hscode_items.py`, 그리고
원하면 `build_hscode_lookup.py`) 아래처럼 가져다 쓰면 됩니다:

```python
from hscode_recommend import get_openai_client, recommend_hscodes

client = get_openai_client()
candidates = recommend_hscodes(client, "김부각")
# [{"hscode": "190590", "reason": "...",
#   "confidence": "확정" | "높음" | "중간" | "낮음",
#   "verified": True/False, "official_name": "..." 또는 None}, ...]
```

화면에는 항상 **"AI 추정이니 실제 신고 시에는 관세사 또는 관세청 품목분류
사전심사로 재확인하세요"** 안내를 같이 보여주세요 (HS코드 오분류는 실제
관세/법적 문제로 이어질 수 있습니다).

## 동작 방식

1. 제품명이 사부작 등록 품목(`hscode_items.py`)과 일치하면 그 코드를
   "확정"으로 표시
2. 그와 무관하게 OpenAI에게도 항상 다른 가능성을 물어봄 (같은 제품도
   분류 기준에 따라 여러 HS코드에 걸칠 수 있어서 — 예: 김부각이 해조류
   분류로도, 조제식료품 분류로도 갈 수 있음)
3. 각 후보를 관세청 공식 데이터(`hscode_master.db`, 있으면)로 대조해서
   실제로 존재하는 코드인지 검증 — LLM이 그럴듯한 가짜 코드를 지어내도
   그대로 "확인됨"처럼 보여주지 않기 위함

## 검증 범위 넓히기 (선택)

지금은 `hscode_items.py`에 사부작 취급 품목 3개(5개 제품)만 등록되어
있어서, 그 외 코드는 전부 "⚠️ 공식 DB 미확인"으로만 나옵니다. 관세청
공식 데이터 전체(1만 개+)로 검증 범위를 넓히려면:

1. https://www.data.go.kr/data/15049722/fileData.do 에서 로그인 후
   "관세청_HS부호" 파일(xlsx) 다운로드 (활용신청 승인 불필요)
2. `python build_hscode_lookup.py --file 받은파일.xlsx`

## 파일 구조

```
hscode_recommend/
├── hscode_recommend.py      # 핵심 로직 (공개 함수: recommend_hscodes)
├── hscode_lookup.py         # HS코드 <-> 제품명 조회
├── hscode_items.py          # 사부작 등록 품목 매핑
├── hscode_cli.py            # 단독 테스트용 CLI
├── build_hscode_lookup.py   # 관세청 공식 데이터 가져오는 배치 스크립트
├── env_setup.py             # API 키 확인/입력 도우미
├── requirements.txt
├── .env.example
└── .gitignore
```

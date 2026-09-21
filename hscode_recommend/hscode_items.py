"""HS코드 -> 품목명 참고 매핑 (사부작 자체 취급 품목 seed 데이터).

AI 호출 없이 쓰는 순수 조회용 딕셔너리. 하나의 HS코드에 여러 품목이
걸릴 수 있어(예: 190590 = 김부각/유과/약과 전부 여기 해당) 값은 리스트로 둔다.

매핑에 없는 제품명은 find_registered_hscode()가 None을 반환하고,
market_research.py가 LLM에게 HS코드 추천을 맡긴다.

다른 식품회사까지 대상을 넓히려면(수만 건 규모의 전체 HS코드가 필요해지면):
    1) data.go.kr에서 "관세청_HS부호" 데이터셋 확인
       https://www.data.go.kr/data/15049722/fileData.do
    2) build_hscode_lookup.py로 내려받은 파일을 hscode_master 테이블에 넣기
"""

HSCODE_ITEMS = {
    "190590": ["김부각", "유과", "약과"],
    "190490": ["누룽지칩"],
    "200599": ["고구마스틱"],
}

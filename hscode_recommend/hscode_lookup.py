"""HS코드 <-> 품목명 조회.

get_product_name(): HS코드 -> 품목명 (hscode_items.py 우선 + hscode_master 보완)
find_registered_hscode(): 제품명 -> 사부작 등록 HS코드 (역방향 조회)

hscode_master 테이블을 채우려면:
    1) https://www.data.go.kr/data/15049722/fileData.do 에서 로그인 후
       "관세청_HS부호" 파일(xlsx)을 내려받는다 (활용신청 승인 필요 없음)
    2) python build_hscode_lookup.py --file <받은 파일 경로>
"""

import sqlite3

from hscode_items import HSCODE_ITEMS


def get_product_name(hscode: str, conn: sqlite3.Connection | None = None) -> str | None:
    """HS코드 -> 품목명. conn이 주어지면 hscode_master 테이블도 함께 조회한다.
    사부작 자체 매핑과 관세청 공식명이 둘 다 있으면 합쳐서 보여준다."""
    local_names = HSCODE_ITEMS.get(hscode)
    local = ", ".join(local_names) if local_names else None

    official = None
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT name_ko FROM hscode_master WHERE hscode=?", (hscode,)
            ).fetchone()
            if row and row[0]:
                official = row[0]
        except sqlite3.OperationalError:
            pass  # hscode_master 테이블이 아직 없음 (build_hscode_lookup.py 실행 전)

    if local and official:
        return f"{local} (관세청 공식명: {official})"
    return local or official


def find_registered_hscode(product_name: str) -> dict | None:
    """제품명 -> 사부작이 이미 등록해둔 HS코드 (역방향 조회).
    market_research.recommend_hscodes()가 LLM 추천 결과에 이 정보를 합쳐서
    등록된 코드는 "확정"으로 표시하는 데 쓴다."""
    target = product_name.strip()
    if not target:
        return None
    for hscode, names in HSCODE_ITEMS.items():
        if any(target == n or target in n or n in target for n in names):
            return {"hscode": hscode, "names": ", ".join(names)}
    return None

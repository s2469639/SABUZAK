"""한국 관세청(data.go.kr) 수출입실적 오픈API 연동 - 한국이 직접 신고한 수출입 통계.

un_comtrade.py(UN Comtrade, "상대국이 한국으로부터 수입했다고 UN에 보고한" 미러
통계)와는 완전히 독립된 모듈이다. 일부러 별도 파일로 분리했다: 이 둘을 하나로
합쳐서 "평균값"처럼 섞어버리면, 두 출처가 원래 다른 기준(관세청은 한국이 직접
신고한 수출액, UN Comtrade는 상대국이 보고한 수입액)으로 집계된다는 사실이
화면에서 사라져버리기 때문이다. app.py에서 두 모듈의 결과를 각각 받아서
[UN Comtrade 통계] / [관세청 공식 자료]로 라벨을 분리해 나란히 보여준다 -
AI에게도 "두 수치가 다르면 어느 게 맞는지 판단하지 말라"고 명시해서 섞지 않는다.

⚠️ 검증 상태 - 꼭 읽어주세요:
    data.go.kr의 "관세청_품목별 수출입실적(GW)", "관세청_품목별 국가별
    수출입실적(GW)" 두 오픈API를 대상으로 짰다. 이 코드는 공공데이터포털에
    등록된 API 대부분이 따르는 "공공데이터 개방 표준" 응답 형식
    (response.header.resultCode / response.body.items.item ...)을 기준으로
    가정한 것이고, 이 두 API의 실제 응답을 직접 받아본 적은 없다. 특히:
        - 요청 URL(Endpoint) 자체를 모른다 -> .env에 직접 넣게 했다
          (활용신청 승인 화면의 "요청 URL" 그대로 복사해서 CUSTOMS_ITEM_API_URL /
          CUSTOMS_ITEM_COUNTRY_API_URL에 붙여넣으면 된다)
        - 요청 파라미터 이름 (hsSgn, startYyyyMm 등은 추정)
        - 응답 필드 이름 (expDlrAmt, cntyCd 등은 추정, 여러 후보를 같이 찾아봄)
    customs_cli.py --debug로 원본 응답을 그대로 찍을 수 있다. 실제 필드명이
    다르면 그 목록을 알려주면 바로 고쳐줄 수 있다.

국가 매칭에 대해:
    "품목별 국가별" API를 국가 필터 없이 호출하면(country_code=None) 전체
    국가가 응답에 다 들어있을 것으로 가정한다. 그러면 이 응답 자체가 곧
    "국가명 -> 관세청 국가코드" 매핑표 역할을 하므로, UN Comtrade 때처럼
    ISO3나 AI 추천 같은 별도의 코드 변환 로직이 필요 없다. 그냥 응답에 있는
    국가명(한글/영문)과 사용자가 입력한 국가명을 문자열로 대조하면 된다.
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "customs_trade_cache.db")
CACHE_TTL_DAYS = 25  # 관세청은 매월 15일경 전월 자료를 갱신한다고 알려져 있어, UN Comtrade(30일)보다 살짝 촘촘하게 잡음
HSCODE_RE = re.compile(r"^\d{6}$")  # UN Comtrade 쪽과 비교하기 쉽도록 우리는 6자리로 통일해서 받는다

EXP_AMT_CANDIDATES = ["expDlrAmt", "expAmt", "exportAmt", "expUsd", "expDlr"]
IMP_AMT_CANDIDATES = ["impDlrAmt", "impAmt", "importAmt", "impUsd", "impDlr"]
YM_CANDIDATES = ["year", "baseYm", "statYymm", "yyyymm", "period", "statKor"]
COUNTRY_CODE_CANDIDATES = ["cntyCd", "natCd", "countryCode", "cntCd"]
COUNTRY_NAME_KO_CANDIDATES = ["cntyKorNm", "natKorNm", "countryName", "cntyNm", "korNm"]
COUNTRY_NAME_EN_CANDIDATES = ["cntyEnNm", "natEngNm", "countryNameEn", "engNm"]


def _locate_env_file():
    """.env를 최상위 프로젝트 폴더(이 폴더의 부모 디렉터리, 예: SABUZAK/)에서
    먼저 찾는다 - 여러 도구 폴더가 .env 하나를 공유하는 구조로 바뀌었기 때문.
    이 폴더 안에 .env를 따로 둔 경우(예전 방식)도 계속 지원한다."""
    parent_env = os.path.join(os.path.dirname(BASE_DIR), ".env")
    if os.path.exists(parent_env):
        return parent_env
    local_env = os.path.join(BASE_DIR, ".env")
    if os.path.exists(local_env):
        return local_env
    return parent_env


def get_config():
    """data.go.kr 인증키를 준비한다. 없으면 RuntimeError.
    이 모듈 전체가 선택 기능이라, 키가 없으면 이 함수를 부르는 쪽(app.py)이
    그냥 이 섹션을 건너뛰면 된다 - UN Comtrade 핵심 기능은 이 키 없이도 그대로 동작해야 한다."""
    load_dotenv(_locate_env_file())
    api_key = os.getenv("DATA_GO_KR_API_KEY")
    if not api_key:
        raise RuntimeError(
            "DATA_GO_KR_API_KEY가 설정되어 있지 않습니다 (.env 확인). "
            "data.go.kr에서 '관세청_품목별 수출입실적(GW)'과 '관세청_품목별 "
            "국가별 수출입실적(GW)' 을 활용신청하면 발급됩니다 (계정당 인증키 1개를 공유해서 씀)."
        )
    return api_key


def _get_endpoint(env_name):
    url = os.getenv(env_name)
    if not url:
        raise RuntimeError(
            f"{env_name}가 .env에 없습니다. data.go.kr 활용신청 승인 화면에 나오는 "
            "'요청 URL(Endpoint)'을 그대로 복사해서 .env에 붙여넣어주세요. "
            "(이 URL은 데이터셋마다 다르고, 저는 실제로 확인해본 적이 없어서 기본값을 넣어두지 않았습니다.)"
        )
    return url


def _request(url, api_key, params, proxy_url=None):
    """공공데이터포털 공통 응답 형식(response.header/body.items.item)을 가정하고 파싱한다.
    결과가 1건일 때 items.item이 리스트가 아니라 dict 하나로 오는 경우가 흔해서 방어적으로 처리한다."""
    query = {"serviceKey": api_key, "type": "json", **params}
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    resp = requests.get(url, params=query, timeout=20, proxies=proxies)
    resp.raise_for_status()
    data = resp.json()

    header = data.get("response", {}).get("header", {})
    result_code = header.get("resultCode")
    if result_code not in (None, "00", "0"):
        raise RuntimeError(f"관세청 API 오류 응답: {result_code} {header.get('resultMsg')}")

    body = data.get("response", {}).get("body", {})
    items = body.get("items")
    if items is None:
        return []
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items or []


def _find_field(item, candidates, label):
    for c in candidates:
        if c in item:
            return item[c]
    lowered = {k.lower(): k for k in item.keys()}
    for c in candidates:
        if c.lower() in lowered:
            return item[lowered[c.lower()]]
    raise RuntimeError(
        f"{label} 필드를 찾지 못했습니다. 실제 응답 필드: {list(item.keys())} "
        f"(찾던 이름: {candidates}) -- 이 목록을 알려주시면 코드를 맞춰드릴게요."
    )


def _find_field_optional(item, candidates):
    try:
        return _find_field(item, candidates, "")
    except RuntimeError:
        return None


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_item_trade_stats(hscode, start_ym, end_ym, proxy_url=None):
    """[1단계] 한국이 직접 신고한 이 HS코드의 월별 수출입 실적 (국가 구분 없음, 전세계 합계).
    start_ym/end_ym은 "YYYYMM" 문자열."""
    api_key = get_config()
    url = _get_endpoint("CUSTOMS_ITEM_API_URL")
    items = _request(
        url, api_key,
        {"hsSgn": hscode, "startYyyyMm": start_ym, "endYyyyMm": end_ym, "numOfRows": 999},
        proxy_url=proxy_url,
    )

    by_month = []
    for item in items:
        ym = _find_field(item, YM_CANDIDATES, "기준연월")
        by_month.append({
            "year_month": str(ym),
            "export_usd": _to_float(_find_field_optional(item, EXP_AMT_CANDIDATES)),
            "import_usd": _to_float(_find_field_optional(item, IMP_AMT_CANDIDATES)),
        })
    by_month.sort(key=lambda x: x["year_month"])
    return {"hscode": hscode, "by_month": by_month}


def get_item_country_trade_stats(hscode, start_ym, end_ym, proxy_url=None):
    """[2단계] 한국이 직접 신고한 이 HS코드의 국가별 수출입 실적.
    국가 필터를 아예 안 걸고 전체를 받아온다 - 그러면 이 응답 자체가 "국가명 목록"
    역할도 하므로, 국가코드를 우리가 미리 알아내거나 변환할 필요가 없다."""
    api_key = get_config()
    url = _get_endpoint("CUSTOMS_ITEM_COUNTRY_API_URL")
    items = _request(
        url, api_key,
        {"hsSgn": hscode, "startYyyyMm": start_ym, "endYyyyMm": end_ym, "numOfRows": 999},
        proxy_url=proxy_url,
    )

    by_country = []
    for item in items:
        by_country.append({
            "country_code": _find_field_optional(item, COUNTRY_CODE_CANDIDATES),
            "country_name_ko": _find_field_optional(item, COUNTRY_NAME_KO_CANDIDATES),
            "country_name_en": _find_field_optional(item, COUNTRY_NAME_EN_CANDIDATES),
            "export_usd": _to_float(_find_field_optional(item, EXP_AMT_CANDIDATES)),
            "import_usd": _to_float(_find_field_optional(item, IMP_AMT_CANDIDATES)),
        })
    by_country.sort(key=lambda x: (x["export_usd"] or 0), reverse=True)
    return {"hscode": hscode, "by_country": by_country}


def annual_totals(by_month):
    """월별 수출입 데이터를 연도 단위로 합산한다 (트라이빅 "한국 N개년
    수출신고 추이" 막대그래프용). 그 해에 값이 없는 달이 하나라도 있으면
    "부분 집계일 수 있다"는 뜻으로 has_gap을 표시한다 (관세청은 매월 15일경
    전월 자료를 갱신하므로, 올해처럼 아직 다 안 들어온 연도가 있을 수 있음)."""
    by_year = {}
    for m in by_month:
        year = m["year_month"][:4]
        entry = by_year.setdefault(year, {
            "year": year, "export_usd": 0.0, "import_usd": 0.0,
            "months_counted": 0, "has_gap": False,
        })
        if m["export_usd"] is None or m["import_usd"] is None:
            entry["has_gap"] = True
        entry["export_usd"] += m["export_usd"] or 0.0
        entry["import_usd"] += m["import_usd"] or 0.0
        entry["months_counted"] += 1
    return sorted(by_year.values(), key=lambda e: e["year"])


def find_country_row(by_country_rows, name_candidates):
    """국가명 후보 목록(예: 사용자가 입력한 원문 + 우리가 아는 한글 별칭들) 중
    하나라도 country_name_ko/en과 일치하면 그 행을 반환한다.
    완전일치를 먼저 다 시도하고, 그래도 없으면 부분일치로 한 번 더 시도한다
    (완전일치를 부분일치보다 먼저 다 봐야 "미국"과 "미국령 사모아" 같은
    걸 헷갈리지 않는다)."""
    candidates = [c.strip() for c in name_candidates if c and c.strip()]
    if not candidates:
        return None

    for cand in candidates:
        for row in by_country_rows:
            if row["country_name_ko"] == cand:
                return row
            if row["country_name_en"] and row["country_name_en"].lower() == cand.lower():
                return row

    for cand in candidates:
        for row in by_country_rows:
            if row["country_name_ko"] and cand in row["country_name_ko"]:
                return row
            if row["country_name_en"] and cand.lower() in row["country_name_en"].lower():
                return row

    return None


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customs_trade_cache (
            cache_key TEXT PRIMARY KEY,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_cache(conn, key, ttl_days):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM customs_trade_cache WHERE cache_key=?", (key,)
    ).fetchone()
    if not row:
        return None
    result_json, fetched_at = row
    fetched = datetime.fromisoformat(fetched_at)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched > timedelta(days=ttl_days):
        return None
    result = json.loads(result_json)
    result["from_cache"] = True
    return result


def _save_cache(conn, key, result):
    conn.execute(
        """
        INSERT INTO customs_trade_cache (cache_key, result_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (key, json.dumps(result, ensure_ascii=False), result["fetched_at"]),
    )
    conn.commit()


def _month_range(months_back, lag_months=2):
    """관세청은 매월 15일경 "전월" 자료를 갱신한다고 알려져 있어서, 이번 달과
    지난 달은 아직 자료가 없을 수 있다 (UN Comtrade의 "보고 지연"과 같은 종류의
    문제라 lag_months만큼 기준일을 뒤로 물려서 시작한다)."""
    now = datetime.now(timezone.utc)
    end_total = now.year * 12 + (now.month - 1) - lag_months
    start_total = end_total - months_back
    end_ym = f"{end_total // 12}{end_total % 12 + 1:02d}"
    start_ym = f"{start_total // 12}{start_total % 12 + 1:02d}"
    return start_ym, end_ym


def get_customs_context(
    hscode: str,
    target_country_candidates: list[str] | None = None,
    *,
    months: int = 36,
    db_path: str | None = None,
    ttl_days: int = CACHE_TTL_DAYS,
    force: bool = False,
    proxy_url: str | None = None,
) -> dict:
    """공개 인터페이스. 다른 코드는 이 함수 하나만 알면 된다.

    target_country_candidates: 이 국가명을 후보로 순서대로 매칭 시도한다
    (예: ["베트남", "Vietnam"]). 하나도 안 맞으면 target_country_match는 None.
    관세청 API가 어떤 표기를 쓰는지 확실하지 않아서 후보를 여러 개 받는다.

    반환 스키마:
        {
            "hscode", "months_covered": "YYYYMM~YYYYMM",
            "item_total": [{"year_month", "export_usd", "import_usd"}, ...],
            "annual_totals": [{"year", "export_usd", "import_usd",
                                "months_counted", "has_gap"}, ...],  # item_total을 연도별로 합산
            "target_country_match": {"country_name_ko", "country_name_en",
                                      "export_usd", "import_usd"} | None,
            "fetched_at", "from_cache",
        }
    """
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (6자리 숫자)")

    start_ym, end_ym = _month_range(months)
    cache_key = f"{hscode}|{','.join(target_country_candidates or [])}|{start_ym}-{end_ym}"

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    ensure_schema(conn)

    try:
        if not force:
            cached = _load_cache(conn, cache_key, ttl_days)
            if cached:
                return cached

        item_stats = get_item_trade_stats(hscode, start_ym, end_ym, proxy_url=proxy_url)

        target_country_match = None
        if target_country_candidates:
            country_stats = get_item_country_trade_stats(hscode, start_ym, end_ym, proxy_url=proxy_url)
            target_country_match = find_country_row(country_stats["by_country"], target_country_candidates)

        result = {
            "hscode": hscode,
            "months_covered": f"{start_ym}~{end_ym}",
            "item_total": item_stats["by_month"],
            "annual_totals": annual_totals(item_stats["by_month"]),
            "target_country_match": target_country_match,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": False,
        }
        _save_cache(conn, cache_key, result)
        return result
    finally:
        conn.close()

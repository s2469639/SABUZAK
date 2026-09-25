"""한국 관세청 '품목별 국가별 수출입실적' (공공데이터포털) 조회.

un_v6/customs_kr.py를 이 프로젝트 구조로 그대로 이식한 것 (DB 경로만
instance/un_comtrade_cache.db로 통일). UN Comtrade의 "상대국이 신고한
한국산 수입액"은 금액이 작을 때 원산지 분류 차이·중계무역 때문에 오차가
크므로, 한국의 실제 수출 실적은 한국 관세청 통계로 교차 확인한다.

API: https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList
    - serviceKey, strtYymm, endYymm(조회기간 1년 이내), hsSgn(HS 2~10자리), cntyCd(2자리 국가코드)
    - 응답(XML): item마다 year("2024.01" 또는 "총계"), hsCd(10자리 HSK), expDlr(수출금액 달러) 등
    - 6자리 HS로 조회하면 10자리 HSK별 x 월별로 쪼개진 행 + 맨 앞에 "총계" 행이 온다.
    - 수출은 FOB 기준(관세청 공시). UN Comtrade 수입액(CIF)과 기준이 달라 약간의 차이는 정상이다.

.env에 DATA_GO_KR_API_KEY(공공데이터포털 Decoding 키)가 없으면 조용히 건너뛴다
(선택 기능 - 없어도 나머지 화면은 그대로 동작).
"""

import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "instance", "un_comtrade_cache.db")
API_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
KST = timezone(timedelta(hours=9))

# ISO3 -> ISO2 (관세청 API는 2자리 국가코드를 씀). UN Comtrade reporterISO 값 기준.
ISO3_TO_ISO2 = {
    "USA": "US", "CAN": "CA", "MEX": "MX", "BRA": "BR", "ARG": "AR", "CHL": "CL", "PER": "PE",
    "COL": "CO", "ECU": "EC", "URY": "UY", "PRY": "PY", "BOL": "BO", "VEN": "VE", "PAN": "PA",
    "CRI": "CR", "GTM": "GT", "DOM": "DO", "JAM": "JM", "TTO": "TT",
    "GBR": "GB", "IRL": "IE", "FRA": "FR", "DEU": "DE", "ITA": "IT", "ESP": "ES", "PRT": "PT",
    "NLD": "NL", "BEL": "BE", "LUX": "LU", "CHE": "CH", "AUT": "AT", "DNK": "DK", "SWE": "SE",
    "NOR": "NO", "FIN": "FI", "ISL": "IS", "POL": "PL", "CZE": "CZ", "SVK": "SK", "HUN": "HU",
    "ROU": "RO", "BGR": "BG", "GRC": "GR", "HRV": "HR", "SVN": "SI", "SRB": "RS", "EST": "EE",
    "LVA": "LV", "LTU": "LT", "UKR": "UA", "BLR": "BY", "RUS": "RU", "TUR": "TR", "CYP": "CY",
    "MLT": "MT", "GEO": "GE", "ARM": "AM", "AZE": "AZ", "KAZ": "KZ", "UZB": "UZ", "KGZ": "KG",
    "MNG": "MN",
    "CHN": "CN", "JPN": "JP", "KOR": "KR", "TWN": "TW", "S19": "TW", "HKG": "HK", "MAC": "MO",
    "VNM": "VN", "THA": "TH", "MYS": "MY", "SGP": "SG", "IDN": "ID", "PHL": "PH", "KHM": "KH",
    "LAO": "LA", "MMR": "MM", "BRN": "BN", "IND": "IN", "PAK": "PK", "BGD": "BD", "LKA": "LK",
    "NPL": "NP", "AUS": "AU", "NZL": "NZ", "FJI": "FJ", "PNG": "PG",
    "SAU": "SA", "ARE": "AE", "QAT": "QA", "KWT": "KW", "OMN": "OM", "BHR": "BH", "ISR": "IL",
    "JOR": "JO", "LBN": "LB", "IRQ": "IQ", "IRN": "IR", "EGY": "EG", "MAR": "MA", "DZA": "DZ",
    "TUN": "TN", "LBY": "LY", "NGA": "NG", "GHA": "GH", "KEN": "KE", "ETH": "ET", "TZA": "TZ",
    "UGA": "UG", "ZAF": "ZA", "CIV": "CI", "SEN": "SN", "CMR": "CM", "AGO": "AO", "MOZ": "MZ",
}


def iso3_to_iso2(iso3):
    if not iso3:
        return None
    return ISO3_TO_ISO2.get(str(iso3).upper())


def _api_key():
    return os.getenv("DATA_GO_KR_API_KEY")


def _ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customs_kr_cache (
            hscode TEXT NOT NULL,
            iso2 TEXT NOT NULL,
            period_key TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, iso2, period_key)
        )
        """
    )
    conn.commit()


def _to_float(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _fetch_period(key, hscode, iso2, start_yymm, end_yymm):
    """관세청 API 1회 호출 -> {"export_usd", "import_usd", "months": [...]}.
    "총계" 행이 있으면 그 값을 쓰고, 없으면 월별 행을 직접 합산한다."""
    resp = requests.get(
        API_URL,
        params={"serviceKey": key, "strtYymm": start_yymm, "endYymm": end_yymm,
                "hsSgn": hscode, "cntyCd": iso2},
        timeout=20,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    # 공공데이터포털 게이트웨이 오류(인증키 미등록, 호출 한도 초과 등)는 형식이 달라서
    # resultCode 없이 returnReasonCode/returnAuthMsg로 온다. 이걸 놓치면 "수출 $0"으로
    # 잘못 보이므로 반드시 오류로 처리한다.
    gw_code = (root.findtext(".//returnReasonCode") or "").strip()
    if gw_code and gw_code != "00":
        msg = (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "").strip()
        raise RuntimeError(f"공공데이터포털 오류 {gw_code}: {msg}")
    code = (root.findtext(".//resultCode") or "").strip()
    msg = (root.findtext(".//resultMsg") or "").strip()
    if code in ("03",) or "NODATA" in msg.upper():
        # 해당 기간 수출입 실적이 없음 = 0 (오류가 아님)
        return {"export_usd": 0.0, "import_usd": 0.0, "months": []}
    if code and code != "00":
        raise RuntimeError(f"관세청 API 오류 {code}: {msg}")
    if not code and root.find(".//item") is None:
        raise RuntimeError("관세청 API 응답 형식을 알 수 없습니다: " + resp.text[:120])

    total_row = None
    exp_sum = imp_sum = 0.0
    months = set()
    for item in root.iter("item"):
        year = (item.findtext("year") or "").strip()
        exp = _to_float(item.findtext("expDlr"))
        imp = _to_float(item.findtext("impDlr"))
        if year == "총계":
            total_row = (exp, imp)
            continue
        exp_sum += exp
        imp_sum += imp
        if year:
            months.add(year)
    export_usd, import_usd = total_row if total_row else (exp_sum, imp_sum)
    return {"export_usd": export_usd, "import_usd": import_usd, "months": sorted(months)}


def _read_cache(conn, hscode, iso2, period_key, ttl_days):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM customs_kr_cache "
        "WHERE hscode=? AND iso2=? AND period_key=?",
        (hscode, iso2, period_key),
    ).fetchone()
    if not row:
        return None
    fetched = datetime.fromisoformat(row[1])
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched > timedelta(days=ttl_days):
        return None
    return json.loads(row[0])


def _write_cache(conn, hscode, iso2, period_key, data):
    conn.execute(
        """
        INSERT INTO customs_kr_cache (hscode, iso2, period_key, result_json, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hscode, iso2, period_key) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, iso2, period_key, json.dumps(data, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def _fetch_many(conn, key, hscode, iso2, periods, force):
    """periods: [(start_yymm, end_yymm, ttl_days)] -> {(start, end): data}.
    캐시에 없는 기간만 API로 받는다. 연도마다 1번씩 호출해야 해서(조회기간 1년 이내 제한)
    순서대로 부르면 느리므로, 최대 3개를 동시에 받는다 (초당 호출 제한을 넘지 않는 수준)."""
    out, missing = {}, []
    for start, end, ttl in periods:
        cached = None if force else _read_cache(conn, hscode, iso2, f"{start}-{end}", ttl)
        if cached is not None:
            out[(start, end)] = cached
        else:
            missing.append((start, end))
    if missing:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(_fetch_period, key, hscode, iso2, st, en): (st, en) for st, en in missing}
            for fut, (st, en) in futures.items():
                data = fut.result()  # 하나라도 실패하면 예외 -> 호출한 쪽에서 "조회 실패"로 처리
                out[(st, en)] = data
                _write_cache(conn, hscode, iso2, f"{st}-{en}", data)
    return out


def get_korea_exports(hscode, iso3, years, *, include_ytd=False, force=False, db_path=None):
    """한국 -> 해당 국가 수출액(관세청 기준)을 연도별로 돌려준다.

    반환:
        {"available": True, "iso2", "by_year": [{"year", "export_usd"}],
         "ytd": {"year", "months", "export_usd", "prev_export_usd", "yoy_pct"} | None, "source": "관세청"}
        또는 {"available": False, "reason": "..."} (키 없음/국가코드 매핑 없음/API 오류)
    """
    key = _api_key()
    if not key:
        return {"available": False, "reason": "DATA_GO_KR_API_KEY가 설정되어 있지 않습니다."}
    iso2 = iso3_to_iso2(iso3)
    if not iso2:
        return {"available": False, "reason": f"관세청 국가코드로 변환할 수 없는 국가입니다 ({iso3})."}

    db_path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db_path, timeout=10)
    _ensure_schema(conn)
    now = datetime.now(KST)
    try:
        full_years = [y for y in sorted(set(years)) if y < now.year]  # 올해는 ytd로 따로 처리
        # 지난해는 정정 신고가 반영될 수 있어 7일, 그 이전 연도는 90일 캐시
        periods = [(f"{y}01", f"{y}12", 7 if y == now.year - 1 else 90) for y in full_years]

        # 관세청은 매월 15일경 전월 자료를 반영 -> 15일 이전이면 전전월까지만 확정
        last_month = (now.month - 1 if now.day >= 15 else now.month - 2) if include_ytd else 0
        if last_month >= 1:
            periods.append((f"{now.year}01", f"{now.year}{last_month:02d}", 3))
            # 전년 같은 기간(1월~같은 달)과 비교해야 "올해 흐름"을 판단할 수 있다
            periods.append((f"{now.year - 1}01", f"{now.year - 1}{last_month:02d}", 7))

        got = _fetch_many(conn, key, hscode, iso2, periods, force)
        by_year = [{"year": y, "export_usd": got[(f"{y}01", f"{y}12")]["export_usd"]} for y in full_years]

        ytd = None
        if last_month >= 1:
            data = got[(f"{now.year}01", f"{now.year}{last_month:02d}")]
            prev = got[(f"{now.year - 1}01", f"{now.year - 1}{last_month:02d}")]
            prev_usd = prev["export_usd"]
            ytd = {
                "year": now.year, "months": last_month, "export_usd": data["export_usd"],
                "prev_export_usd": prev_usd,
                "yoy_pct": round((data["export_usd"] / prev_usd - 1) * 100, 1) if prev_usd else None,
            }

        return {"available": True, "iso2": iso2, "by_year": by_year, "ytd": ytd, "source": "관세청"}
    except Exception as e:
        print(f"[관세청] {hscode}/{iso2} 조회 실패: {e}")
        return {"available": False, "reason": f"관세청 자료 조회 실패: {e}"}
    finally:
        conn.close()

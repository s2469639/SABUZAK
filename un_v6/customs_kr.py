"""한국 관세청 '품목별 국가별 수출입실적' (공공데이터포털) 조회.

UN Comtrade의 "상대국이 신고한 한국산 수입액"은 금액이 작을 때 원산지 분류
차이·중계무역 때문에 오차가 크다. 한국의 실제 수출 실적은 한국 관세청 통계가
가장 정확하므로, 한국 측 수출액은 이 모듈로 가져와서 교차 확인용으로 쓴다.

API: https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList
    - serviceKey, strtYymm, endYymm(조회기간 1년 이내), hsSgn(HS 2~10자리), cntyCd(2자리 국가코드)
    - 응답(XML): item마다 year("2024.01" 또는 "총계"), hsCd(10자리 HSK), expDlr(수출금액 달러) 등
    - 6자리 HS로 조회하면 10자리 HSK별 x 월별로 쪼개진 행 + 맨 앞에 "총계" 행이 온다.
      (사용자 환경에서 실제 응답으로 확인함: 2024년 미국 190590 총계 expDlr=136,278,667)
    - 수출은 FOB 기준(관세청 공시). UN Comtrade 수입액(CIF)과 기준이 달라 약간의 차이는 정상이다.

.env에 DATA_GO_KR_API_KEY(공공데이터포털 Decoding 키)가 없으면 조용히 건너뛴다
(선택 기능 - 없어도 나머지 화면은 그대로 동작).
"""

import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "un_comtrade_cache.db")
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
    parent_env = os.path.join(os.path.dirname(BASE_DIR), ".env")
    if os.path.exists(parent_env):
        load_dotenv(parent_env, override=True)
    local_env = os.path.join(BASE_DIR, ".env")
    if os.path.exists(local_env):
        load_dotenv(local_env, override=False)
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
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code != "00":
        msg = (root.findtext(".//resultMsg") or "").strip()
        raise RuntimeError(f"관세청 API 오류 {code}: {msg}")

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


def _cached_period(conn, key, hscode, iso2, start_yymm, end_yymm, ttl_days, force):
    period_key = f"{start_yymm}-{end_yymm}"
    if not force:
        row = conn.execute(
            "SELECT result_json, fetched_at FROM customs_kr_cache "
            "WHERE hscode=? AND iso2=? AND period_key=?",
            (hscode, iso2, period_key),
        ).fetchone()
        if row:
            fetched = datetime.fromisoformat(row[1])
            if datetime.now(timezone.utc) - fetched <= timedelta(days=ttl_days):
                return json.loads(row[0])
    data = _fetch_period(key, hscode, iso2, start_yymm, end_yymm)
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
    time.sleep(0.15)  # 초당 호출 제한(에러코드 23) 예방
    return data


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
        by_year = []
        for y in sorted(set(years)):
            if y >= now.year:
                continue  # 올해는 ytd로 따로 처리
            # 지난해는 정정 신고가 반영될 수 있어 7일, 그 이전 연도는 90일 캐시
            ttl = 7 if y == now.year - 1 else 90
            data = _cached_period(conn, key, hscode, iso2, f"{y}01", f"{y}12", ttl, force)
            by_year.append({"year": y, "export_usd": data["export_usd"]})

        ytd = None
        if include_ytd and now.month > 1:
            # 관세청은 매월 15일경 전월 자료를 반영 -> 15일 이전이면 전전월까지만 확정
            last_month = now.month - 1 if now.day >= 15 else now.month - 2
            if last_month >= 1:
                data = _cached_period(
                    conn, key, hscode, iso2, f"{now.year}01", f"{now.year}{last_month:02d}", 3, force,
                )
                # 전년 같은 기간(1월~같은 달)과 비교해야 "올해 흐름"을 판단할 수 있다
                prev = _cached_period(
                    conn, key, hscode, iso2, f"{now.year - 1}01", f"{now.year - 1}{last_month:02d}", 7, force,
                )
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
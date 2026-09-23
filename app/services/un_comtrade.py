"""HS코드 + 국가 -> UN Comtrade 무역통계 기반 시장조사.

un_v6/un_comtrade.py를 본 프로젝트 구조로 그대로 이식한 것. 로직/데이터
구조는 원본과 동일하고, 아래만 이 프로젝트에 맞게 바꿨다:
    - .env를 따로 찾지 않고(원본은 독립 실행 폴더라 자체 탐색 로직이 있었음)
      run.py가 이미 로드해둔 os.environ만 읽는다.
    - 캐시 DB 경로를 instance/un_comtrade_cache.db로 통일.
    - GET(화면 표시)에서는 네트워크 호출 없이 캐시만 읽는 get_cached_*
      함수를 추가했다 (박람회 상세 페이지를 열 때마다 UN Comtrade/OpenAI를
      호출하면 느리고 API 한도도 금방 닳으므로, 실제 조회는 버튼을 눌러야만
      실행되게 하기 위함 - UNCTAD TRAINS 탭과 동일한 패턴).

⚠️ 검증 상태에 대해 정직하게 알려드립니다 (원본 README 그대로 인용):
    이 코드는 UN Comtrade 공식 패키지(comtradeapicall)의 소스코드를 직접
    읽고 실제 요청 URL/파라미터 구조까지 확인해서 짰지만, 이 환경에서는
    UN Comtrade 서버 접속 자체가 막혀 있어서 실제 응답 JSON을 받아본 적은
    없습니다. 응답 컬럼명(primaryValue, reporterDesc 등)은 UN Comtrade API
    v1 공식 문서 기준으로 가정한 것이지 직접 확인한 건 아닙니다.
"""

import json
import os
import re
import sqlite3
import traceback
from datetime import datetime, timedelta, timezone

import comtradeapicall
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "instance", "un_comtrade_cache.db")
DEFAULT_MODEL = "gpt-4o-mini"
CACHE_TTL_DAYS = 30
DEFAULT_COMPETITORS = ["KOR", "CHN", "JPN", "USA"]
HSCODE_RE = re.compile(r"^\d{6}$")  # Comtrade는 국제 공통 6자리 HS코드를 씀

# 한국의 주요 교역 상대국 위주로 채운 참고 매핑 (Korean/English -> ISO3).
# 여기 없는 국가는 3자리 ISO3 코드(예: VNM, PER)를 직접 입력하면 된다.
KOREAN_NAME_TO_ISO3 = {
    "한국": "KOR", "대한민국": "KOR", "korea": "KOR", "south korea": "KOR",
    "중국": "CHN", "china": "CHN",
    "일본": "JPN", "japan": "JPN",
    "미국": "USA", "united states": "USA", "usa": "USA",
    "베트남": "VNM", "vietnam": "VNM",
    "독일": "DEU", "germany": "DEU",
    "영국": "GBR", "united kingdom": "GBR", "uk": "GBR",
    "프랑스": "FRA", "france": "FRA",
    "인도": "IND", "india": "IND",
    "태국": "THA", "thailand": "THA",
    "인도네시아": "IDN", "indonesia": "IDN",
    "말레이시아": "MYS", "malaysia": "MYS",
    "필리핀": "PHL", "philippines": "PHL",
    "싱가포르": "SGP", "singapore": "SGP",
    "호주": "AUS", "australia": "AUS",
    "캐나다": "CAN", "canada": "CAN",
    "멕시코": "MEX", "mexico": "MEX",
    "브라질": "BRA", "brazil": "BRA",
    "이탈리아": "ITA", "italy": "ITA",
    "스페인": "ESP", "spain": "ESP",
    "네덜란드": "NLD", "netherlands": "NLD",
    "러시아": "RUS", "russia": "RUS",
    "사우디아라비아": "SAU", "saudi arabia": "SAU",
    "아랍에미리트": "ARE", "uae": "ARE",
    "홍콩": "HKG", "hong kong": "HKG",
    "스위스": "CHE", "switzerland": "CHE",
    "튀르키예": "TUR", "터키": "TUR", "turkey": "TUR",
}

_numeric_code_cache = {}  # ISO3 -> Comtrade 숫자 코드 (프로세스 내에서만 캐싱)


def get_config():
    """OpenAI 클라이언트 + Comtrade 구독키를 준비한다.
    키가 없으면 RuntimeError (Flask 요청 중 sys.exit()을 부르면 서버가
    죽어버리므로 예외로 처리)."""
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    comtrade_key = os.getenv("UN_COMTRADE_SUBSCRIPTION_KEY")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY가 .env에 설정되어 있지 않습니다.")
    if not comtrade_key:
        raise RuntimeError(
            "UN_COMTRADE_SUBSCRIPTION_KEY가 .env에 설정되어 있지 않습니다. "
            "comtradeplus.un.org에서 무료로 가입하면 자동 승인됩니다."
        )
    return OpenAI(api_key=openai_key), comtrade_key


def resolve_iso3(country_input: str) -> str:
    """국가명(한글/영문) 또는 ISO3 코드 -> ISO3 코드로 정규화."""
    raw = country_input.strip()
    if len(raw) == 3 and raw.isascii() and raw.isalpha():
        return raw.upper()
    iso3 = KOREAN_NAME_TO_ISO3.get(raw) or KOREAN_NAME_TO_ISO3.get(raw.lower())
    if not iso3:
        raise ValueError(
            f"국가를 인식할 수 없습니다: {country_input!r}. "
            "ISO3 코드(예: VNM, USA, KOR)로 직접 입력해보세요."
        )
    return iso3


def candidate_reporter_codes(iso3: str, proxy_url: str | None = None) -> list[str]:
    """ISO3 -> Comtrade 숫자 국가코드 "후보 목록". 한 나라에 코드가 여러 개인
    경우(예: 독일 DEU -> "280,276")를 대비해 후보를 전부 반환한다."""
    if iso3 in _numeric_code_cache:
        return _numeric_code_cache[iso3]
    result = comtradeapicall.convertCountryIso3ToCode(iso3, proxy_url=proxy_url)
    if not result:
        raise ValueError(f"UN Comtrade에서 국가코드를 찾지 못했습니다: {iso3}")
    codes = [c.strip() for c in result.split(",") if c.strip()]
    if not codes:
        raise ValueError(f"UN Comtrade에서 국가코드를 찾지 못했습니다: {iso3}")
    _numeric_code_cache[iso3] = codes
    return codes


def iso3_to_numeric(iso3: str, proxy_url: str | None = None) -> str:
    return candidate_reporter_codes(iso3, proxy_url=proxy_url)[0]


def _find_column(df, candidates, label):
    for c in candidates:
        if c in df.columns:
            return c
    lowered = {col.lower(): col for col in df.columns}
    for c in candidates:
        if c.lower() in lowered:
            return lowered[c.lower()]
    raise RuntimeError(
        f"{label} 컬럼을 찾지 못했습니다. 실제 응답 컬럼: {list(df.columns)} "
        f"(찾던 이름: {candidates})"
    )


def _find_column_optional(df, candidates):
    try:
        return _find_column(df, candidates, "")
    except RuntimeError:
        return None


def get_global_import_ranking(subscription_key, hscode, year, top_n=10, proxy_url=None):
    """[1단계] 이 HS코드를 전 세계에서 가장 많이 수입하는 나라 순위."""
    df = comtradeapicall.getFinalData(
        subscription_key,
        typeCode="C", freqCode="A", clCode="HS", period=str(year),
        reporterCode=None, cmdCode=hscode, flowCode="M",
        partnerCode="0", partner2Code=None, customsCode=None, motCode=None,
        maxRecords=2500, format_output="JSON", aggregateBy=None,
        breakdownMode="classic", countOnly=None, includeDesc=True,
        proxy_url=proxy_url,
    )
    if df is None or df.empty:
        return []

    value_col = _find_column(df, ["primaryValue"], "수입액")
    country_col = _find_column(df, ["reporterDesc"], "국가명")
    code_col = _find_column_optional(df, ["reporterCode"])

    cols = [country_col, value_col] + ([code_col] if code_col else [])
    ranked = df[cols].dropna(subset=[country_col, value_col]).sort_values(value_col, ascending=False)
    out = []
    for _, row in ranked.head(top_n).iterrows():
        entry = {"country": row[country_col], "import_value_usd": float(row[value_col])}
        if code_col:
            entry["reporter_code"] = str(row[code_col])
        out.append(entry)
    return out


def get_competitiveness(
    subscription_key, hscode, target_iso3, year, competitors=None, proxy_url=None,
    reporter_code=None,
):
    """[2단계] 타깃 국가의 이 HS코드 수입 시장에서 한국/경쟁국 점유율."""
    competitors = competitors or DEFAULT_COMPETITORS

    candidate_codes = [reporter_code] if reporter_code else candidate_reporter_codes(
        target_iso3, proxy_url=proxy_url
    )

    filtered_competitors = []
    for c in competitors:
        try:
            if iso3_to_numeric(c, proxy_url=proxy_url) in candidate_codes:
                continue
        except ValueError:
            pass
        filtered_competitors.append(c)
    competitors = filtered_competitors

    df = None
    for code in candidate_codes:
        df = comtradeapicall.getFinalData(
            subscription_key,
            typeCode="C", freqCode="A", clCode="HS", period=str(year),
            reporterCode=code, cmdCode=hscode, flowCode="M",
            partnerCode=None, partner2Code=None, customsCode=None, motCode=None,
            maxRecords=2500, format_output="JSON", aggregateBy=None,
            breakdownMode="classic", countOnly=None, includeDesc=True,
            proxy_url=proxy_url,
        )
        if df is not None and not df.empty:
            break

    is_mirror = False
    if df is None or df.empty:
        for code in candidate_codes:
            df = comtradeapicall.getFinalData(
                subscription_key,
                typeCode="C", freqCode="A", clCode="HS", period=str(year),
                reporterCode=None, cmdCode=hscode, flowCode="X",
                partnerCode=code, partner2Code=None, customsCode=None, motCode=None,
                maxRecords=2500, format_output="JSON", aggregateBy=None,
                breakdownMode="classic", countOnly=None, includeDesc=True,
                proxy_url=proxy_url,
            )
            if df is not None and not df.empty:
                is_mirror = True
                break

    if df is None or df.empty:
        return {
            "total_import_usd": None, "breakdown": [], "year": year, "item_desc": None,
            "supplier_country_count": None, "is_mirror_estimate": False,
        }

    value_col = _find_column(df, ["primaryValue"], "수입액")
    cmd_desc_col = _find_column_optional(df, ["cmdDesc"])
    item_desc = str(df[cmd_desc_col].iloc[0]) if cmd_desc_col and not df[cmd_desc_col].isna().all() else None

    if not is_mirror:
        country_code_col = _find_column(df, ["partnerCode"], "파트너국 코드")
        world_rows = df[df[country_code_col].astype(str) == "0"]
        total = float(world_rows[value_col].iloc[0]) if not world_rows.empty else None
        other_rows = df[df[country_code_col].astype(str) != "0"][value_col].dropna()
    else:
        country_code_col = _find_column(df, ["reporterCode"], "보고국 코드")
        clean_values = df[value_col].dropna()
        total = float(clean_values.sum()) if not clean_values.empty else None
        other_rows = clean_values

    supplier_country_count = int((other_rows > 0).sum())

    breakdown = []
    for iso3 in competitors:
        try:
            code = iso3_to_numeric(iso3, proxy_url=proxy_url)
        except ValueError:
            continue
        rows = df[df[country_code_col].astype(str) == str(code)]
        value = float(rows[value_col].iloc[0]) if not rows.empty else 0.0
        share = (value / total * 100) if total else None
        breakdown.append({
            "country_iso3": iso3,
            "import_value_usd": value,
            "share_pct": round(share, 1) if share is not None else None,
        })

    breakdown.sort(key=lambda x: x["import_value_usd"], reverse=True)
    return {
        "total_import_usd": total, "breakdown": breakdown, "year": year, "item_desc": item_desc,
        "supplier_country_count": supplier_country_count, "is_mirror_estimate": is_mirror,
    }


def calc_cagr(start_value, end_value, num_years):
    """연평균 성장률(CAGR) = (종료값/시작값)^(1/연수) - 1 (복리 기준)."""
    if not start_value or start_value <= 0 or num_years <= 0:
        return None
    return round(((end_value / start_value) ** (1 / num_years) - 1) * 100, 1)


def get_growth_trend(subscription_key, hscode, target_iso3, years, proxy_url=None, reporter_code=None):
    """[3단계] 타깃 국가의 이 HS코드 수입액 3개년 추이 + CAGR."""
    candidate_codes = [reporter_code] if reporter_code else candidate_reporter_codes(
        target_iso3, proxy_url=proxy_url
    )
    period = ",".join(str(y) for y in years)

    df = None
    for code in candidate_codes:
        df = comtradeapicall.getFinalData(
            subscription_key,
            typeCode="C", freqCode="A", clCode="HS", period=period,
            reporterCode=code, cmdCode=hscode, flowCode="M",
            partnerCode="0", partner2Code=None, customsCode=None, motCode=None,
            maxRecords=2500, format_output="JSON", aggregateBy=None,
            breakdownMode="classic", countOnly=None, includeDesc=True,
            proxy_url=proxy_url,
        )
        if df is not None and not df.empty:
            break

    is_mirror = False
    if df is None or df.empty:
        for code in candidate_codes:
            df = comtradeapicall.getFinalData(
                subscription_key,
                typeCode="C", freqCode="A", clCode="HS", period=period,
                reporterCode=None, cmdCode=hscode, flowCode="X",
                partnerCode=code, partner2Code=None, customsCode=None, motCode=None,
                maxRecords=2500, format_output="JSON", aggregateBy=None,
                breakdownMode="classic", countOnly=None, includeDesc=True,
                proxy_url=proxy_url,
            )
            if df is not None and not df.empty:
                is_mirror = True
                break

    if df is None or df.empty:
        return {
            "by_year": [], "cagr_pct": None, "years_requested": years, "years_with_data": 0,
            "is_mirror_estimate": False,
        }

    value_col = _find_column(df, ["primaryValue"], "수입액")
    year_col = _find_column(df, ["refYear", "period"], "연도")

    clean = df[[year_col, value_col]].dropna()
    if not is_mirror:
        clean = clean.sort_values(year_col)
        by_year = [
            {"year": int(row[year_col]), "import_value_usd": float(row[value_col])}
            for _, row in clean.iterrows()
        ]
    else:
        grouped = clean.groupby(year_col)[value_col].sum().sort_index()
        by_year = [{"year": int(y), "import_value_usd": float(v)} for y, v in grouped.items()]

    latest_requested_year = max(years)
    for y in by_year:
        y["may_be_incomplete"] = (y["year"] == latest_requested_year)

    cagr = None
    if len(by_year) >= 2:
        start, end = by_year[0], by_year[-1]
        cagr = calc_cagr(start["import_value_usd"], end["import_value_usd"], end["year"] - start["year"])

    return {
        "by_year": by_year,
        "cagr_pct": cagr,
        "years_requested": years,
        "years_with_data": len(by_year),
        "is_mirror_estimate": is_mirror,
    }


def interpret_with_llm(client, model, official_item_desc, hscode, target_country, ranking, competitiveness, growth):
    """[4단계] 위 3개 지표를 OpenAI에게 주고 전략적 시사점을 한국어로 작성."""
    payload = {
        "official_item_desc_en": official_item_desc or "(UN Comtrade 응답에 설명 없음)",
        "hscode": hscode,
        "target_country": target_country,
        "global_import_ranking": {"countries_returned": len(ranking), "top_countries": ranking},
        "korea_competitiveness": competitiveness,
        "growth_trend": growth,
    }
    prompt = f"""당신은 글로벌 무역 컨설턴트입니다. 아래 [데이터]는 UN Comtrade
공식 무역통계에서 가져온 수치입니다. 이 안에 있는 수치만 사용하고, 여기
없는 숫자나 통계는 절대 새로 만들어내지 마세요 (모르면 "데이터 없음"이라고
쓰세요).

품목명은 반드시 official_item_desc_en(UN Comtrade 공식 설명)을 기준으로
판단하세요.

숫자를 읽을 때 주의할 점:
- korea_competitiveness.total_import_usd가 이 시장(타깃 국가)의 실제 총
  수입 규모입니다. 이 값이 0보다 크면 그 시장에는 수입 수요가 분명히
  존재하는 것이니, breakdown에 나열된 개별 국가의 점유율이 낮다고 해서
  "이 시장은 수입이 없다/수요가 없다"고 결론 내리면 안 됩니다.
- breakdown은 total_import_usd 중 일부(주요 경쟁국)만 나열한 것이라
  국가별 값을 다 더해도 total_import_usd보다 작을 수 있습니다.
- growth_trend.by_year의 각 항목에 "may_be_incomplete": true가 있으면,
  그 연도는 아직 집계가 안 끝났을 수 있습니다. 이 연도의 수치가 이전
  연도보다 낮다고 해서 곧바로 "역성장/수요 감소"라고 단정하지 마세요.
- growth_trend.years_with_data가 years_requested의 개수보다 적으면 일부
  연도 데이터가 아예 없다는 뜻입니다.
- korea_competitiveness.is_mirror_estimate 또는 growth_trend.is_mirror_estimate가
  true이면, 타깃국이 직접 보고한 공식 수치가 아니라 "전세계 각국이 이
  타깃국에 수출했다고 보고한 값들을 합산한 추정치"입니다.

[데이터]
{json.dumps(payload, ensure_ascii=False, indent=2)}
[데이터 끝]

한국 중소기업 관점에서 아래 3가지를 한국어로 작성하세요:
1) 시장 매력도: 이 시장(타깃 국가)이 이 품목에 있어 유망한 시장인지
2) 경쟁 구도: 한국의 현재 점유율과 주요 경쟁국 대비 위치
3) 전략적 제언: 성장률과 점유율을 종합했을 때 취해야 할 전략

반드시 아래 JSON 형식으로만 응답하세요:
{{"market_attractiveness": "...", "competitive_position": "...", "strategic_recommendation": "..."}}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"AI 해석 생성 실패: {e}")
        return None


def _get_conn(db_path=None):
    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    return sqlite3.connect(db_path, timeout=10)


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS un_comtrade_cache (
            hscode TEXT NOT NULL,
            target_country TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, target_country)
        )
        """
    )
    conn.commit()


def _load_cache(conn, hscode, target_country, ttl_days):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM un_comtrade_cache WHERE hscode=? AND target_country=?",
        (hscode, target_country),
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


def _save_cache(conn, hscode, target_country, result):
    conn.execute(
        """
        INSERT INTO un_comtrade_cache (hscode, target_country, result_json, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(hscode, target_country) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, target_country, json.dumps(result, ensure_ascii=False), result["fetched_at"]),
    )
    conn.commit()


def get_cached_market_research(hscode: str, target_country: str, ttl_days: int = CACHE_TTL_DAYS, db_path=None):
    """네트워크 호출 없이 캐시만 읽는다 (화면 표시용). 캐시 없으면 None."""
    if not HSCODE_RE.match(hscode):
        return None
    try:
        target_iso3 = resolve_iso3(target_country)
    except ValueError:
        return None
    conn = _get_conn(db_path)
    try:
        ensure_schema(conn)
        return _load_cache(conn, hscode, target_iso3, ttl_days)
    finally:
        conn.close()


def get_market_research(
    hscode: str,
    target_country: str,
    *,
    competitors: list[str] | None = None,
    years: list[int] | None = None,
    model: str = DEFAULT_MODEL,
    db_path: str | None = None,
    ttl_days: int = CACHE_TTL_DAYS,
    force: bool = False,
    proxy_url: str | None = None,
) -> dict:
    """공개 인터페이스. HS코드(6자리) + 국가 -> 시장조사 결과 (캐시 우선)."""
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")
    target_iso3 = resolve_iso3(target_country)

    if years is None:
        base_year = datetime.now(timezone.utc).year - 2
        years = [base_year - 2, base_year - 1, base_year]
    years = sorted(years)
    latest_year = years[-1]

    conn = _get_conn(db_path)
    ensure_schema(conn)

    cache_key = target_iso3
    try:
        if not force:
            cached = _load_cache(conn, hscode, cache_key, ttl_days)
            if cached:
                return cached

        try:
            openai_client, subscription_key = get_config()
            ranking = get_global_import_ranking(subscription_key, hscode, latest_year, proxy_url=proxy_url)
            competitiveness = get_competitiveness(
                subscription_key, hscode, target_iso3, latest_year, competitors, proxy_url=proxy_url
            )
            growth = get_growth_trend(subscription_key, hscode, target_iso3, years, proxy_url=proxy_url)

            official_item_desc = competitiveness.get("item_desc")
            ai_insight = interpret_with_llm(
                openai_client, model, official_item_desc, hscode, target_iso3,
                ranking, competitiveness, growth,
            )
        except Exception:
            print(f"[un_comtrade] {hscode}/{target_iso3} 조사 중 오류:")
            traceback.print_exc()
            raise

        result = {
            "hscode": hscode,
            "target_country": target_iso3,
            "official_item_desc": official_item_desc,
            "years": years,
            "global_import_ranking": ranking,
            "competitiveness": competitiveness,
            "growth_trend": growth,
            "ai_insight": ai_insight,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": False,
        }
        _save_cache(conn, hscode, cache_key, result)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 매트릭스 비교 (여러 후보국을 "성장률 x 한국 점유율" 두 축 위에서 한 번에 비교)
# ---------------------------------------------------------------------------

QUADRANT_LABELS = {
    (True, True): "집중 공략",
    (True, False): "경쟁력 강화 필요",
    (False, True): "현상 유지/수확",
    (False, False): "우선순위 낮음",
}


def _classify_quadrant(cagr_pct, korea_share_pct, avg_cagr_pct, avg_korea_share_pct):
    high_growth = cagr_pct >= avg_cagr_pct
    high_share = korea_share_pct >= avg_korea_share_pct
    return QUADRANT_LABELS[(high_growth, high_share)]


def ensure_multi_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS un_comtrade_matrix_point_cache (
            hscode TEXT NOT NULL,
            candidate_key TEXT NOT NULL,
            years_key TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, candidate_key, years_key)
        )
        """
    )
    conn.commit()


def _load_point_cache(conn, hscode, candidate_key, years_key, ttl_days):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM un_comtrade_matrix_point_cache "
        "WHERE hscode=? AND candidate_key=? AND years_key=?",
        (hscode, candidate_key, years_key),
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


def _save_point_cache(conn, hscode, candidate_key, years_key, result):
    conn.execute(
        """
        INSERT INTO un_comtrade_matrix_point_cache
            (hscode, candidate_key, years_key, result_json, fetched_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hscode, candidate_key, years_key) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, candidate_key, years_key, json.dumps(result, ensure_ascii=False), result["fetched_at"]),
    )
    conn.commit()


def _get_candidate_point(subscription_key, hscode, label, target_iso3, reporter_code, years, proxy_url):
    latest_year = max(years)
    competitiveness = get_competitiveness(
        subscription_key, hscode, target_iso3, latest_year,
        competitors=["KOR"], proxy_url=proxy_url, reporter_code=reporter_code,
    )
    growth = get_growth_trend(
        subscription_key, hscode, target_iso3, years, proxy_url=proxy_url, reporter_code=reporter_code,
    )

    korea_row = next((b for b in competitiveness["breakdown"] if b["country_iso3"] == "KOR"), None)
    korea_share_pct = korea_row["share_pct"] if korea_row else None
    korea_import_usd = korea_row["import_value_usd"] if korea_row else None
    cagr_pct = growth["cagr_pct"]

    latest_incomplete = any(
        y.get("may_be_incomplete") for y in growth["by_year"] if y["year"] == latest_year
    )

    return {
        "label": label,
        "total_import_usd": competitiveness["total_import_usd"],
        "korea_import_usd": korea_import_usd,
        "korea_share_pct": korea_share_pct,
        "cagr_pct": cagr_pct,
        "years_with_data": growth["years_with_data"],
        "may_be_incomplete_latest_year": latest_incomplete,
        "item_desc": competitiveness.get("item_desc"),
        "supplier_country_count": competitiveness.get("supplier_country_count"),
        "is_mirror_estimate": bool(competitiveness.get("is_mirror_estimate") or growth.get("is_mirror_estimate")),
    }


def interpret_matrix_with_llm(client, model, official_item_desc, hscode, candidates, thresholds):
    payload = {
        "official_item_desc_en": official_item_desc or "(UN Comtrade 응답에 설명 없음)",
        "hscode": hscode,
        "thresholds": thresholds,
        "candidates": candidates,
    }
    prompt = f"""당신은 글로벌 무역 컨설턴트입니다. 아래 [데이터]는 여러 후보
국가에 대해 UN Comtrade 공식 무역통계로 계산한 "성장률 x 한국 점유율"
매트릭스 좌표입니다. 이 안에 있는 수치만 사용하고 새 숫자를 지어내지 마세요.

각 후보국의 quadrant 필드는 이미 계산되어 있습니다:
- "집중 공략": 시장 성장률도 평균 이상, 한국 점유율도 평균 이상
- "경쟁력 강화 필요": 시장은 평균 이상으로 크는데 한국 점유율은 낮음
- "현상 유지/수확": 한국 점유율은 높지만 시장 성장은 평균 이하로 둔화
- "우선순위 낮음": 성장률도 점유율도 평균 이하

may_be_incomplete_latest_year가 true인 후보국은 최신 연도 통계가 아직 다
집계되지 않았을 수 있으니 곧바로 "역성장"이라 단정하지 마세요.
is_mirror_estimate가 true인 후보국은 "전세계 각국이 그 나라에 수출했다고
보고한 값들을 합산한 추정치"이니 그 점을 짧게라도 밝히세요.

[데이터]
{json.dumps(payload, ensure_ascii=False, indent=2)}
[데이터 끝]

한국 중소기업 관점에서:
1) top_priority_markets: 우선적으로 공략할 만한 국가 1~3개와 그 이유
2) overall_strategy: 전체 후보국을 종합했을 때 취할 전략 방향

반드시 아래 JSON 형식으로만 응답하세요:
{{"top_priority_markets": [{{"label": "...", "reason": "..."}}], "overall_strategy": "..."}}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"AI 매트릭스 해석 생성 실패: {e}")
        return None


def get_multi_country_comparison(
    hscode: str,
    candidate_countries: list[str] | None = None,
    *,
    top_n: int = 10,
    years: list[int] | None = None,
    model: str = DEFAULT_MODEL,
    db_path: str | None = None,
    ttl_days: int = CACHE_TTL_DAYS,
    force: bool = False,
    proxy_url: str | None = None,
) -> dict:
    """공개 인터페이스: 후보국 여러 개를 "성장률 x 한국 점유율" 매트릭스로 비교."""
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")

    if years is None:
        base_year = datetime.now(timezone.utc).year - 2
        years = [base_year - 2, base_year - 1, base_year]
    years = sorted(years)
    latest_year = years[-1]
    years_key = ",".join(str(y) for y in years)

    conn = _get_conn(db_path)
    ensure_multi_schema(conn)

    try:
        openai_client, subscription_key = get_config()

        targets = []
        if candidate_countries:
            for c in candidate_countries:
                iso3 = resolve_iso3(c)
                targets.append({"label": iso3, "iso3": iso3, "reporter_code": None})
        else:
            ranking = get_global_import_ranking(
                subscription_key, hscode, latest_year, top_n=top_n, proxy_url=proxy_url
            )
            for r in ranking:
                if "reporter_code" not in r:
                    continue
                targets.append({"label": r["country"], "iso3": None, "reporter_code": r["reporter_code"]})

        if not targets:
            raise RuntimeError("비교할 후보국을 찾지 못했습니다. candidate_countries를 직접 지정해보세요.")

        official_item_desc = None
        candidates = []
        excluded = []
        for t in targets:
            candidate_key = t["iso3"] or f"code:{t['reporter_code']}"
            cached = None if force else _load_point_cache(conn, hscode, candidate_key, years_key, ttl_days)
            if cached:
                point = cached
            else:
                point = _get_candidate_point(
                    subscription_key, hscode, t["label"], t["iso3"], t["reporter_code"], years, proxy_url,
                )
                point["fetched_at"] = datetime.now(timezone.utc).isoformat()
                _save_point_cache(conn, hscode, candidate_key, years_key, point)

            if official_item_desc is None and point.get("item_desc"):
                official_item_desc = point["item_desc"]

            if point["cagr_pct"] is None or point["korea_share_pct"] is None:
                excluded.append({
                    "label": point["label"],
                    "reason": "성장률 또는 한국 점유율을 계산할 데이터가 부족합니다.",
                })
            else:
                candidates.append(point)

        if not candidates:
            raise RuntimeError("매트릭스에 올릴 수 있는 후보국이 없습니다 (모든 후보국의 데이터가 부족합니다).")

        avg_cagr = round(sum(c["cagr_pct"] for c in candidates) / len(candidates), 1)
        avg_share = round(sum(c["korea_share_pct"] for c in candidates) / len(candidates), 1)
        for c in candidates:
            c["quadrant"] = _classify_quadrant(c["cagr_pct"], c["korea_share_pct"], avg_cagr, avg_share)

        ranked_by_import = sorted(candidates, key=lambda c: (c["total_import_usd"] or 0), reverse=True)
        for i, c in enumerate(ranked_by_import, 1):
            c["import_rank"] = i

        candidates.sort(key=lambda c: (c["cagr_pct"], c["korea_share_pct"]), reverse=True)

        ai_summary = interpret_matrix_with_llm(
            openai_client, model, official_item_desc, hscode, candidates,
            {"avg_cagr_pct": avg_cagr, "avg_korea_share_pct": avg_share},
        )

        return {
            "hscode": hscode,
            "official_item_desc": official_item_desc,
            "years": years,
            "thresholds": {"avg_cagr_pct": avg_cagr, "avg_korea_share_pct": avg_share},
            "candidates": candidates,
            "excluded": excluded,
            "ai_summary": ai_summary,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": all(c.get("from_cache") for c in candidates) if candidates else False,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 시장 개요: 수입/수출 순위표 + 주요국 세계시장 점유율 추이
# ---------------------------------------------------------------------------


def get_global_flow_stats(subscription_key, hscode, years, flow="M", proxy_url=None):
    period = ",".join(str(y) for y in years)
    df = comtradeapicall.getFinalData(
        subscription_key,
        typeCode="C", freqCode="A", clCode="HS", period=period,
        reporterCode=None, cmdCode=hscode, flowCode=flow,
        partnerCode="0", partner2Code=None, customsCode=None, motCode=None,
        maxRecords=2500, format_output="JSON", aggregateBy=None,
        breakdownMode="classic", countOnly=None, includeDesc=True,
        proxy_url=proxy_url,
    )
    if df is None or df.empty:
        return []

    value_col = _find_column(df, ["primaryValue"], "금액")
    country_col = _find_column(df, ["reporterDesc"], "국가명")
    year_col = _find_column(df, ["refYear", "period"], "연도")
    code_col = _find_column_optional(df, ["reporterCode"])

    cols = [country_col, value_col, year_col] + ([code_col] if code_col else [])
    clean = df[cols].dropna(subset=[country_col, value_col, year_col])

    out = []
    for _, row in clean.iterrows():
        entry = {"country": row[country_col], "year": int(row[year_col]), "value_usd": float(row[value_col])}
        if code_col:
            entry["reporter_code"] = str(row[code_col])
        out.append(entry)
    return out


def ranking_from_flow_stats(flow_stats, year, top_n=10):
    rows = [r for r in flow_stats if r["year"] == year]
    rows.sort(key=lambda r: r["value_usd"], reverse=True)
    return [{"country": r["country"], "value_usd": r["value_usd"]} for r in rows[:top_n]]


def world_share_trend_from_flow(flow_stats, years, top_n=6, always_include_codes=()):
    if not flow_stats or not years:
        return {"years": years or [], "series": {}}

    by_year_total = {}
    for r in flow_stats:
        by_year_total[r["year"]] = by_year_total.get(r["year"], 0.0) + r["value_usd"]

    latest_year = max(years)
    latest_rows = [r for r in flow_stats if r["year"] == latest_year]
    latest_rows.sort(key=lambda r: r["value_usd"], reverse=True)

    def _key(r):
        return r.get("reporter_code") or r["country"]

    selected = []
    seen_keys = set()
    for r in latest_rows[:top_n]:
        k = _key(r)
        if k not in seen_keys:
            selected.append((k, r["country"]))
            seen_keys.add(k)
    for code in always_include_codes:
        if code not in seen_keys:
            match = next((r for r in latest_rows if _key(r) == code), None)
            if match:
                selected.append((code, match["country"]))
                seen_keys.add(code)

    rows_by_key_year = {}
    for r in flow_stats:
        rows_by_key_year[(_key(r), r["year"])] = r

    series = {}
    for key, label in selected:
        pts = []
        for y in years:
            row = rows_by_key_year.get((key, y))
            total = by_year_total.get(y) or 0
            if row and total:
                pts.append({"year": y, "share_pct": round(row["value_usd"] / total * 100, 1)})
            else:
                pts.append({"year": y, "share_pct": None})
        series[label] = pts

    return {"years": years, "series": series}


def ensure_overview_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS un_comtrade_overview_cache (
            hscode TEXT NOT NULL,
            years_key TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, years_key)
        )
        """
    )
    conn.commit()


def _load_overview_cache(conn, hscode, years_key, ttl_days):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM un_comtrade_overview_cache WHERE hscode=? AND years_key=?",
        (hscode, years_key),
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


def _save_overview_cache(conn, hscode, years_key, result):
    conn.execute(
        """
        INSERT INTO un_comtrade_overview_cache (hscode, years_key, result_json, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(hscode, years_key) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, years_key, json.dumps(result, ensure_ascii=False), result["fetched_at"]),
    )
    conn.commit()


def get_market_overview(
    hscode: str,
    *,
    years: list[int] | None = None,
    top_n: int = 10,
    trend_top_n: int = 6,
    db_path: str | None = None,
    ttl_days: int = CACHE_TTL_DAYS,
    force: bool = False,
    proxy_url: str | None = None,
) -> dict:
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")

    if years is None:
        base_year = datetime.now(timezone.utc).year - 2
        years = [base_year - 4, base_year - 3, base_year - 2, base_year - 1, base_year]
    years = sorted(years)
    latest_year = years[-1]
    years_key = ",".join(str(y) for y in years)

    conn = _get_conn(db_path)
    ensure_overview_schema(conn)

    try:
        if not force:
            cached = _load_overview_cache(conn, hscode, years_key, ttl_days)
            if cached:
                return cached

        _, subscription_key = get_config()
        korea_code = iso3_to_numeric("KOR", proxy_url=proxy_url)

        import_flow = get_global_flow_stats(subscription_key, hscode, years, flow="M", proxy_url=proxy_url)
        export_flow = get_global_flow_stats(subscription_key, hscode, years, flow="X", proxy_url=proxy_url)

        result = {
            "hscode": hscode,
            "years": years,
            "import_ranking": ranking_from_flow_stats(import_flow, latest_year, top_n),
            "export_ranking": ranking_from_flow_stats(export_flow, latest_year, top_n),
            "import_share_trend": world_share_trend_from_flow(import_flow, years, trend_top_n, [korea_code]),
            "export_share_trend": world_share_trend_from_flow(export_flow, years, trend_top_n, [korea_code]),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": False,
        }
        _save_overview_cache(conn, hscode, years_key, result)
        return result
    finally:
        conn.close()

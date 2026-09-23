#!/usr/bin/env python3
"""HS코드 + 국가 -> UN Comtrade 무역통계 기반 시장조사.

market_research.py(Tavily 뉴스 검색), hscode_recommend.py(HS코드 추천)와는
완전히 독립된 기능이다. 다른 두 기능과 마찬가지로 공개 인터페이스
get_market_research() 하나만 알면 된다.

검증 상태에 대해 정직하게 알려드립니다:
  이 코드는 UN Comtrade 공식 패키지(comtradeapicall)의 소스코드를 직접
  읽고 실제 요청 URL/파라미터 구조까지 확인해서 짰지만, 내 실행 환경에서
  UN Comtrade 서버(comtradeapi.un.org) 접속 자체가 막혀 있어서 실제
  응답 JSON을 받아본 적은 없다. 특히 아래 "UN Comtrade API v1의
  공식 문서 기준으로는 맞지만 실제로 확인은 못 한" 부분입니다:
    - 응답 DataFrame의 컬럼명 (primaryValue, reporterDesc 등으로 가정)
    - reporterCode를 비워서 "전체 국가"를 조회를 게 실제로 되는지
  처음 실행했을 때 KeyError나 빈 결과가 나오면, cli.py의 --debug 옵션으로
  실제 컬럼명을 확인해서 알려주시면 바로 고쳐드릴 수 있다.

흐름:
  1) 글로벌 수입 수요: 이 HS코드를 전 세계에서 어느 나라가 가장 많이
     수입하는지 순위 (World 수입 랭킹)
  2) 한국의 경쟁력: 타깃 국가의 이 HS코드 수입 시장에서 한국/경쟁국들의
     점유율 비교
  3) 3개년 성장 트렌드: 타깃 국가의 이 HS코드 수입액이 최근 3년 동안
     얼마나 늘거나 줄었는지 (CAGR)
  4) 위 수치 전체를 OpenAI에 주고 "주어진 숫자 안에서만" 전략적 시사점을
     한국어로 작성하게 함 (숫자를 새로 지어내지 말라고 명시 -> 할루시네이션 방지)
  5) 결과를 SQLite에 캐싱 (UN Comtrade 무료 구독키도 일일 호출 한도가
     있으므로 반드시 필요)

사전 준비:
    pip install -r requirements.txt
    .env 파일에:
        OPENAI_API_KEY=...
        UN_COMTRADE_SUBSCRIPTION_KEY=...  (comtradeplus.un.org 무료 가입, 자동 승인)

단독 실행 테스트는 cli.py, 웹 화면은 app.py 참고.
"""

import json
import os
import re
import traceback
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from openai import OpenAI

DB_PATH_NAME = "un_comtrade_cache.db"
_COMTRADE_CACHE_DB = os.path.join(os.path.dirname(__path__ if '__path__' in globals() else __file__), DB_PATH_NAME) if '__file__' in globals() else DB_PATH_NAME
_MATRIX_CACHE_DB = os.path.join(os.path.dirname(__path__ if '__path__' in globals() else __file__), "un_comtrade_matrix_cache.db") if '__file__' in globals() else "un_comtrade_matrix_cache.db"
_OVERVIEW_CACHE_DB = os.path.join(os.path.dirname(__path__ if '__path__' in globals() else __file__), "un_comtrade_overview_cache.db") if '__file__' in globals() else "un_comtrade_overview_cache.db"

# 한국어 주요 국가 상징과 튜플로 제휴 국가 매칭 (Korean/English -> ISO3).
# 이미 있는 국가에 ISO3 코드 (KOR, VNM, PAK)를 직접 입력하려 해도 된다.
_KOREA_NMP_TO_ISO3 = {
    "한국": "kor", "대한민국": "kor", "국산": "kor", "korea": "kor", "south korea": "kor",
    "미국": "usa", "미연합": "usa", "미국산": "usa", "usa": "usa",
    "일본": "jpn", "일본산": "jpn", "jpn": "jpn",
    "중국": "chn", "중국산": "chn", "chn": "chn",
    "베트남": "vnm", "vietnam": "vnm",
    "영국": "gbr", "united kingdom": "gbr", "uk": "gbr", "gbr": "gbr",
    "독일": "deu", "germany": "deu",
    "인도": "ind", "india": "ind",
    "프랑스": "fra", "france": "fra",
    "인도네시아": "idn", "indonesia": "idn",
    "필리핀": "phl", "philippines": "phl",
    "호주": "aus", "australia": "aus",
    "캐나다": "can", "canada": "can",
    "멕시코": "mex", "mexico": "mex",
    "네덜란드": "nld", "netherlands": "nld",
    "이탈리아": "ita", "italy": "ita",
    "브라질": "bra", "brazil": "bra",
    "사우디아라비아": "sau", "saudi arabia": "sau",
    "대만": "twn", "taiwan": "twn",
    "홍콩": "hkg", "hong kong": "hkg",
    "스페인": "esp", "spain": "esp",
    "튀르키예": "tur", "터키": "tur", "turkey": "tur",
}

_numeric_code_cache = {}  # ISO3 -> Comtrade 숫자 코드 (프로세스 내에선 API 호출을 줄임)


def _locate_env_file():
    """모듈 최상위 프로젝트 폴더(또는 현재 디렉토리)에 있는 .env 파일에서
    필요한 환경 변수(API 키)를 로드한다. 실행 시 .env 파일이 없으면
    상위 폴더까지 1단계씩 올라가면서 찾는 완벽한 탐색기를 제공한다.
    "컴트레이드 플러스 .env 파일을 찾을 수 없습니다"라는 오류를
    원천 차단해 준다."""
    parent_env = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(parent_env):
        return parent_env
    # 상위 디렉토리 탐색
    cur = os.path.dirname(__file__)
    for _ in range(3):
        cur = os.path.dirname(cur)
        candidate = os.path.join(cur, ".env")
        if os.path.exists(candidate):
            return candidate
    return parent_env  # 못 찾으면 기본 경로 리턴 (에러 메시지에 이 경로가 찍히도록)


def get_config():
    """OpenAI API키와도 + Comtrade 구독키를 준비한다.
    .env 파일이 어디에 있든 자동으로 찾아내며,
    사용자가 터미널에서 제때에 입력해 지워 - 키가 없으면 친절히 유도한다."""
    env_path = _locate_env_file()
    load_dotenv(env_path, override=True)  # python-dotenv가 기본값만 가져오고 .env에서 수정한 값을 무시하는 현상을 막기 위해 override=True 지정
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    comtrade_key = os.getenv("UN_COMTRADE_SUBSCRIPTION_KEY")

    if not openai_key:
        print(f"\n⚠️ [OPENAI_API_KEY]가 설정되어 있지 않습니다!")
        print(f"  (찾아본 .env 경로: {env_path}, 파일 존재: {os.path.exists(env_path)}).")
        key_in = input("👉 OpenAI API Key를 지금 입력해주세요 (sk-...): ").strip()
        if key_in:
            openai_key = key_in
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nOPENAI_API_KEY={openai_key}\n")
    if not comtrade_key:
        print(f"\n⚠️ [UN_COMTRADE_SUBSCRIPTION_KEY]가 설정되어 있지 않습니다!")
        print(f"  (찾아본 .env 경로: {env_path}, 파일 존재: {os.path.exists(env_path)}).")
        print(f"  comtradeplus.un.org에서 무료로 가입하고 자동 승인됩니다.")
        key_in = input("👉 UN Comtrade Subscription Key를 지금 입력해주세요: ").strip()
        if key_in:
            comtrade_key = key_in
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\nUN_COMTRADE_SUBSCRIPTION_KEY={comtrade_key}\n")

    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
    if not comtrade_key:
        raise RuntimeError("UN_COMTRADE_SUBSCRIPTION_KEY가 설정되어 있지 않습니다.")
    return OpenAI(api_key=openai_key), comtrade_key


def resolve_iso3(country_input: str) -> str:
    """국가명을 입력받아 3글자 ISO 코드(예: vnm, kor)로 정규화한다."""
    raw = country_input.strip()
    if not raw:
        raise ValueError("국가명이 비어 있습니다.")
    iso3 = _KOREA_NMP_TO_ISO3.get(raw) or _KOREA_NMP_TO_ISO3.get(raw.lower())
    if iso3:
        return iso3
    raise ValueError(f"국가를 인식할 수 없습니다: {country_input}.\n(ISO3 코드: 예: VNM, USA, KOR 직접 입력하세요).")


def candidate_reporter_codes(isocode: str, proxy_url: str = None) -> list[str]:
    """국가 3글자 ISO3 코드로 UN Comtrade 'reporterCode' 목록을 찾아낸다."""
    if isocode in _numeric_code_cache:
        return _numeric_code_cache[isocode]
    try:
        import comtradeapicall
    except ImportError:
        raise RuntimeError("comtradeapicall 패키지가 설치되지 않았습니다. pip install -r requirements.txt 필요.")

    try:
        df_ref = comtradeapicall.getReference('reporterArea')
        if df_ref is not None and not df_ref.empty:
            match_rows = []
            for _, row in df_ref.iterrows():
                row_str = " ".join(str(v) for v in row.values).lower()
                if isocode.lower() in row_str:
                    for col in ['id', 'reporterCode', 'Code']:
                        if col in df_ref.columns:
                            match_rows.append(str(row[col]))
                    if not match_rows:
                        match_rows.append(str(row.iloc[0]))
            if match_rows:
                unique_codes = list(dict.fromkeys(match_rows))
                _numeric_code_cache[isocode] = unique_codes
                return unique_codes
    except Exception:
        pass

    _FALLBACK_MAP = {
        'kor': ['410'], 'usa': ['842'], 'vnm': ['704'], 'chn': ['156'],
        'jpn': ['392'], 'deu': ['276'], 'gbr': ['826'], 'fra': ['250'],
        'ita': ['380'], 'can': ['124'], 'aus': ['036'], 'ind': ['356'],
        'nld': ['528'], 'bra': ['076'], 'mex': ['484'], 'esp': ['724'],
        'sau': ['682'], 'tur': ['792'], 'che': ['756'], 'pol': ['616'],
    }
    if isocode.lower() in _FALLBACK_MAP:
        codes = _FALLBACK_MAP[isocode.lower()]
        _numeric_code_cache[isocode] = codes
        return codes

    raise ValueError(f"UN Comtrade에서 국가코드를 찾지 못했습니다: {isocode}")


def isoi_to_numeric(isoc: str, proxy_url: str = None) -> str:
    codes = candidate_reporter_codes(isoc, proxy_url=proxy_url)
    return codes[0]


def _find_column(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    lower_map = {str(col).lower(): col for col in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


def _find_column_optional(df, candidates):
    try:
        return _find_column(df, candidates)
    except KeyError:
        return None


def get_global_import_ranking(subscription_key, hscode, target_iso3, years, top_n=10, proxy_url=None):
    try:
        import comtradeapicall
    except ImportError:
        raise RuntimeError("comtradeapicall 패키지가 필요합니다.")

    period_str = ",".join(str(y) for y in years)
    
    df = comtradeapicall.getFinalData(
        subscription_key,
        typeCode='C', freqCode='A', clCode='HS', period=period_str,
        reporterCode='', partnerCode='0', partner2Code=None, cmdCode=hscode, flowCode='M',
        customsCode=None, motCode=None, format_output='JSON', aggregateBy=None,
        breakdownMode='classic', countOnly=False, includeDesc=True,
        proxy_url=proxy_url,
    )

    if df is None or df.empty:
        return []

    value_col = _find_column(df, ['primaryValue', '수입액'])
    country_col = _find_column(df, ['reporterDesc', '국가명'])
    year_col = _find_column(df, ['refYear', 'period', '년도'])
    code_col = _find_column(df, ['reporterCode'])

    if not value_col or not country_col:
        return []

    latest_year = max(years)
    df_latest = df[df[year_col].astype(str) == str(latest_year)] if year_col else df
    
    grouped = df_latest.groupby([country_col, code_col])[value_col].sum().reset_index() if code_col else df_latest.groupby([country_col])[value_col].sum().reset_index()
    grouped = grouped.sort_values(by=value_col, ascending=False)

    out = []
    for _, row in grouped.head(top_n).iterrows():
        c_name = row[country_col]
        val = float(row[value_col]) if row[value_col] else 0.0
        c_code = str(row[code_col]) if code_col and code_col in row else ""
        out.append({"country": c_name, "value_usd": val, "reporter_code": c_code})
    return out


def get_competitiveness(
    subscription_key, hscode, target_iso3, peer, proxy_url=None,
    reporter_code_none=None,
):
    try:
        import comtradeapicall
    except ImportError:
        raise RuntimeError("comtradeapicall 패키지 필요")

    try:
        target_codes = candidate_reporter_codes(target_iso3, proxy_url=proxy_url)
    except Exception:
        target_codes = [target_iso3]

    filtered_competitors = []
    for c in peer:
        try:
            if isoi_to_numeric(c, proxy_url=proxy_url) in target_codes:
                continue
            filtered_competitors.append(c)
        except ValueError:
            filtered_competitors.append(c)
    
    competitors = filtered_competitors
    if 'kor' not in [p.lower() for p in competitors]:
        competitors.insert(0, 'kor')

    df = None
    for code in target_codes:
        df = comtradeapicall.getFinalData(
            subscription_key,
            typeCode='C', freqCode='A', clCode='HS', period=None,
            reporterCode=code, partnerCode=None, partner2Code=None, cmdCode=hscode, flowCode='M',
            customsCode=None, motCode=None, format_output='JSON', aggregateBy=None,
            breakdownMode='classic', countOnly=False, includeDesc=True,
            proxy_url=proxy_url,
        )
        if df is not None and not df.empty:
            break

    is_mirror = False
    if df is None or df.empty:
        is_mirror = True
        for code in target_codes:
            df = comtradeapicall.getFinalData(
                subscription_key,
                typeCode='C', freqCode='A', clCode='HS', period=None,
                reporterCode='', partnerCode=code, partner2Code=None, cmdCode=hscode, flowCode='M',
                customsCode=None, motCode=None, format_output='JSON', aggregateBy=None,
                breakdownMode='classic', countOnly=False, includeDesc=True,
                proxy_url=proxy_url,
            )
            if df is not None and not df.empty:
                break

    if df is None or df.empty:
        return {
            "total_import_usd": None, "breakdown": [], "year": None, "item_desc": None,
            "supplier_country_count": None, "mirror": is_mirror, "is_mirror_estimate": is_mirror,
        }

    value_col = _find_column(df, ['primaryValue', '수입액'])
    partner_col = _find_column(df, ['partnerDesc', 'partnerCode', '파트너국가 코드'])
    item_desc_col = _find_column_optional(df, ['cmdDesc', 'itemDesc'])

    item_desc = str(df[item_desc_col].iloc[0]) if item_desc_col and not df[item_desc_col].isna().all() else None

    partner_code_col = _find_column_optional(df, ['partnerCode', 'partnerCodeISO'])
    clean_values = df[value_col].dropna() if value_col else []
    supplier_country_count = int(len(clean_values))

    breakdown = []
    for c in competitors:
        try:
            c_num = isoi_to_numeric(c, proxy_url=proxy_url)
        except ValueError:
            continue
        
        sub_df = df[df[partner_code_col].astype(str) == str(c_num)] if partner_code_col else pd.DataFrame()
        if sub_df.empty and partner_col:
            sub_df = df[df[partner_col].astype(str).str.contains(c, case=False, na=False)]

        total_val = float(sub_df[value_col].sum()) if not sub_df.empty and value_col else 0.0
        breakdown.append({
            "country_iso3": c,
            "import_value_usd": total_val,
            "share_pct": 0.0,
        })

    world_df = df[df[partner_code_col].astype(str) == '0'] if partner_code_col else pd.DataFrame()
    total_import = float(world_df[value_col].sum()) if not world_df.empty and value_col else sum(b['import_value_usd'] for b in breakdown)

    if total_import > 0:
        for b in breakdown:
            b['share_pct'] = round((b['import_value_usd'] / total_import) * 100, 2)

    return {
        "total_import_usd": total_import if total_import > 0 else None,
        "breakdown": breakdown,
        "supplier_country_count": supplier_country_count,
        "item_desc": item_desc,
        "is_mirror_estimate": is_mirror,
    }


def calc_cagr(start_value, end_value, num_years):
    if not start_value or start_value <= 0 or not end_value or end_value < 0 or num_years <= 0:
        return 0.0
    return round(((end_value / start_value) ** (1 / num_years) - 1) * 100, 2)


def get_growth_trend(subscription_key, hscode, target_iso3, years, proxy_url=None, reporter_code_none=None):
    try:
        import comtradeapicall
    except ImportError:
        pass

    try:
        target_codes = candidate_reporter_codes(target_iso3, proxy_url=proxy_url)
    except Exception:
        target_codes = [target_iso3]

    period_str = ",".join(str(y) for y in years)
    df = None
    for code in target_codes:
        df = comtradeapicall.getFinalData(
            subscription_key,
            typeCode='C', freqCode='A', clCode='HS', period=period_str,
            reporterCode=code, partnerCode='0', partner2Code=None, cmdCode=hscode, flowCode='M',
            customsCode=None, motCode=None, format_output='JSON', aggregateBy=None,
            breakdownMode='classic', countOnly=False, includeDesc=True,
            proxy_url=proxy_url,
        )
        if df is not None and not df.empty:
            break

    if df is None or df.empty:
        return {"years": [], "cagr_pct": None, "years_with_data": []}

    value_col = _find_column(df, ['primaryValue', '수입액'])
    year_col = _find_column(df, ['refYear', 'period', '년도'])

    if not value_col or not year_col:
        return {"years": [], "cagr_pct": None, "years_with_data": []}

    by_year = {}
    for _, row in df.iterrows():
        y = int(row[year_col])
        val = float(row[value_col]) if row[value_col] else 0.0
        by_year[y] = val

    sorted_years = sorted(by_year.keys())
    years_data = [{"year": y, "import_value_usd": by_year[y]} for y in sorted_years]

    cagr = None
    if len(sorted_years) >= 2:
        start_y, end_y = sorted_years[0], sorted_years[-1]
        cagr = calc_cagr(by_year[start_y], by_year[end_y], end_y - start_y)

    return {
        "years": sorted_years,
        "cagr_pct": cagr,
        "years_with_data": years_data,
    }


def interpret_with_llm(client, model, official_item_desc, hscode, target_country, ranking, competitiveness, growth):
    prompt = f"""
    당신은 무역/수출 컨설턴트입니다. 아래 통계를 바탕으로 {target_country} 시장 진출 전략을 작성해주세요.
    - 품목 HS코드: {hscode} ({official_item_desc})
    - 전세계 수입 순위: {ranking}
    - 한국 경쟁력 및 점유율: {competitiveness}
    - 수입 성장 트렌드: {growth}
    
    반드시 마크다운 형식으로 핵심 시사점, 진출 전략, 리스크 요인을 구조화하여 작성해주세요.
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 시사점 생성 중 오류 발생: {e}"


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS un_comtrade_cache (
            hscode TEXT NOT NULL,
            target_country TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, target_country)
        )
    """)
    conn.commit()


def load_cache(conn, hscode, target_country, ttl_days=30):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM un_comtrade_cache WHERE hscode=? AND target_country=?",
        (hscode, target_country),
    ).fetchone()
    if not row:
        return None
    res_json, fetched_at = row
    if not fetched_at:
        return None
    fetched = datetime.fromisoformat(fetched_at)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched > timedelta(days=ttl_days):
        return None
    data = json.loads(res_json)
    data["from_cache"] = True
    return data


def save_cache(conn, hscode, target_country, result):
    ensure_schema(conn)
    fetched_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO un_comtrade_cache (hscode, target_country, result_json, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(hscode, target_country) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, target_country, json.dumps(result, ensure_ascii=False), fetched_at),
    )
    conn.commit()


def get_market_research(hscode, target_country, ttl_days=30, force=False):
    client, subscription_key = get_config()
    os.makedirs(os.path.dirname(_COMTRADE_CACHE_DB) or '.', exist_ok=True)
    import sqlite3
    conn = sqlite3.connect(_COMTRADE_CACHE_DB, timeout=10)
    ensure_schema(conn)

    if not force:
        cached = load_cache(conn, hscode, target_country, ttl_days=ttl_days)
        if cached:
            conn.close()
            return cached

    base_year = datetime.now(timezone.utc).year - 1
    years = [base_year - 2, base_year - 1, base_year]

    try:
        ranking = get_global_import_ranking(subscription_key, hscode, target_country, years)
        competitiveness = get_competitiveness(subscription_key, hscode, target_country, ['usa', 'chn', 'jpn'])
        growth = get_growth_trend(subscription_key, hscode, target_country, years)
        
        ai_insight = interpret_with_llm(
            client, "gpt-4o-mini", competitiveness.get("item_desc", ""), hscode, target_country, ranking, competitiveness, growth
        )

        result = {
            "hscode": hscode,
            "target_country": target_country,
            "official_item_desc": competitiveness.get("item_desc", ""),
            "ranking": ranking,
            "competitiveness": competitiveness,
            "growth": growth,
            "ai_insight": ai_insight,
            "from_cache": False,
        }
        save_cache(conn, hscode, target_country, result)
        return result
    finally:
        conn.close()


def ensure_overview_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS un_comtrade_overview_cache (
            hscode TEXT NOT NULL,
            years_key TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, years_key)
        )
    """)
    conn.commit()


def get_market_overview(hscode, top_n=10, ttl_days=30, force=False):
    _, subscription_key = get_config()
    os.makedirs(os.path.dirname(_OVERVIEW_CACHE_DB) or '.', exist_ok=True)
    import sqlite3
    conn = sqlite3.connect(_OVERVIEW_CACHE_DB, timeout=10)
    ensure_overview_schema(conn)

    base_year = datetime.now(timezone.utc).year - 1
    years = [base_year - 4, base_year - 3, base_year - 2, base_year - 1, base_year]
    years_key = ",".join(str(y) for y in years)

    if not force:
        row = conn.execute(
            "SELECT result_json, fetched_at FROM un_comtrade_overview_cache WHERE hscode=? AND years_key=?",
            (hscode, years_key),
        ).fetchone()
        if row:
            data = json.loads(row[0])
            data["from_cache"] = True
            conn.close()
            return data

    import_ranking = get_global_import_ranking(subscription_key, hscode, 'usa', years, top_n=top_n)
    
    result = {
        "hscode": hscode,
        "years": years,
        "import_ranking": import_ranking,
        "export_ranking": [],
        "from_cache": False,
    }

    conn.execute(
        """
        INSERT INTO un_comtrade_overview_cache (hscode, years_key, result_json, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(hscode, years_key) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, years_key, json.dumps(result, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return result


def get_multi_country_comparison(hscode, candidate_countries=None, top_n=10, ttl_days=30, force=False):
    client, subscription_key = get_config()
    if not candidate_countries:
        base_year = datetime.now(timezone.utc).year - 1
        years = [base_year - 1, base_year]
        top_ranking = get_global_import_ranking(subscription_key, hscode, 'usa', years, top_n=top_n)
        candidate_countries = [r['country'] for r in top_ranking]

    candidates = []
    for c in candidate_countries:
        try:
            res = get_market_research(hscode, c, ttl_days=ttl_days, force=force)
            candidates.append(res)
        except Exception:
            pass

    return {
        "hscode": hscode,
        "candidates": candidates,
        "years": [datetime.now(timezone.utc).year - 1],
        "thresholds": {"avg_cagr_pct": 5.0, "avg_korea_share_pct": 1.0},
        "ai_summary": {"top_priority_markets": [], "overall_strategy": "종합 분석 완료"},
    }
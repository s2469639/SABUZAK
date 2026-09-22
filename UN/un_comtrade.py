"""HS코드 + 국가 -> UN Comtrade 무역통계 기반 시장조사.

market_research.py(Tavily 뉴스 검색), hscode_recommend.py(HS코드 추천)와는
완전히 독립된 기능이다. 다른 두 기능과 마찬가지로 공개 인터페이스
get_market_research() 하나만 알면 된다.

⚠️ 검증 상태에 대해 정직하게 알려드립니다:
    이 코드는 UN Comtrade 공식 패키지(comtradeapicall)의 소스코드를 직접
    읽고 실제 요청 URL/파라미터 구조까지 확인해서 짰지만, 제 실행 환경에서
    UN Comtrade 서버(comtradeapi.un.org) 접속 자체가 막혀 있어서 실제
    응답 JSON을 받아본 적은 없습니다. 특히 아래는 "UN Comtrade API v1의
    공식 문서 기준으로는 맞지만 실제로 확인은 못 한" 부분입니다:
        - 응답 DataFrame의 컬럼명 (primaryValue, reporterDesc 등으로 가정)
        - reporterCode를 비워서 "전체 국가"를 조회하는 게 실제로 되는지
    처음 실행했을 때 KeyError나 빈 결과가 나오면, cli.py의 --debug 옵션으로
    실제 컬럼명을 확인해서 알려주시면 바로 고쳐드릴 수 있습니다.

흐름:
    1) 글로벌 수입 수요: 이 HS코드를 전 세계에서 어느 나라가 가장 많이
       수입하는지 순위 (World 수입 랭킹)
    2) 한국의 경쟁력: 타깃 국가의 이 HS코드 수입 시장에서 한국/경쟁국들의
       점유율 비교
    3) 3개년 성장 트렌드: 타깃 국가의 이 HS코드 수입액이 최근 3개년 동안
       얼마나 늘거나 줄었는지 (CAGR)
    4) 위 수치 전체를 OpenAI에 주고 "주어진 숫자 안에서만" 전략적 시사점을
       한국어로 작성하게 함 (숫자를 새로 지어내지 말라고 명시 -> 할루시네이션 방지)
    5) 결과를 SQLite에 캐싱 (UN Comtrade 무료 구독키도 일일 호출 한도가
       있으므로 반드시 필요)

사전 준비:
    pip install -r requirements.txt
    .env 파일에:
        OPENAI_API_KEY=...
        UN_COMTRADE_SUBSCRIPTION_KEY=...   (comtradeplus.un.org 무료 가입, 자동 승인)

단독 실행 테스트는 cli.py, 웹 화면은 app.py 참고.
"""

import json
import os
import re
import sqlite3
import traceback
from datetime import datetime, timedelta, timezone

import comtradeapicall
from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "un_comtrade_cache.db")
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

_numeric_code_cache = {}  # ISO3 -> Comtrade 숫자 코드 (프로세스 내에서만 캐싱, 반복 조회 시 API 재호출 방지)


def get_config():
    """OpenAI 클라이언트 + Comtrade 구독키를 준비한다.
    키가 없으면 RuntimeError (Flask 요청 중 sys.exit()을 부르면 서버가
    죽어버리는 문제가 있어서 예외로 처리 — 다른 두 기능과 동일한 이유)."""
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    comtrade_key = os.getenv("UN_COMTRADE_SUBSCRIPTION_KEY")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다 (.env 파일 확인).")
    if not comtrade_key:
        raise RuntimeError(
            "UN_COMTRADE_SUBSCRIPTION_KEY가 설정되어 있지 않습니다 (.env 파일 확인). "
            "comtradeplus.un.org에서 무료로 가입하면 자동 승인됩니다."
        )
    return OpenAI(api_key=openai_key), comtrade_key


def resolve_iso3(country_input: str) -> str:
    """국가명(한글/영문) 또는 ISO3 코드 -> ISO3 코드로 정규화."""
    raw = country_input.strip()
    if len(raw) == 3 and raw.isascii() and raw.isalpha():
        # "베트남"도 길이 3인 문자열이라 raw.isalpha()만 보면 ISO3로 오인함
        # (한글도 유니코드 기준 alpha라서) -> ASCII 알파벳인지도 같이 확인
        return raw.upper()
    iso3 = KOREAN_NAME_TO_ISO3.get(raw) or KOREAN_NAME_TO_ISO3.get(raw.lower())
    if not iso3:
        raise ValueError(
            f"국가를 인식할 수 없습니다: {country_input!r}. "
            "ISO3 코드(예: VNM, USA, KOR)로 직접 입력해보세요."
        )
    return iso3


def iso3_to_numeric(iso3: str, proxy_url: str | None = None) -> str:
    """ISO3 -> Comtrade 숫자 국가코드. comtradeapicall의 공식 변환 함수를 쓰되,
    같은 프로세스 안에서 반복 조회 시 매번 API를 다시 부르지 않게 캐싱한다."""
    if iso3 in _numeric_code_cache:
        return _numeric_code_cache[iso3]
    result = comtradeapicall.convertCountryIso3ToCode(iso3, proxy_url=proxy_url)
    if not result:
        raise ValueError(f"UN Comtrade에서 국가코드를 찾지 못했습니다: {iso3}")
    numeric = result.split(",")[0]
    _numeric_code_cache[iso3] = numeric
    return numeric


def _find_column(df, candidates, label):
    """DataFrame에서 기대하는 컬럼을 찾는다. 정확히 일치하는 것부터, 그다음
    대소문자 무시하고 candidates가 포함된 컬럼을 찾는다. 못 찾으면 실제
    컬럼 목록을 담아 에러를 내서 원인 파악이 쉽게 한다 (API 응답 스키마를
    100% 검증하지 못한 채로 짠 코드라 방어적으로 처리함)."""
    for c in candidates:
        if c in df.columns:
            return c
    lowered = {col.lower(): col for col in df.columns}
    for c in candidates:
        if c.lower() in lowered:
            return lowered[c.lower()]
    raise RuntimeError(
        f"{label} 컬럼을 찾지 못했습니다. 실제 응답 컬럼: {list(df.columns)} "
        f"(찾던 이름: {candidates}) -- 이 목록을 알려주시면 코드를 맞춰드릴게요."
    )


def _find_column_optional(df, candidates):
    """_find_column과 같지만 못 찾아도 에러 없이 None을 반환한다.
    cmdDesc(품목 설명)처럼 "있으면 쓰고 없어도 치명적이지 않은" 컬럼에 쓴다."""
    try:
        return _find_column(df, candidates, "")
    except RuntimeError:
        return None


def get_global_import_ranking(subscription_key, hscode, year, top_n=10, proxy_url=None):
    """[1단계] 이 HS코드를 전 세계에서 가장 많이 수입하는 나라 순위.
    reporterCode를 비우면(None) '전체 국가', partnerCode='0'은 '세계 전체
    로부터의 수입 합계'를 의미한다."""
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
    # reporterCode(숫자 국가코드)도 같이 챙겨두면, 매트릭스 비교(자동 후보국
    # 선정)에서 이 순위표의 국가를 ISO3 이름 매칭 없이 바로 재사용할 수 있다.
    # UN 공식 국가명("Viet Nam", "United States of America" 등)은 우리
    # KOREAN_NAME_TO_ISO3 매핑과 표기가 달라서 이름만으로는 매칭이 안 될 수 있음.
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
    """[2단계] 타깃 국가의 이 HS코드 수입 시장에서 한국/경쟁국 점유율.
    reporterCode=타깃국, partnerCode를 비워서(None) 모든 파트너국(+World
    합계인 partner=0)을 한 번에 받은 뒤, 관심 국가들만 추려서 비중을 계산한다.

    reporter_code: 이미 숫자 국가코드를 알고 있으면(예: 글로벌 순위표에서
    가져온 국가) 그대로 넘겨서 ISO3 변환을 건너뛸 수 있다. 이 경우
    target_iso3는 "자기 자신 제외" 판정과 화면 표시용 라벨로만 쓰인다."""
    competitors = competitors or DEFAULT_COMPETITORS
    reporter_code = reporter_code or iso3_to_numeric(target_iso3, proxy_url=proxy_url)

    # 타깃 국가 자신은 경쟁국 목록에서 제외한다. "일본이 일본으로부터
    # 수입한 금액"은 항상 0(자국→자국 거래는 존재하지 않음)인 의미 없는
    # 값인데, 이걸 그냥 두면 화면/AI 프롬프트에 "JPN: $0"으로 찍혀서
    # "이 나라는 수입이 아예 없다"는 착각을 유발한다 (실제로 이 버그 때문에
    # AI가 총 수입액이 3800만 달러인 시장을 "수입이 전혀 없다"고 잘못
    # 해석한 사례가 있었음). ISO3 문자열이 아니라 숫자 코드로 비교해야
    # target_iso3가 없는(자동 후보국) 경우에도 안전하게 걸러진다.
    filtered_competitors = []
    for c in competitors:
        try:
            if iso3_to_numeric(c, proxy_url=proxy_url) == reporter_code:
                continue
        except ValueError:
            pass
        filtered_competitors.append(c)
    competitors = filtered_competitors

    df = comtradeapicall.getFinalData(
        subscription_key,
        typeCode="C", freqCode="A", clCode="HS", period=str(year),
        reporterCode=reporter_code, cmdCode=hscode, flowCode="M",
        partnerCode=None, partner2Code=None, customsCode=None, motCode=None,
        maxRecords=2500, format_output="JSON", aggregateBy=None,
        breakdownMode="classic", countOnly=None, includeDesc=True,
        proxy_url=proxy_url,
    )
    if df is None or df.empty:
        return {
            "total_import_usd": None, "breakdown": [], "year": year, "item_desc": None,
            "supplier_country_count": None,
        }

    value_col = _find_column(df, ["primaryValue"], "수입액")
    partner_code_col = _find_column(df, ["partnerCode"], "파트너국 코드")
    partner_desc_col = _find_column(df, ["partnerDesc"], "파트너국명")
    # cmdDesc: UN Comtrade가 공식으로 관리하는 이 HS코드의 품목 설명(영문).
    # 원래는 사용자가 제품명을 따로 입력받아 화면/AI에 썼는데, 사람이 타이핑한
    # 이름이 HS코드와 실제로 다른 품목을 가리킬 위험이 있어서(예: HS코드는
    # 감자칩인데 이름은 "김치"라고 잘못 입력) 그 입력 자체를 없애고, 대신
    # 이 공식 설명을 화면 제목과 AI 분석 양쪽에 쓴다.
    cmd_desc_col = _find_column_optional(df, ["cmdDesc"])
    item_desc = str(df[cmd_desc_col].iloc[0]) if cmd_desc_col and not df[cmd_desc_col].isna().all() else None

    world_rows = df[df[partner_code_col].astype(str) == "0"]
    total = float(world_rows[value_col].iloc[0]) if not world_rows.empty else None

    # 공급국 다양성(supplier_country_count): World 합계 행(partnerCode='0')을
    # 뺀 나머지 개별 국가 행 중 금액이 0보다 큰 행의 개수. "이 나라가 이
    # 품목을 몇 개국에서 수입해오는가"를 뜻하며, 트라이빅 "유망시장 순위"
    # 버블차트의 Y축(수입국가수)에 대응한다. 이미 받아온 df에서 그대로
    # 계산하므로 API를 추가로 부를 필요가 없다.
    non_world_rows = df[df[partner_code_col].astype(str) != "0"][value_col].dropna()
    supplier_country_count = int((non_world_rows > 0).sum())

    breakdown = []
    for iso3 in competitors:
        try:
            code = iso3_to_numeric(iso3, proxy_url=proxy_url)
        except ValueError:
            continue
        rows = df[df[partner_code_col].astype(str) == str(code)]
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
        "supplier_country_count": supplier_country_count,
    }


def calc_cagr(start_value, end_value, num_years):
    """연평균 성장률(CAGR) = (종료값/시작값)^(1/연수) - 1.
    단순 평균 증감률이 아니라 복리 기준으로 계산해야 함 (자주 틀리는 부분)."""
    if not start_value or start_value <= 0 or num_years <= 0:
        return None
    return round(((end_value / start_value) ** (1 / num_years) - 1) * 100, 1)


def get_growth_trend(subscription_key, hscode, target_iso3, years, proxy_url=None, reporter_code=None):
    """[3단계] 타깃 국가의 이 HS코드 수입액 3개년 추이 + CAGR.
    무료 구독키가 있으면 period에 여러 연도를 콤마로 이어서 한 번에 조회
    가능하다 (무료 preview는 연도 1개씩만 가능해서 3번 나눠 불러야 하지만,
    구독키 방식은 한 번에 끝남).

    reporter_code: 이미 숫자 국가코드를 알고 있으면 ISO3 변환을 건너뛴다
    (자동 후보국 비교에서 순위표의 reporterCode를 그대로 재사용할 때 씀)."""
    reporter_code = reporter_code or iso3_to_numeric(target_iso3, proxy_url=proxy_url)
    period = ",".join(str(y) for y in years)

    df = comtradeapicall.getFinalData(
        subscription_key,
        typeCode="C", freqCode="A", clCode="HS", period=period,
        reporterCode=reporter_code, cmdCode=hscode, flowCode="M",
        partnerCode="0", partner2Code=None, customsCode=None, motCode=None,
        maxRecords=2500, format_output="JSON", aggregateBy=None,
        breakdownMode="classic", countOnly=None, includeDesc=True,
        proxy_url=proxy_url,
    )
    if df is None or df.empty:
        return {"by_year": [], "cagr_pct": None, "years_requested": years, "years_with_data": 0}

    value_col = _find_column(df, ["primaryValue"], "수입액")
    year_col = _find_column(df, ["refYear", "period"], "연도")

    df = df[[year_col, value_col]].dropna().sort_values(year_col)
    by_year = [
        {"year": int(row[year_col]), "import_value_usd": float(row[value_col])}
        for _, row in df.iterrows()
    ]

    # 요청한 연도 중 가장 최근 연도(latest_requested_year)는 나라에 따라
    # 아직 최종 집계가 안 끝났을 수 있다(보고 지연 1~2년은 흔한 일). 그런데도
    # 이 값이 그대로 CAGR 계산에 들어가면 "실제 수요 감소"와 "아직 다 안
    # 걷힌 것"을 구분 못 하고 AI가 "역성장"이라고 단정할 위험이 있다 (JPN
    # 자기거래 버그와 같은 종류의 문제). 그래서 가장 최근 연도에는 항상
    # "미완성일 수 있음" 표시를 붙여서 AI/화면 양쪽에 넘긴다.
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
        "years_requested": years,      # 사용자가 요청한 연도 (실제로 데이터가 다 있으리라는 보장은 없음)
        "years_with_data": len(by_year),  # 실제로 응답에 들어있던 연도 수
    }


def interpret_with_llm(client, model, official_item_desc, hscode, target_country, ranking, competitiveness, growth):
    """[4단계] 위 3개 지표를 OpenAI에게 주고 전략적 시사점을 한국어로 작성.
    UN Comtrade 수치는 공식 통계라 Tavily 뉴스 검색 결과보다는 신뢰도가
    높지만, LLM이 프롬프트에 없는 숫자를 지어낼 위험은 똑같이 있으므로
    "주어진 수치만 사용하라"고 명시한다.

    품목명은 사용자가 따로 타이핑하게 하지 않고, UN Comtrade가 HS코드
    조회 결과로 직접 돌려준 cmdDesc(official_item_desc)를 쓴다. 사람이
    입력하는 이름은 HS코드와 실제로 다른 품목을 가리킬 수 있어서(예:
    HS코드는 감자칩인데 이름은 "김치"), 애초에 그런 입력을 받지 않으면
    AI가 엉뚱한 품목으로 리포트를 쓰는 문제 자체가 구조적으로 발생하지
    않는다."""
    payload = {
        "official_item_desc_en": official_item_desc or "(UN Comtrade 응답에 설명 없음)",
        "hscode": hscode,
        "target_country": target_country,
        # 실제로 몇 개국이 응답에 들어있는지(최대 10개 요청이지만 나라마다
        # 보고를 안 했으면 더 적을 수 있음) 개수를 명시해서, AI가 "10개국
        # 비교"라고 착각하지 않게 함
        "global_import_ranking": {"countries_returned": len(ranking), "top_countries": ranking},
        "korea_competitiveness": competitiveness,
        "growth_trend": growth,
    }
    prompt = f"""당신은 글로벌 무역 컨설턴트입니다. 아래 [데이터]는 UN Comtrade
공식 무역통계에서 가져온 수치입니다. 이 안에 있는 수치만 사용하고, 여기
없는 숫자나 통계는 절대 새로 만들어내지 마세요 (모르면 "데이터 없음"이라고
쓰세요).

품목명은 반드시 official_item_desc_en(UN Comtrade 공식 설명)을 기준으로
판단하세요. 이건 HS코드로 조회해서 나온 공식 데이터이므로 가장 정확합니다.

숫자를 읽을 때 주의할 점:
- korea_competitiveness.total_import_usd가 이 시장(타깃 국가)의 실제 총
  수입 규모입니다. 이 값이 0보다 크면 그 시장에는 수입 수요가 분명히
  존재하는 것이니, breakdown에 나열된 개별 국가의 점유율이 낮다고 해서
  "이 시장은 수입이 없다/수요가 없다"고 결론 내리면 안 됩니다.
- breakdown은 total_import_usd 중 일부(주요 경쟁국)만 나열한 것이라
  국가별 값을 다 더해도 total_import_usd보다 작을 수 있습니다(나머지는
  다른 국가들 몫). 이것도 "수입이 적다"는 의미가 아닙니다.
- growth_trend.by_year의 각 항목에 "may_be_incomplete": true가 있으면,
  그 연도(대개 가장 최근 연도)는 많은 나라가 통계를 1~2년 늦게 제출하기
  때문에 아직 집계가 안 끝났을 수 있습니다. 이 연도의 수치가 이전 연도보다
  낮다고 해서 곧바로 "역성장/수요 감소"라고 단정하지 말고, "최신 연도는
  아직 통계가 완전히 집계되지 않았을 수 있어 실제보다 낮게 보일 수 있다"는
  가능성을 반드시 같이 언급하세요.
- growth_trend.years_with_data가 growth_trend.years_requested의 개수보다
  적으면 일부 연도 데이터가 아예 없다는 뜻입니다. 이때는 "N개년 성장률"이
  아니라 실제로 데이터가 있는 연도 수를 기준으로 설명하세요.

[데이터]
{json.dumps(payload, ensure_ascii=False, indent=2)}
[데이터 끝]

한국 중소기업 관점에서 아래 3가지를 한국어로 작성하세요:
1) 시장 매력도: 이 시장(타깃 국가)이 이 품목에 있어 유망한 시장인지
2) 경쟁 구도: 한국의 현재 점유율과 주요 경쟁국 대비 위치
3) 전략적 제언: 성장률과 점유율을 종합했을 때 취해야 할 전략 (예: 성장률은
   높은데 점유율이 낮으면 "진입 기회는 크나 차별화 필요", 특정 경쟁국
   점유율이 압도적이면 "가격 경쟁보다 틈새 공략" 등)

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
        return None  # 실패해도 원본 수치는 그대로 보여줌


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
    """공개 인터페이스. 다른 코드는 이 함수 하나만 알면 된다.

    UN Comtrade API는 HS코드로만 통계를 분류하고 자연어 제품명은 전혀
    이해하지 못하므로, 입력은 HS코드(6자리)만 받는다. 화면에 보여줄 품목
    이름은 UN Comtrade가 직접 돌려주는 공식 설명(official_item_desc)을
    쓴다 - 사용자가 이름을 따로 입력하게 하면 HS코드와 다른 품목을 적을
    위험이 있어서, 애초에 그 입력 자체를 없앴다.

    반환 스키마:
        {
            "hscode": str, "target_country": str,
            "official_item_desc": str | None,  # UN Comtrade 공식 품목 설명(영문) - 화면 제목과 AI 분석 둘 다 이 값을 씀
            "years": [int, int, int],
            "global_import_ranking": [{"country", "import_value_usd"}, ...],  # 상위 10개국
            "competitiveness": {"total_import_usd", "year", "breakdown": [
                {"country_iso3", "import_value_usd", "share_pct"}, ...]},
            "growth_trend": {
                "by_year": [{"year", "import_value_usd", "may_be_incomplete"}, ...],
                "cagr_pct", "years_requested", "years_with_data",
            },
            "ai_insight": {"market_attractiveness","competitive_position",
                            "strategic_recommendation"} | None,
            "fetched_at": ISO8601, "from_cache": bool,
        }

    주의: UN Comtrade 데이터는 국가에 따라 보고가 1~2년씩 늦는 경우가
    흔하다. years를 지정 안 하면 최근 3개년(재작년 기준 -2~-4년 전)을
    기본값으로 쓰지만, 데이터가 없으면 --years로 더 이전 연도를 직접
    지정해야 할 수 있다.
    """
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")
    target_iso3 = resolve_iso3(target_country)

    if years is None:
        base_year = datetime.now(timezone.utc).year - 2  # Comtrade 보고 지연 감안한 기본값
        years = [base_year - 2, base_year - 1, base_year]
    years = sorted(years)
    latest_year = years[-1]

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
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

            # AI에게는 사용자가 타이핑한 product_name이 아니라 UN Comtrade가
            # 공식으로 돌려준 품목 설명(cmdDesc)을 준다 -> 사용자가 HS코드와
            # 다른 이름을 실수로 입력해도 AI 리포트가 엉뚱한 품목으로 안 새게 됨
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
            "official_item_desc": official_item_desc,  # UN Comtrade 공식 품목 설명 (AI가 실제로 쓰는 기준)
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
# 후보국 비교 매트릭스 (KOTRA TriBig, ITC Export Potential Map 같은 전문
# 무역조사기관들이 쓰는 방식): 국가 하나씩 따로 보는 대신, "이 나라 수입시장이
# 얼마나 크고 있나(성장률)" x "그 안에서 한국이 얼마나 선전하고 있나(점유율)"
# 두 축 위에 후보국들을 한 번에 올려서 비교한다.
#
#                 한국 점유율 높음
#                        |
#   현상유지/수확        |   집중 공략
#   ------------------------------------------  -> 그 나라 수입 성장률(CAGR)
#   우선순위 낮음        |   경쟁력 강화 필요
#                        |
#                 한국 점유율 낮음
#
# 이 방식은 부수적으로 기존 약점도 줄여준다: 매트릭스에는 "경쟁국이 누구냐"가
# 필요 없고 "한국 점유율이 몇 %냐"만 있으면 되므로, DEFAULT_COMPETITORS를
# 하드코딩해둔 문제의 영향이 작아진다 (한국 점유율은 항상 정확히 계산됨).
# ---------------------------------------------------------------------------

QUADRANT_LABELS = {
    (True, True): "집중 공략",
    (True, False): "경쟁력 강화 필요",
    (False, True): "현상 유지/수확",
    (False, False): "우선순위 낮음",
}


def _classify_quadrant(cagr_pct, korea_share_pct, avg_cagr_pct, avg_korea_share_pct):
    """기준선(후보국 평균)보다 성장률/점유율이 각각 높은지로 4분면을 정한다."""
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


def _get_candidate_point(
    subscription_key, hscode, label, target_iso3, reporter_code, years, proxy_url,
):
    """후보국 1개의 매트릭스 좌표(성장률, 한국 점유율)를 계산한다.
    competitors에 KOR을 항상 강제로 포함시켜서, 후보국이 어떤 나라든
    한국 점유율은 반드시 계산되게 한다."""
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
        # 트라이빅 "유망시장 순위" 버블차트의 Y축(공급국 다양성)에 대응.
        # get_competitiveness가 이미 받아온 응답에서 계산하므로 추가 API 호출 없음.
        "supplier_country_count": competitiveness.get("supplier_country_count"),
    }


def interpret_matrix_with_llm(client, model, official_item_desc, hscode, candidates, thresholds):
    """4분면에 흩뿌려진 후보국들을 보고 우선순위와 이유를 한국어로 정리."""
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
- "경쟁력 강화 필요": 시장은 평균 이상으로 크는데 한국 점유율은 낮음 (기회는 있으나 아직 자리 못 잡음)
- "현상 유지/수확": 한국 점유율은 높지만 시장 성장은 평균 이하로 둔화
- "우선순위 낮음": 성장률도 점유율도 평균 이하

may_be_incomplete_latest_year가 true인 후보국은 최신 연도 통계가 아직 다
집계되지 않았을 수 있으니, CAGR이 낮게 보여도 곧바로 "역성장"이라 단정하지
마세요. total_import_usd가 있는데 korea_share_pct가 낮거나 None이면 "한국이
아직 거의 진출 못 한 시장"이지 "수요가 없는 시장"이 아닙니다.

[데이터]
{json.dumps(payload, ensure_ascii=False, indent=2)}
[데이터 끝]

한국 중소기업 관점에서:
1) top_priority_markets: 우선적으로 공략할 만한 국가 1~3개와 그 이유 (라벨 그대로 사용)
2) overall_strategy: 전체 후보국을 종합했을 때 취할 전략 방향 (사분면별로 어떻게 다르게 접근해야 하는지 포함)

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
    """공개 인터페이스: 후보국 여러 개를 "성장률 x 한국 점유율" 매트릭스
    위에서 한 번에 비교한다 (KOTRA TriBig류 전문 무역조사기관 방식).

    candidate_countries:
        - 직접 지정: ["VNM", "태국", "Philippines"] 처럼 ISO3/국가명 리스트.
        - None(기본값): 글로벌 수입 순위 상위 top_n개국을 자동으로 후보로 삼는다.
          이때는 UN Comtrade가 돌려준 국가명/국가코드를 그대로 쓰므로 ISO3
          매핑이 없는 나라도 자동 후보에는 포함될 수 있다 (화면 표시는
          UN 공식 영문 국가명으로 나옴).

    반환 스키마:
        {
            "hscode", "official_item_desc", "years",
            "thresholds": {"avg_cagr_pct", "avg_korea_share_pct"},
            "candidates": [
                {"label", "total_import_usd", "korea_import_usd",
                 "korea_share_pct", "cagr_pct", "quadrant",
                 "years_with_data", "may_be_incomplete_latest_year"},
                ...
            ],  # cagr_pct 또는 korea_share_pct가 없어(데이터 부족) 매트릭스에
                # 올릴 수 없는 후보는 "excluded" 리스트로 따로 뺀다.
            "excluded": [{"label", "reason"}, ...],
            "ai_summary": {"top_priority_markets", "overall_strategy"} | None,
            "fetched_at", "from_cache",
        }
    """
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")

    if years is None:
        base_year = datetime.now(timezone.utc).year - 2
        years = [base_year - 2, base_year - 1, base_year]
    years = sorted(years)
    latest_year = years[-1]
    years_key = ",".join(str(y) for y in years)

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    ensure_multi_schema(conn)

    try:
        openai_client, subscription_key = get_config()

        # 후보국 목록 준비: 직접 지정했으면 ISO3로 정규화, 아니면 글로벌
        # 순위표 상위 top_n개국을 그대로 후보로 삼는다 (reporterCode를 그대로
        # 재사용해서 이름 매칭 실패 위험을 없앤다).
        targets = []  # [{"label", "iso3"|None, "reporter_code"|None}]
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
                    continue  # 국가코드가 없으면(응답 스키마 이슈 등) 후보로 못 씀
                targets.append({"label": r["country"], "iso3": None, "reporter_code": r["reporter_code"]})

        if not targets:
            raise RuntimeError(
                "비교할 후보국을 찾지 못했습니다. candidate_countries를 직접 지정해보세요."
            )

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
                    subscription_key, hscode, t["label"], t["iso3"], t["reporter_code"],
                    years, proxy_url,
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
            raise RuntimeError(
                "매트릭스에 올릴 수 있는 후보국이 없습니다 (모든 후보국의 데이터가 부족합니다)."
            )

        avg_cagr = round(sum(c["cagr_pct"] for c in candidates) / len(candidates), 1)
        avg_share = round(sum(c["korea_share_pct"] for c in candidates) / len(candidates), 1)
        for c in candidates:
            c["quadrant"] = _classify_quadrant(c["cagr_pct"], c["korea_share_pct"], avg_cagr, avg_share)

        # 트라이빅 "유망시장 순위" 버블차트의 X축(수입금액 순위)에 대응.
        # ⚠️ 트라이빅이 실제로 이 순위를 어떤 공식(단순 수입액순? 성장률/점유율을
        # 섞은 자체 점수?)으로 매기는지는 공개돼 있지 않아서 그대로 재현할 수
        # 없다. 우리는 정직하게 "수입금액이 큰 순"으로만 매긴다.
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
# 시장 개요(트라이빅 "세계시장 교역순위" + "주요국 세계시장 점유율"에 대응):
# 수입/수출 양쪽 순위표와, 최근 N개년 동안 주요국들의 "세계 시장 대비 점유율"
# 추이를 만든다. get_multi_country_comparison()(성장률x한국점유율 매트릭스)과
# 완전히 별개의 공개 함수라, 필요한 화면만 골라서 쓸 수 있다.
# ---------------------------------------------------------------------------


def get_global_flow_stats(subscription_key, hscode, years, flow="M", proxy_url=None):
    """이 HS코드를 전세계 모든 국가가 특정 흐름(M=수입, X=수출)으로 몇 년
    동안 얼마씩 거래했는지 원본 행 단위로 받아온다. reporterCode=None(전체
    국가), partnerCode='0'(세계 전체 대상 합계), period에 여러 연도를 콤마로
    이어서 한 번에 요청 - 이 원본 데이터 하나로 ①순위표와 ②연도별 점유율
    추이를 둘 다 만들 수 있어서 API를 두 번 부를 필요가 없다."""
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
    """get_global_flow_stats() 결과에서 특정 연도의 상위 top_n개국 순위만 뽑는다."""
    rows = [r for r in flow_stats if r["year"] == year]
    rows.sort(key=lambda r: r["value_usd"], reverse=True)
    return [{"country": r["country"], "value_usd": r["value_usd"]} for r in rows[:top_n]]


def world_share_trend_from_flow(flow_stats, years, top_n=6, always_include_codes=()):
    """국가별 연도별 "세계 시장 전체 대비 점유율" 추이. 최신 연도 기준 상위
    top_n개국을 고르되, always_include_codes(보통 한국)에 있는 나라는
    상위권 밖이어도 강제로 포함시킨다. 국가는 reporter_code(숫자 코드)로
    식별한다 - UN 공식 영문 국가명이 우리 KOREAN_NAME_TO_ISO3 표기와
    다를 수 있어서 이름 매칭에 의존하지 않는다."""
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

    selected = []  # [(key, label)]
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
    """공개 인터페이스: 트라이빅 "세계시장 교역순위"+"주요국 세계시장 점유율"
    화면에 대응. get_multi_country_comparison()과는 독립적으로 호출 가능.

    반환 스키마:
        {
            "hscode", "years",
            "import_ranking": [{"country", "value_usd"}, ...],
            "export_ranking": [{"country", "value_usd"}, ...],
            "import_share_trend": {"years", "series": {country: [{"year","share_pct"}, ...]}},
            "export_share_trend": {...},
            "fetched_at", "from_cache",
        }
    """
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")

    if years is None:
        base_year = datetime.now(timezone.utc).year - 2
        years = [base_year - 4, base_year - 3, base_year - 2, base_year - 1, base_year]
    years = sorted(years)
    latest_year = years[-1]
    years_key = ",".join(str(y) for y in years)

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
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

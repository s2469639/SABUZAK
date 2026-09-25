"""HS코드 + 국가 -> UN Comtrade 무역통계 기반 시장조사.

un_v6/un_comtrade.py를 이 프로젝트 구조로 그대로 이식한 것. 로직/데이터
구조는 원본과 동일하고, 아래만 이 프로젝트에 맞게 바꿨다:
    - .env를 따로 찾지 않고(원본은 독립 실행 폴더라 자체 탐색 로직이 있었음)
      run.py가 이미 로드해둔 os.environ만 읽는다.
    - 캐시 DB 경로를 instance/un_comtrade_cache.db로 통일.
    - customs_kr 모듈을 app.services.kr_customs로 참조.

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
    2) 한국의 경쟁력: 타깃 국가의 이 HS코드 수입 시장에서 실제 상위 공급국
       순위 + 한국의 순위/점유율 (+ 기존 주요 경쟁국 비교)
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
from openai import OpenAI

from app.services.kr_customs import get_korea_exports

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "instance", "un_comtrade_cache.db")
DEFAULT_MODEL = "gpt-4o-mini"
CACHE_TTL_DAYS = 30
DEFAULT_COMPETITORS = ["KOR", "CHN", "JPN", "USA"]
TOP_SUPPLIERS_N = 10  # 타깃국 수입시장의 "실제 상위 공급국" 몇 개국까지 보여줄지

# 성장률은 2년 구간이면 소규모 시장에서 크게 흔들려서, 5개년 이상으로 본다.
# 기준연도(base_year = 올해-2)보다 1년 더 최근 연도까지 함께 요청해서, 이미
# 확정 통계가 나온 나라는 더 최신 값을 쓴다 (여러 연도를 한 번에 요청하므로
# API 호출 수는 늘지 않는다).
GROWTH_YEARS_BACK = 5
# 한국 점유율이 이 값(%) 미만이면, 후보국 평균보다 높더라도 "한국이 선전 중"으로
# 보지 않는다 (0.01% vs 0.06% 같은 차이로 "집중 공략"이 나오던 문제 방지).
MIN_MEANINGFUL_KOREA_SHARE_PCT = 1.0
# 이보다 작은 시장은 성장률 변동이 크다는 표시를 붙인다.
SMALL_MARKET_USD = 10_000_000
# 최신 연도 값이 직전 연도보다 이 비율 이상 급감하면 "집계 미완 가능성"으로 본다.
INCOMPLETE_DROP_RATIO = 0.7


def default_years():
    """기본 조회 연도: (올해-2)를 기준연도로, 그 5년 전부터 기준연도+1년까지.
    예) 2026년 -> 2019~2025 (2025년은 통계가 확정된 나라만 값이 나온다)."""
    base_year = datetime.now(timezone.utc).year - 2
    return list(range(base_year - GROWTH_YEARS_BACK, base_year + 2)), base_year
HSCODE_RE = re.compile(r"^\d{6}$")  # Comtrade는 국제 공통 6자리 HS코드를 씀

# 한국의 주요 교역 상대국 위주로 채운 참고 매핑 (Korean/English -> ISO3).
# UN Comtrade가 돌려주는 공식 영문 국가명(예: "Viet Nam", "Rep. of Korea")도
# 함께 넣어서, 자동 후보국 이름으로 상세 조사를 할 때 인식 실패를 줄인다.
# 여기 없는 국가는 3자리 ISO3 코드(예: VNM, PER)를 직접 입력하면 된다.
KOREAN_NAME_TO_ISO3 = {
    "한국": "KOR", "대한민국": "KOR", "korea": "KOR", "south korea": "KOR",
    "rep. of korea": "KOR", "republic of korea": "KOR",
    "중국": "CHN", "china": "CHN",
    "일본": "JPN", "japan": "JPN",
    "미국": "USA", "united states": "USA", "usa": "USA", "united states of america": "USA",
    "베트남": "VNM", "vietnam": "VNM", "viet nam": "VNM",
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
    "벨기에": "BEL", "belgium": "BEL",
    "오스트리아": "AUT", "austria": "AUT",
    "스웨덴": "SWE", "sweden": "SWE",
    "덴마크": "DNK", "denmark": "DNK",
    "노르웨이": "NOR", "norway": "NOR",
    "핀란드": "FIN", "finland": "FIN",
    "아일랜드": "IRL", "ireland": "IRL",
    "포르투갈": "PRT", "portugal": "PRT",
    "그리스": "GRC", "greece": "GRC",
    "폴란드": "POL", "poland": "POL",
    "체코": "CZE", "czechia": "CZE", "czech republic": "CZE",
    "헝가리": "HUN", "hungary": "HUN",
    "루마니아": "ROU", "romania": "ROU",
    "러시아": "RUS", "russia": "RUS", "russian federation": "RUS",
    "사우디아라비아": "SAU", "saudi arabia": "SAU",
    "아랍에미리트": "ARE", "uae": "ARE", "united arab emirates": "ARE",
    "이스라엘": "ISR", "israel": "ISR",
    "이집트": "EGY", "egypt": "EGY",
    "남아프리카공화국": "ZAF", "south africa": "ZAF",
    "나이지리아": "NGA", "nigeria": "NGA",
    "홍콩": "HKG", "hong kong": "HKG", "china, hong kong sar": "HKG",
    "대만": "TWN", "taiwan": "TWN", "other asia, nes": "TWN",
    "스위스": "CHE", "switzerland": "CHE",
    "튀르키예": "TUR", "터키": "TUR", "turkey": "TUR", "türkiye": "TUR",
    "뉴질랜드": "NZL", "new zealand": "NZL",
    "칠레": "CHL", "chile": "CHL",
    "페루": "PER", "peru": "PER",
    "콜롬비아": "COL", "colombia": "COL",
    "아르헨티나": "ARG", "argentina": "ARG",
    "파키스탄": "PAK", "pakistan": "PAK",
    "방글라데시": "BGD", "bangladesh": "BGD",
    "카자흐스탄": "KAZ", "kazakhstan": "KAZ",
    "몽골": "MNG", "mongolia": "MNG",
}

_numeric_code_cache = {}  # ISO3 -> Comtrade 숫자 코드 (프로세스 내에서만 캐싱, 반복 조회 시 API 재호출 방지)

# 품목 설명 한국어 번역 캐시 (같은 HS코드를 다시 조회할 때 OpenAI를 또 부르지 않도록 파일에 저장).
# un_v6/app.py의 _translate_item_desc() 그대로 이식.
_DESC_CACHE_FILE = os.path.join(BASE_DIR, "instance", "item_desc_ko_cache.json")


def _load_desc_cache():
    try:
        with open(_DESC_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_desc_cache(cache):
    try:
        os.makedirs(os.path.dirname(_DESC_CACHE_FILE), exist_ok=True)
        with open(_DESC_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 캐시 저장 실패는 화면 표시에 영향 없음


def translate_item_desc(text):
    """UN Comtrade 영문 품목 설명을 한국어로 번역한다 (OpenAI 사용).
    실패하면 None을 돌려주고, 화면에는 영문 원문이 그대로 나온다."""
    if not text:
        return None
    cache = _load_desc_cache()
    if text in cache:
        return cache[text]

    try:
        client, _ = get_config()
        model = os.getenv("OPENAI_TRANSLATE_MODEL", "gpt-4o-mini")
        prompt = (
            "다음은 HS코드 품목 분류 설명(영문)입니다. 무역 실무에서 쓰는 자연스러운 "
            "한국어로 번역하세요. 'heading no. 1605'처럼 호 번호가 나오면 '제1605호'로 "
            "쓰고, 'n.e.c.'는 '달리 분류되지 않은'으로 옮기세요. "
            "번역문만 한 문단으로 출력하세요.\n\n" + text
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        ko = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[품목 설명 번역 실패 - 영문으로 표시] {e}")
        return None

    if ko:
        cache[text] = ko
        _save_desc_cache(cache)
    return ko or None


def get_config():
    """OpenAI 클라이언트 + Comtrade 구독키를 준비한다.
    키가 없으면 RuntimeError (Flask 요청 중 sys.exit()을 부르면 서버가
    죽어버리므로 예외로 처리). run.py가 이미 .env를 os.environ에 로드해뒀으므로
    여기서 dotenv를 다시 부르지 않는다."""
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


def candidate_reporter_codes(iso3: str, proxy_url: str | None = None) -> list[str]:
    """ISO3 -> Comtrade 숫자 국가코드 "후보 목록". comtradeapicall이 한 나라에
    코드를 여러 개(콤마로 구분) 돌려주는 경우가 실제로 있다 - 예: 독일(DEU)은
    "280,276"을 돌려주는데, 280은 통일 이전(1990년 이전 서독) 코드고 276이
    현재(통일 독일) 코드다. 어느 게 "현재" 코드인지는 나라마다 다르고 미리
    알 방법이 없어서, 여기서는 순서를 판단하지 않고 후보를 전부 반환한다 -
    실제로 어느 코드가 맞는지는 이 코드를 쓰는 쪽(get_competitiveness 등)이
    "그 코드로 조회했을 때 데이터가 실제로 나오는지"를 직접 시도해보고 정한다."""
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
    """ISO3 -> Comtrade 숫자 국가코드 (단일 값이 필요한 가벼운 용도:
    화면 표시, "이 경쟁국이 타깃국 자기 자신인지" 대략적인 판정 등).
    후보가 여러 개면 첫 번째를 돌려준다 - 실제 데이터 조회에는
    candidate_reporter_codes()로 전체 후보를 다 시도하는 쪽을 쓴다."""
    return candidate_reporter_codes(iso3, proxy_url=proxy_url)[0]


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


def _round_share(share):
    """점유율 반올림. 소수점 첫째 자리로 반올림하면 0.003%(한국산이 조금이라도
    있음)와 0%(전혀 없음)가 둘 다 0.0이 돼서 구분이 안 되던 문제가 있어,
    소수점 넷째 자리까지 보관한다 (화면에서는 크기에 맞게 줄여서 표시)."""
    return round(share, 4) if share is not None else None


_RANKING_MEMO = {}  # (hscode, year, top_n) -> (저장 시각, 결과). 탭 전환 때마다 같은 순위를 다시 부르지 않게.
_RANKING_MEMO_TTL = timedelta(hours=12)


def get_global_import_ranking(subscription_key, hscode, year, top_n=10, proxy_url=None):
    """[1단계] 이 HS코드를 전 세계에서 가장 많이 수입하는 나라 순위 (메모리 캐시 적용)."""
    key = (hscode, int(year), int(top_n))
    hit = _RANKING_MEMO.get(key)
    if hit and datetime.now(timezone.utc) - hit[0] < _RANKING_MEMO_TTL:
        return [dict(r) for r in hit[1]]
    out = _fetch_global_import_ranking(subscription_key, hscode, year, top_n, proxy_url)
    if out:
        _RANKING_MEMO[key] = (datetime.now(timezone.utc), out)
    return [dict(r) for r in out]


def _fetch_global_import_ranking(subscription_key, hscode, year, top_n=10, proxy_url=None):
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
    iso_col = _find_column_optional(df, ["reporterISO"])

    cols = [country_col, value_col] + [c for c in (code_col, iso_col) if c]
    ranked = df[cols].dropna(subset=[country_col, value_col]).sort_values(value_col, ascending=False)
    out = []
    for _, row in ranked.head(top_n).iterrows():
        entry = {"country": row[country_col], "import_value_usd": float(row[value_col])}
        if code_col:
            entry["reporter_code"] = str(row[code_col])
        if iso_col:
            entry["iso3"] = _clean_text(row[iso_col])
        out.append(entry)
    return out


def _clean_text(value):
    """DataFrame 셀 값을 문자열로. 비어 있거나 NaN이면 None."""
    if value is None or value != value:  # value != value 는 NaN 판정
        return None
    text = str(value).strip()
    return text or None


def _supplier_table(df, value_col, code_col, label_col, iso_col, total, korea_codes, top_n):
    """타깃국 수입시장의 "실제" 공급국 순위표를 만든다 (트라이빅 "수입지역 순위").
    기존 breakdown은 미리 정해둔 경쟁국(KOR/CHN/JPN/USA)만 보여줘서, 실제 1위
    공급국(예: 미국 시장의 캐나다)이 빠지고 한국이 1위처럼 보이는 문제가 있었다.
    여기서는 모든 공급국을 금액순으로 정렬하고, 한국의 실제 순위도 함께 계산한다.
    같은 국가 코드가 여러 행이면 기존 코드와 같은 기준(첫 행)으로 하나만 쓴다."""
    cols = [code_col, value_col] + [c for c in (label_col, iso_col) if c]
    rows = df[cols].dropna(subset=[code_col, value_col]).copy()
    rows[code_col] = rows[code_col].astype(str)
    rows = rows[(rows[code_col] != "0") & (rows[value_col] > 0)]
    rows = rows.drop_duplicates(subset=[code_col], keep="first")
    rows = rows.sort_values(value_col, ascending=False)

    ranked = []
    for rank, (_, row) in enumerate(rows.iterrows(), 1):
        value = float(row[value_col])
        code = row[code_col]
        label = _clean_text(row[label_col]) if label_col else None
        iso3 = _clean_text(row[iso_col]) if iso_col else None
        label = label or code
        ranked.append({
            "rank": rank,
            "label": label,
            "iso3": iso3,
            "code": code,
            "import_value_usd": value,
            "share_pct": _round_share(value / total * 100) if total else None,
            "is_korea": code in korea_codes or iso3 == "KOR",
        })

    korea = next((r for r in ranked if r["is_korea"]), None)
    return {
        "top_suppliers": ranked[:top_n],
        "korea_supplier": korea,  # 한국 행 (순위 밖이어도 따로 보관) - 없으면 None
        "korea_rank": korea["rank"] if korea else None,
        "supplier_ranked_count": len(ranked),
    }


def get_competitiveness(
    subscription_key, hscode, target_iso3, year, competitors=None, proxy_url=None,
    reporter_code=None,
):
    """[2단계] 타깃 국가의 이 HS코드 수입 시장에서 한국/경쟁국 점유율.
    reporterCode=타깃국, partnerCode를 비워서(None) 모든 파트너국(+World
    합계인 partner=0)을 한 번에 받은 뒤, 관심 국가들만 추려서 비중을 계산한다.
    같은 응답으로 "실제 상위 공급국 순위"(top_suppliers)와 한국의 실제 순위도
    함께 만든다 (추가 API 호출 없음).

    reporter_code: 이미 숫자 국가코드를 알고 있으면(예: 글로벌 순위표에서
    가져온 국가) 그대로 넘겨서 ISO3 변환을 건너뛸 수 있다. 이 경우
    target_iso3는 "자기 자신 제외" 판정과 화면 표시용 라벨로만 쓰인다."""
    competitors = competitors or DEFAULT_COMPETITORS

    # comtradeapicall이 한 나라에 국가코드를 여러 개 돌려주는 경우가 실제로
    # 있다 (실사례로 검증됨: 독일 DEU -> "280,276". 280은 통일 이전 서독,
    # 276이 현재 독일인데, 어느 게 "현재" 코드인지 미리 알 방법이 없다).
    # reporter_code를 명시적으로 안 받았으면 후보를 전부 모아뒀다가, 아래에서
    # 실제로 데이터가 나오는 코드를 하나씩 시도해서 찾는다.
    candidate_codes = [reporter_code] if reporter_code else candidate_reporter_codes(
        target_iso3, proxy_url=proxy_url
    )

    # 타깃 국가 자신은 경쟁국 목록에서 제외한다. "일본이 일본으로부터
    # 수입한 금액"은 항상 0(자국→자국 거래는 존재하지 않음)인 의미 없는
    # 값인데, 이걸 그냥 두면 화면/AI 프롬프트에 "JPN: $0"으로 찍혀서
    # "이 나라는 수입이 아예 없다"는 착각을 유발한다 (실제로 이 버그 때문에
    # AI가 총 수입액이 3800만 달러인 시장을 "수입이 전혀 없다"고 잘못
    # 해석한 사례가 있었음). candidate_codes 중 하나라도 일치하면 제외한다.
    filtered_competitors = []
    for c in competitors:
        try:
            if iso3_to_numeric(c, proxy_url=proxy_url) in candidate_codes:
                continue
        except ValueError:
            pass
        filtered_competitors.append(c)
    competitors = filtered_competitors

    # 후보 코드를 하나씩 시도해서 실제로 데이터가 나오는 코드를 찾는다.
    # 대부분의 나라는 후보가 1개뿐이라 이 루프가 한 번만 돈다.
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

    # 미러(거울) 데이터 폴백: 후보 코드를 전부 시도해도 빈 응답이면, 그 나라가
    # 이 API에 "자기가 직접 보고한" 무역 통계를 아예 안 주는 것이다 (실제로
    # 미국을 reporterCode로 걸면 TOTAL 품목조차 0건이 나오는 걸 사용자와 직접
    # 검증했음 - 연도/품목 문제가 아니라 그 나라가 reporter로서 이 API에
    # 데이터가 없는 것). 이럴 때는 "전세계 각국이 이 타깃국에 수출했다고
    # 보고한 값들"을 대신 모아서(reporterCode=None, partnerCode=타깃국,
    # flowCode="X") 타깃국의 수입 통계를 역으로 추정한다. 이 경우 반드시
    # is_mirror_estimate=True로 표시해서 "타깃국이 직접 발표한 공식 수치"와
    # 혼동하지 않게 한다.
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
            "top_suppliers": [], "korea_supplier": None, "korea_rank": None,
            "supplier_ranked_count": 0,
        }

    value_col = _find_column(df, ["primaryValue"], "수입액")
    # cmdDesc: UN Comtrade가 공식으로 관리하는 이 HS코드의 품목 설명(영문).
    # 원래는 사용자가 제품명을 따로 입력받아 화면/AI에 썼는데, 사람이 타이핑한
    # 이름이 HS코드와 실제로 다른 품목을 가리킬 위험이 있어서(예: HS코드는
    # 감자칩인데 이름은 "김치"라고 잘못 입력) 그 입력 자체를 없애고, 대신
    # 이 공식 설명을 화면 제목과 AI 분석 양쪽에 쓴다.
    cmd_desc_col = _find_column_optional(df, ["cmdDesc"])
    item_desc = str(df[cmd_desc_col].iloc[0]) if cmd_desc_col and not df[cmd_desc_col].isna().all() else None

    if not is_mirror:
        # 일반 모드: "상대국"은 partnerCode 컬럼에, World 합계는 partnerCode='0' 행에 있다.
        country_code_col = _find_column(df, ["partnerCode"], "파트너국 코드")
        label_col = _find_column_optional(df, ["partnerDesc"])
        iso_col = _find_column_optional(df, ["partnerISO"])
        world_rows = df[df[country_code_col].astype(str) == "0"]
        total = float(world_rows[value_col].iloc[0]) if not world_rows.empty else None
        other_rows = df[df[country_code_col].astype(str) != "0"][value_col].dropna()
    else:
        # 미러 모드: 이제 "상대국"(=수출한 나라)은 reporterCode 컬럼에 있고,
        # World 합계 행 자체가 없으므로 모든 행의 값을 직접 더해서 총액을 만든다.
        country_code_col = _find_column(df, ["reporterCode"], "보고국 코드")
        label_col = _find_column_optional(df, ["reporterDesc"])
        iso_col = _find_column_optional(df, ["reporterISO"])
        clean_values = df[value_col].dropna()
        total = float(clean_values.sum()) if not clean_values.empty else None
        other_rows = clean_values

    # 공급국 다양성(supplier_country_count): "이 나라가 이 품목을 몇 개국에서
    # 수입해오는가". 일반 모드는 World 합계 행을 뺀 나머지, 미러 모드는 전체
    # 행(각 행 자체가 서로 다른 수출국 1개)에서 값이 0보다 큰 행을 센다.
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
            "share_pct": _round_share(share),
        })
    breakdown.sort(key=lambda x: x["import_value_usd"], reverse=True)

    try:
        korea_codes = set(candidate_reporter_codes("KOR", proxy_url=proxy_url))
    except Exception:
        korea_codes = set()
    suppliers = _supplier_table(
        df, value_col, country_code_col, label_col, iso_col, total, korea_codes, TOP_SUPPLIERS_N,
    )

    return {
        "total_import_usd": total, "breakdown": breakdown, "year": year, "item_desc": item_desc,
        "supplier_country_count": supplier_country_count, "is_mirror_estimate": is_mirror,
        **suppliers,
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
    # get_competitiveness()와 같은 이유: comtradeapicall이 한 나라에 국가코드를
    # 여러 개 돌려줄 수 있다 (예: 독일 DEU -> "280,276", 280은 통일 이전
    # 서독). 후보를 전부 모아서 실제로 데이터가 나오는 코드를 찾는다.
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

    # get_competitiveness()와 같은 이유의 미러 폴백: 후보 코드를 전부 시도해도
    # 빈 응답이면(실사례로 검증됨: 미국), 전세계 각국이 "우리가 타깃국에
    # 수출했다"고 보고한 값들을 연도별로 합산해서 대신 쓴다.
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
            "by_year": [], "cagr_pct": None, "cagr_start_year": None, "cagr_end_year": None,
            "latest_valid_year": None, "years_requested": years, "years_with_data": 0,
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
        # 미러 모드에서는 한 연도에 여러 수출국 행이 섞여 있으니 연도별로 합산한다.
        grouped = clean.groupby(year_col)[value_col].sum().sort_index()
        by_year = [{"year": int(y), "import_value_usd": float(v)} for y, v in grouped.items()]

    # 최신 연도 "집계 미완" 판정: 예전에는 최신 연도에 무조건 경고를 붙여서
    # 모든 나라에 같은 경고가 떴다. 이제는 "요청한 가장 최근 연도의 값이 직전
    # 연도보다 30% 이상 급감한 경우"에만 집계 미완 가능성으로 표시하고, 그 연도는
    # CAGR 계산에서 뺀다 (진짜 급감일 수도 있으니 값 자체는 그대로 보여준다).
    latest_requested_year = max(years)
    for i, y in enumerate(by_year):
        prev = by_year[i - 1]["import_value_usd"] if i > 0 else None
        y["may_be_incomplete"] = bool(
            y["year"] == latest_requested_year and prev
            and y["import_value_usd"] < prev * INCOMPLETE_DROP_RATIO
        )

    valid = [y for y in by_year if not y["may_be_incomplete"]]
    cagr = None
    cagr_start_year = cagr_end_year = None
    if len(valid) >= 2:
        start, end = valid[0], valid[-1]
        cagr = calc_cagr(start["import_value_usd"], end["import_value_usd"], end["year"] - start["year"])
        cagr_start_year, cagr_end_year = start["year"], end["year"]

    return {
        "by_year": by_year,
        "cagr_pct": cagr,
        "cagr_start_year": cagr_start_year,   # CAGR 계산에 실제로 쓴 첫 해
        "cagr_end_year": cagr_end_year,       # CAGR 계산에 실제로 쓴 마지막 해
        "latest_valid_year": valid[-1]["year"] if valid else None,
        "years_requested": years,      # 사용자가 요청한 연도 (실제로 데이터가 다 있으리라는 보장은 없음)
        "years_with_data": len(by_year),  # 실제로 응답에 들어있던 연도 수
        "is_mirror_estimate": is_mirror,
    }


def _friendly_ai_error(e):
    """OpenAI 오류를 화면에 보여줄 짧은 한국어 설명으로 바꾼다 (원문도 함께)."""
    text = str(e)
    low = text.lower()
    if "insufficient_quota" in low or "exceeded your current quota" in low:
        hint = "OpenAI 사용 한도(크레딧)가 소진됐습니다. OpenAI 결제/사용량 페이지를 확인해주세요."
    elif "rate limit" in low or "429" in low:
        hint = "OpenAI 호출이 잠시 너무 많았습니다. 잠시 후 다시 시도해주세요."
    elif "401" in low or "api key" in low or "api_key" in low:
        hint = "OpenAI API 키가 올바르지 않습니다. .env의 OPENAI_API_KEY를 확인해주세요."
    elif "model" in low and ("not found" in low or "does not exist" in low):
        hint = "설정된 AI 모델을 사용할 수 없습니다. 모델 이름을 확인해주세요."
    elif "timeout" in low or "timed out" in low or "connection" in low:
        hint = "OpenAI 서버에 연결하지 못했습니다(네트워크/시간 초과). 잠시 후 다시 시도해주세요."
    else:
        hint = "AI 해석 중 예상치 못한 오류가 발생했습니다."
    return f"{hint} (원문: {text[:200]})"


def _pct_change(new, old):
    if new is None or not old:
        return None
    return round((new / old - 1) * 100, 1)


def derive_detail_metrics(result):
    """국가 상세 화면과 AI 해석에 함께 쓰는 "계산된 지표"를 만든다.
    AI에게 원자료만 주면 증감률·집중도 같은 계산을 스스로 하다가 틀리는 경우가 있어서,
    필요한 숫자는 파이썬에서 정확히 계산해 넘기고 AI는 해석만 하게 한다."""
    growth = result.get("growth_trend") or {}
    comp = result.get("competitiveness") or {}
    ke = result.get("korea_exports_customs") or {}

    customs_by_year = {}
    if ke.get("available"):
        customs_by_year = {y["year"]: y["export_usd"] for y in ke.get("by_year") or []}

    # 연도별 표: 그 나라 수입액 + 전년 대비, 한국 수출액(관세청) + 전년 대비
    rows = []
    prev_imp = None
    by_year = growth.get("by_year") or []
    for y in by_year:
        imp = y["import_value_usd"]
        kx = customs_by_year.get(y["year"])
        kx_prev = customs_by_year.get(y["year"] - 1)
        note = None
        if y.get("may_be_incomplete"):
            note = "직전 연도보다 30% 이상 급감 — 집계 미완 가능성 (CAGR 계산 제외)"
        rows.append({
            "year": y["year"],
            "import_usd": imp,
            "import_yoy_pct": _pct_change(imp, prev_imp),
            "korea_export_usd": kx,
            "korea_export_yoy_pct": _pct_change(kx, kx_prev) if kx is not None else None,
            "note": note,
        })
        prev_imp = imp
    # 관세청에는 있는데 UN Comtrade에는 아직 없는 연도(예: 최신 연도)도 표에 보여준다
    known = {r["year"] for r in rows}
    for yr in sorted(customs_by_year):
        if yr not in known and (not rows or yr > rows[-1]["year"]):
            rows.append({
                "year": yr, "import_usd": None, "import_yoy_pct": None,
                "korea_export_usd": customs_by_year[yr],
                "korea_export_yoy_pct": _pct_change(customs_by_year[yr], customs_by_year.get(yr - 1)),
                "note": "상대국 수입 통계 미발표 (한국 수출만 집계됨)",
            })

    tops = comp.get("top_suppliers") or []
    top1 = tops[0] if tops else None
    top3_share = round(sum((t.get("share_pct") or 0) for t in tops[:3]), 1) if tops else None
    korea = comp.get("korea_supplier")

    valid = [y for y in by_year if not y.get("may_be_incomplete")]
    abs_growth = None
    if len(valid) >= 2:
        abs_growth = valid[-1]["import_value_usd"] - valid[0]["import_value_usd"]

    kx_years = sorted(y for y, v in customs_by_year.items() if v)
    korea_export_cagr = None
    if len(kx_years) >= 2:
        korea_export_cagr = calc_cagr(
            customs_by_year[kx_years[0]], customs_by_year[kx_years[-1]], kx_years[-1] - kx_years[0]
        )

    return {
        "yearly_rows": rows,
        "has_notes": any(r["note"] for r in rows),
        "has_customs": bool(customs_by_year),
        "market": {
            "data_year": comp.get("year"),
            "total_import_usd": comp.get("total_import_usd"),
            "cagr_pct": growth.get("cagr_pct"),
            "cagr_period": (
                f"{growth.get('cagr_start_year')}~{growth.get('cagr_end_year')}"
                if growth.get("cagr_start_year") else None
            ),
            "import_increase_usd_over_period": abs_growth,
            "supplier_country_count": comp.get("supplier_country_count"),
            "top1_supplier": {"label": top1["label"], "share_pct": top1["share_pct"]} if top1 else None,
            "top3_suppliers_combined_share_pct": top3_share,
            "is_mirror_estimate": bool(comp.get("is_mirror_estimate") or growth.get("is_mirror_estimate")),
        },
        "korea": {
            "rank_among_suppliers": comp.get("korea_rank"),
            "supplier_ranked_count": comp.get("supplier_ranked_count"),
            "share_pct_partner_reported": korea.get("share_pct") if korea else 0.0,
            "import_from_korea_usd_partner_reported": korea.get("import_value_usd") if korea else 0.0,
            "gap_to_top1_share_pctp": (
                round((top1["share_pct"] or 0) - (korea.get("share_pct") or 0), 2) if (top1 and korea) else None
            ),
            "customs_export_cagr_pct": korea_export_cagr,
            "customs_export_period": f"{kx_years[0]}~{kx_years[-1]}" if len(kx_years) >= 2 else None,
            "customs_ytd": ke.get("ytd") if ke.get("available") else None,
        },
    }


DETAIL_AI_KEYS = (
    "summary", "market_attractiveness", "competitive_position", "korea_position",
    "risks", "strategic_recommendation", "action_items",
)


def has_detailed_ai(ai):
    """새 형식(자세한 버전)의 AI 해석인지. 예전 3문단짜리 캐시는 다시 만든다."""
    return bool(ai) and all(k in ai for k in ("summary", "korea_position", "action_items"))


def interpret_with_llm(client, model, official_item_desc, hscode, target_country, ranking, competitiveness, growth,
                       korea_exports=None, derived=None):
    """[4단계] 수치 전체를 OpenAI에게 주고 전략적 시사점을 한국어로 "자세히" 작성.
    - 주어진 수치만 쓰게 하고(할루시네이션 방지), 증감률·집중도 같은 계산값은
      derive_detail_metrics()가 미리 계산해서 넘긴다.
    - 경쟁국은 실제 상위 공급국 순위(top_suppliers)에서만 고르게 한다.
    - 품목명은 UN Comtrade 공식 설명(official_item_desc)을 기준으로 한다."""
    comp = dict(competitiveness)
    comp.pop("item_desc", None)
    comp.pop("breakdown", None)  # 고정 비교국 표는 순위가 아니라 혼동만 줘서 AI에는 넘기지 않음
    derived = derived or {}
    payload = {
        "official_item_desc_en": official_item_desc or "(UN Comtrade 응답에 설명 없음)",
        "hscode": hscode,
        "target_country": target_country,
        "computed_metrics": {k: derived.get(k) for k in ("market", "korea")},
        "yearly_table": derived.get("yearly_rows"),
        "top_suppliers": comp.get("top_suppliers"),
        "global_import_ranking_top": ranking[:10],
        "korea_exports_customs": korea_exports if (korea_exports or {}).get("available") else None,
    }
    prompt = f"""당신은 KOTRA 무역관 수준의 시장 분석가입니다. 아래 [데이터]는 UN Comtrade 공식 무역통계와
한국 관세청 수출 통계입니다. 한국 중소 수출기업 담당자가 바로 의사결정에 쓸 수 있도록
"{target_country}" 시장 분석 보고서를 자세하게 작성하세요.

[반드시 지킬 규칙]
1. [데이터]에 있는 수치만 사용하세요. 기업명, 소비자 성향, 규제, 관세율, 유통 구조처럼 데이터에
   없는 사실은 절대 지어내지 마세요. 필요하면 "통계만으로는 확인할 수 없어 현지 조사가 필요"라고 쓰세요.
2. 각 문단은 근거 수치를 2개 이상 인용하세요. 금액은 "약 23억 달러", "약 4,500만 달러"처럼 읽기 쉽게,
   비율은 소수점 한두 자리까지 쓰세요. 0.01보다 작은 점유율은 "0.01% 미만"이라고 쓰세요.
3. 성장률을 말할 때는 기간(computed_metrics.market.cagr_period)을 함께 밝히세요.
4. 경쟁 구도는 top_suppliers(이 시장의 실제 수입 상대국 순위)만 근거로 하세요. {target_country}
   자신은 절대 경쟁국으로 언급하지 마세요. top3_suppliers_combined_share_pct로 시장 집중도를 평가하세요.
5. 한국 현황은 두 출처를 구분하세요: 상대국이 신고한 한국산 수입(CIF, computed_metrics.korea의
   partner_reported 값)과 한국 관세청 수출(FOB, yearly_table.korea_export_usd, customs_ytd).
   한국의 실제 수출 흐름은 관세청 값을 우선하고, 올해 누계(customs_ytd)가 있으면 전년 동기 대비를 언급하세요.
6. yearly_table의 note가 있는 연도는 집계 미완 가능성이 있으니 그 연도만으로 "역성장"이라 단정하지 마세요.
7. is_mirror_estimate가 true면 "상대국 보고 기반 추정치"라는 점을 시장 매력도 문단에서 밝히세요.
8. 과장된 표현(예: "엄청난", "반드시 성공")을 쓰지 말고, 담당자에게 보고하는 담백한 문체로 쓰세요.

[데이터]
{json.dumps(payload, ensure_ascii=False, indent=2)}
[데이터 끝]

아래 JSON 형식으로만 응답하세요. 각 항목의 분량을 지켜주세요.
{{
  "summary": "핵심 결론 1~2문장 (이 시장을 어떻게 봐야 하는지 한 줄 요약)",
  "market_attractiveness": "시장 규모, 성장률(기간 포함), 기간 중 늘어난 수입 금액, 최근 연도 흐름을 4~6문장으로",
  "competitive_position": "상위 공급국과 점유율, 상위 3개국 집중도, 공급국 수, 1위와 한국의 격차를 4~6문장으로",
  "korea_position": "한국의 공급국 순위와 점유율, 관세청 기준 수출 추이와 연평균 증감, 올해 누계(전년 동기 대비)를 3~5문장으로",
  "risks": ["데이터로 확인되는 위험 요인 또는 주의점 2~4개 (각 1문장, 근거 수치 포함)"],
  "strategic_recommendation": "위 분석을 종합한 진출 전략 방향 3~5문장",
  "action_items": ["담당자가 다음에 할 구체적 실행 과제 3~5개 (각 1문장)"]
}}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(response.choices[0].message.content)
        for k in ("risks", "action_items"):
            if isinstance(data.get(k), str):
                data[k] = [data[k]]
            data.setdefault(k, [])
        for k in ("summary", "market_attractiveness", "competitive_position", "korea_position",
                  "strategic_recommendation"):
            data.setdefault(k, "")
        return data, None
    except Exception as e:
        print(f"AI 해석 생성 실패: {e}")
        return None, _friendly_ai_error(e)  # 실패해도 원본 수치는 그대로 보여줌


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


def get_cached_market_research(hscode: str, target_country: str, ttl_days: int = CACHE_TTL_DAYS,
                                db_path: str | None = None, years: list[int] | None = None):
    """네트워크 호출 없이 캐시만 읽는다 (화면 표시용 - 박람회 상세 페이지를
    열 때마다 UN Comtrade/OpenAI를 부르면 느리고 API 한도도 금방 닳으므로,
    실제 조회는 "조사하기" 버튼을 눌러야만 실행되게 하기 위함). 캐시 없으면 None."""
    if not HSCODE_RE.match(hscode):
        return None
    try:
        target_iso3 = resolve_iso3(target_country)
    except ValueError:
        return None
    if years is None:
        years, _ = default_years()
    years = sorted(years)
    cache_key = f"{target_iso3}|{years[0]}-{years[-1]}"

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        ensure_schema(conn)
        result = _load_cache(conn, hscode, cache_key, ttl_days)
        if result:
            result["derived"] = derive_detail_metrics(result)
        return result
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
    reporter_code: str | None = None,
    iso3_hint: str | None = None,
    include_ai: bool = True,
) -> dict:
    """공개 인터페이스. 다른 코드는 이 함수 하나만 알면 된다.

    UN Comtrade API는 HS코드로만 통계를 분류하고 자연어 제품명은 전혀
    이해하지 못하므로, 입력은 HS코드(6자리)만 받는다. 화면에 보여줄 품목
    이름은 UN Comtrade가 직접 돌려주는 공식 설명(official_item_desc)을 쓴다.

    reporter_code: 매트릭스 후보국처럼 UN Comtrade 숫자 국가코드를 이미 알고
    있으면 넘긴다. 이때는 국가명 -> ISO3 변환을 건너뛰므로, 매핑표에 없는
    나라(예: 자동 후보로 뽑힌 "Austria")도 상세 조사가 된다. target_country는
    화면 표시용 이름으로만 쓰인다.

    반환 스키마:
        {
            "hscode": str, "target_country": str,
            "official_item_desc": str | None,
            "years": [int, int, int],
            "global_import_ranking": [{"country", "import_value_usd"}, ...],  # 상위 10개국
            "competitiveness": {
                "total_import_usd", "year",
                "breakdown": [{"country_iso3", "import_value_usd", "share_pct"}, ...],  # 고정 비교국
                "top_suppliers": [{"rank", "label", "iso3", "code", "import_value_usd",
                                   "share_pct", "is_korea"}, ...],  # 실제 상위 공급국
                "korea_supplier": {...} | None, "korea_rank": int | None,
                "supplier_ranked_count": int,
            },
            "growth_trend": {
                "by_year": [{"year", "import_value_usd", "may_be_incomplete"}, ...],
                "cagr_pct", "cagr_start_year", "cagr_end_year", "latest_valid_year",
                "years_requested", "years_with_data",
            },
            "korea_exports_customs": {"available", "by_year", "ytd", ...},  # 관세청 기준 한국 수출
            "ai_insight": {"market_attractiveness","competitive_position",
                            "strategic_recommendation"} | None,
            "fetched_at": ISO8601, "from_cache": bool,
        }
    """
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")

    if reporter_code:
        target_iso3 = None
        target_label = target_country.strip() or f"code:{reporter_code}"
        cache_key = f"code:{reporter_code}"
        customs_iso3 = iso3_hint
    else:
        target_iso3 = resolve_iso3(target_country)
        target_label = target_iso3
        cache_key = target_iso3
        customs_iso3 = target_iso3

    if years is None:
        years, ranking_year = default_years()
    else:
        years = sorted(years)
        ranking_year = years[-1]
    years = sorted(years)
    cache_key = f"{cache_key}|{years[0]}-{years[-1]}"

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    ensure_schema(conn)

    try:
        result = None if force else _load_cache(conn, hscode, cache_key, ttl_days)

        if result is None:
            try:
                _, subscription_key = get_config()
                ranking = get_global_import_ranking(subscription_key, hscode, ranking_year, proxy_url=proxy_url)
                # 성장 추이를 먼저 받아서 "이 나라 통계가 실제로 있는 가장 최신 연도"를
                # 찾고, 시장 경쟁력(공급국 순위)은 그 연도 기준으로 조회한다.
                growth = get_growth_trend(
                    subscription_key, hscode, target_iso3, years,
                    proxy_url=proxy_url, reporter_code=reporter_code,
                )
                data_year = growth.get("latest_valid_year") or ranking_year
                competitiveness = get_competitiveness(
                    subscription_key, hscode, target_iso3, data_year, competitors,
                    proxy_url=proxy_url, reporter_code=reporter_code,
                )
                korea_exports = get_korea_exports(
                    hscode, customs_iso3, years, include_ytd=True, force=force,
                )
            except Exception:
                print(f"[un_comtrade] {hscode}/{target_label} 조사 중 오류:")
                traceback.print_exc()
                raise

            result = {
                "hscode": hscode,
                "target_country": target_label,
                "official_item_desc": competitiveness.get("item_desc"),  # UN Comtrade 공식 품목 설명
                "years": years,
                "global_import_ranking": ranking,
                "competitiveness": competitiveness,
                "growth_trend": growth,
                "korea_exports_customs": korea_exports,
                "ai_insight": None,
                "ai_error": None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "from_cache": False,
            }
            # 숫자 데이터는 AI 해석 전에 먼저 저장한다 -> AI가 실패하거나 아직 안 끝나도
            # 다음에 같은 나라를 열 때 UN Comtrade를 다시 부르지 않는다.
            _save_cache(conn, hscode, cache_key, result)

        else:
            # 관세청 값은 자체 캐시(과거 연도 90일, 지난해 7일, 올해 누계 3일)를 따로 갖고 있어서
            # 매번 다시 읽어도 빠르다. 이렇게 해야 (1) 일시적인 관세청 오류가 30일 동안
            # 굳어지지 않고 (2) 올해 누계가 최신으로 유지된다.
            fresh = get_korea_exports(hscode, customs_iso3, years, include_ytd=True)
            if fresh.get("available") or not (result.get("korea_exports_customs") or {}).get("available"):
                result["korea_exports_customs"] = fresh

        result["derived"] = derive_detail_metrics(result)

        # AI 해석: 아직 없으면 만든다 (include_ai=False면 화면이 나중에 따로 요청)
        if include_ai and not has_detailed_ai(result.get("ai_insight")):
            openai_client, _ = get_config()
            ai_insight, ai_error = interpret_with_llm(
                openai_client, model, result.get("official_item_desc"), hscode,
                result["target_country"], result.get("global_import_ranking") or [],
                result["competitiveness"], result["growth_trend"],
                result.get("korea_exports_customs"), result["derived"],
            )
            result["ai_insight"] = ai_insight
            result["ai_error"] = ai_error
            if ai_insight is not None:
                to_save = {k: v for k, v in result.items() if k not in ("derived", "from_cache")}
                _save_cache(conn, hscode, cache_key, to_save)
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS un_comtrade_matrix_result_cache (
            hscode TEXT NOT NULL,
            result_key TEXT NOT NULL,
            result_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (hscode, result_key)
        )
        """
    )
    conn.commit()


def _load_result_cache(conn, hscode, result_key, ttl_days):
    row = conn.execute(
        "SELECT result_json, fetched_at FROM un_comtrade_matrix_result_cache WHERE hscode=? AND result_key=?",
        (hscode, result_key),
    ).fetchone()
    if not row:
        return None
    fetched = datetime.fromisoformat(row[1])
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched > timedelta(days=ttl_days):
        return None
    result = json.loads(row[0])
    result["from_cache"] = True
    return result


def _save_result_cache(conn, hscode, result_key, result):
    conn.execute(
        """
        INSERT INTO un_comtrade_matrix_result_cache (hscode, result_key, result_json, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(hscode, result_key) DO UPDATE SET
            result_json=excluded.result_json, fetched_at=excluded.fetched_at
        """,
        (hscode, result_key, json.dumps(result, ensure_ascii=False), result.get("fetched_at")
         or datetime.now(timezone.utc).isoformat()),
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
    iso3_hint=None, fallback_year=None, force=False,
):
    """후보국 1개의 매트릭스 좌표(성장률, 한국 점유율)를 계산한다.
    competitors에 KOR을 항상 강제로 포함시켜서, 후보국이 어떤 나라든
    한국 점유율은 반드시 계산되게 한다.

    성장 추이를 먼저 조회해서 이 나라 통계가 실제로 있는 가장 최신 연도(data_year)를
    찾고, 한국 점유율은 그 연도 기준으로 계산한다 (나라마다 통계 확정 시점이 달라서)."""
    growth = get_growth_trend(
        subscription_key, hscode, target_iso3, years, proxy_url=proxy_url, reporter_code=reporter_code,
    )
    data_year = growth.get("latest_valid_year") or fallback_year or max(years)
    competitiveness = get_competitiveness(
        subscription_key, hscode, target_iso3, data_year,
        competitors=["KOR"], proxy_url=proxy_url, reporter_code=reporter_code,
    )

    korea_row = next((b for b in competitiveness["breakdown"] if b["country_iso3"] == "KOR"), None)
    korea_share_pct = korea_row["share_pct"] if korea_row else None
    korea_import_usd = korea_row["import_value_usd"] if korea_row else None

    valid = [y for y in growth["by_year"] if not y.get("may_be_incomplete")]
    import_growth_usd = None
    if len(valid) >= 2:
        import_growth_usd = valid[-1]["import_value_usd"] - valid[0]["import_value_usd"]

    # 한국 측 통계(관세청)로 같은 연도 한국 -> 이 나라 수출액을 교차 확인
    customs_iso3 = target_iso3 or iso3_hint
    customs = get_korea_exports(hscode, customs_iso3, [data_year], force=force)
    customs_export = None
    if customs.get("available") and customs.get("by_year"):
        customs_export = customs["by_year"][0]["export_usd"]

    top = competitiveness.get("top_suppliers") or []
    return {
        "label": label,
        "data_year": data_year,
        "total_import_usd": competitiveness["total_import_usd"],
        "korea_import_usd": korea_import_usd,          # 상대국이 신고한 한국산 수입액 (CIF)
        "korea_share_pct": korea_share_pct,
        "korea_export_customs_usd": customs_export,     # 한국 관세청 기준 한국 수출액 (FOB)
        "customs_note": None if customs.get("available") else customs.get("reason"),
        "cagr_pct": growth["cagr_pct"],
        "cagr_start_year": growth.get("cagr_start_year"),
        "cagr_end_year": growth.get("cagr_end_year"),
        # 기간 동안 수입액이 "몇 달러" 늘었는지 (성장률 %만 보면 작은 시장이
        # 과대평가되는 문제를 보완하기 위해 AI 판단에 함께 넘김)
        "import_growth_usd": import_growth_usd,
        "korea_rank": competitiveness.get("korea_rank"),
        "top_supplier": (
            {"label": top[0]["label"], "share_pct": top[0]["share_pct"]} if top else None
        ),
        "years_with_data": growth["years_with_data"],
        "may_be_incomplete_latest_year": any(y.get("may_be_incomplete") for y in growth["by_year"]),
        "item_desc": competitiveness.get("item_desc"),
        "supplier_country_count": competitiveness.get("supplier_country_count"),
        "is_mirror_estimate": bool(competitiveness.get("is_mirror_estimate") or growth.get("is_mirror_estimate")),
    }


def interpret_matrix_with_llm(client, model, official_item_desc, hscode, candidates, thresholds,
                              korea_presence="meaningful"):
    """4분면에 흩뿌려진 후보국들을 보고 우선순위와 이유를 한국어로 정리.
    예전에는 성장률(%)과 점유율만 보고 골라서, 한국산 수입이 연 3만 달러
    수준인 작은 시장이 "우선 공략"으로 추천되는 문제가 있었다. 이제 시장
    규모(total_import_usd)와 실제 증가 금액(import_growth_usd)도 함께 보게 한다."""
    slim = []
    for c in candidates:
        slim.append({k: c.get(k) for k in (
            "label", "quadrant", "data_year", "total_import_usd", "import_growth_usd", "cagr_pct",
            "cagr_start_year", "cagr_end_year", "korea_share_pct", "korea_import_usd",
            "korea_export_customs_usd", "korea_rank", "top_supplier", "import_rank",
            "is_small_market", "may_be_incomplete_latest_year", "is_mirror_estimate",
            "is_focus",
        )})
    payload = {
        "official_item_desc_en": official_item_desc or "(UN Comtrade 응답에 설명 없음)",
        "hscode": hscode,
        "thresholds": thresholds,
        "korea_presence": korea_presence,
        "comparison_size": len(slim),
        "candidates": slim,
    }
    prompt = f"""당신은 글로벌 무역 컨설턴트입니다. 아래 [데이터]는 여러 후보
국가에 대해 UN Comtrade 공식 무역통계로 계산한 "성장률 x 한국 점유율"
매트릭스 좌표입니다. 이 안에 있는 수치만 사용하고 새 숫자나 사실을 지어내지 마세요.

각 후보국의 quadrant 필드는 이미 계산되어 있습니다. 한국 점유율 "높음"의 기준은
thresholds.share_threshold_pct입니다 (후보국 평균과 최소 {MIN_MEANINGFUL_KOREA_SHARE_PCT}% 중 큰 값):
- "집중 공략": 시장 성장률도 평균 이상, 한국 점유율도 기준 이상
- "경쟁력 강화 필요": 시장은 평균 이상으로 크는데 한국 점유율은 낮음
- "현상 유지/수확": 한국 점유율은 높지만 시장 성장은 평균 이하로 둔화
- "우선순위 낮음": 성장률도 점유율도 평균 이하

우선 공략 후보를 고를 때는 성장률(%)과 점유율만 보지 말고 반드시 아래도 함께 따지세요:
- total_import_usd(시장 규모): 성장률이 높아도 시장이 작으면 실제 기회는 작습니다.
- import_growth_usd(기간 중 실제로 늘어난 수입 금액): 성장률 %보다 실제 기회의 크기를 더 잘 보여줍니다.
- korea_import_usd / korea_rank: 한국산이 이미 어느 정도 들어가 있는지(교두보 여부).
- top_supplier: 1위 공급국 점유율이 압도적이면 진입 장벽이 높을 수 있습니다.
한국산 수입이 극히 적고(예: 수만 달러) 시장 규모도 상대적으로 작은 나라를 추천한다면,
그 한계를 이유에 분명히 적으세요.

is_focus가 true인 국가는 사용자가 관심 국가로 직접 입력한 나라입니다. top_priority_markets
선정은 공정하게 하되, 관심 국가가 추천에서 빠졌다면 overall_strategy에서 그 이유를 한 문장으로
설명하세요. comparison_size가 3 미만이면 평균 기준선이 의미가 없어 quadrant가 null입니다.
이때는 사분면 대신 각 나라의 시장 규모·성장률·한국 현황을 직접 평가하세요.

korea_presence가 "negligible"이면 모든 후보국에서 한국 점유율이 기준 미만이라, 이
품목은 한국이 아직 거의 수출하지 않는 품목입니다. 이때는 점유율 차이로 우열을
가리지 말고 시장 규모·증가 금액·1위 공급국 집중도 위주로 "신규 진출 후보"를 고르고,
그 사실을 overall_strategy 첫 문장에 밝히세요.
cagr_pct는 cagr_start_year~cagr_end_year 구간의 연평균 성장률입니다. is_small_market이
true인 시장은 금액이 작아 성장률 변동이 크니 성장률만으로 추천하지 마세요.
korea_export_customs_usd는 한국 관세청 기준 한국의 수출액(FOB)으로, korea_import_usd
(상대국 신고, CIF)보다 한국의 실제 실적에 더 가깝습니다. 둘 다 있으면 관세청 값을 우선하세요. korea_share_pct는 % 단위이며 0.003처럼 매우 작을 수 있습니다 - 이는 "0%"가
아니라 "0.01% 미만"입니다. is_mirror_estimate가 true인 후보국은 "공식 발표가 아닌
추정치"라는 점을 짧게 밝히세요. 국가는 label 그대로 부르세요.

[데이터]
{json.dumps(payload, ensure_ascii=False, indent=2)}
[데이터 끝]

한국 중소기업 관점에서 담당자에게 보고하는 담백한 문체로 작성하세요. 금액은 "약 23억 달러"처럼
읽기 쉽게 쓰고, 성장률에는 기간(cagr_start_year~cagr_end_year)을 함께 밝히세요.
1) key_findings: 비교 국가 전체에서 데이터로 드러나는 핵심 사실 3~4개 (각 1문장, 근거 수치 포함)
2) top_priority_markets: 우선 공략 국가 1~3개와 이유 (이유는 2~3문장, 시장 규모·증가 금액·한국 현황
   중 근거 수치 2개 이상 포함)
3) watch_markets: 지금 당장은 아니지만 지켜볼 국가 0~2개와 이유 (1~2문장)
4) overall_strategy: 전체 비교 국가를 종합한 전략 방향 (사분면별 또는 시장 유형별 접근 차이 포함, 4~6문장)

반드시 아래 JSON 형식으로만 응답하세요:
{{"key_findings": ["..."], "top_priority_markets": [{{"label": "...", "reason": "..."}}], "watch_markets": [{{"label": "...", "reason": "..."}}], "overall_strategy": "..."}}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content), None
    except Exception as e:
        print(f"AI 매트릭스 해석 생성 실패: {e}")
        return None, _friendly_ai_error(e)


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
    include_ai: bool = True,
    retry_customs: bool = True,
) -> dict:
    """공개 인터페이스: 후보국 여러 개를 "성장률 x 한국 점유율" 매트릭스
    위에서 한 번에 비교한다 (KOTRA TriBig류 전문 무역조사기관 방식).

    candidate_countries (관심 국가):
        - ["VNM", "태국", "Philippines"] 처럼 ISO3/국가명 리스트. 수입 상위 top_n개국과
          "합쳐서" 비교한다 (이미 상위권에 있으면 중복 없이 관심 표시만 붙음).
          인식할 수 없는 이름은 전체를 실패시키지 않고 excluded에 사유와 함께 넣는다.
        - None: 수입 상위 top_n개국만 비교한다.
    top_n: 자동으로 넣을 수입 상위 국가 수. 0이면 관심 국가만 비교한다.

    반환 스키마:
        {
            "hscode", "official_item_desc", "years",
            "thresholds": {"avg_cagr_pct", "avg_korea_share_pct"},
            "candidates": [
                {"label", "iso3", "reporter_code", "total_import_usd", "korea_import_usd",
                 "korea_share_pct", "korea_export_customs_usd", "cagr_pct", "cagr_start_year",
                 "cagr_end_year", "data_year", "is_small_market", "import_growth_usd",
                 "korea_rank", "top_supplier", "quadrant", "import_rank",
                 "years_with_data", "may_be_incomplete_latest_year"},
                ...
            ],
            "excluded": [{"label", "reason"}, ...],
            "ai_summary": {"top_priority_markets", "overall_strategy"} | None,
            "fetched_at", "from_cache",
        }
    """
    if not HSCODE_RE.match(hscode):
        raise ValueError(f"HS코드 형식이 올바르지 않습니다: {hscode!r} (국제 공통 6자리 숫자)")

    if years is None:
        years, ranking_year = default_years()
    else:
        years = sorted(years)
        ranking_year = years[-1]
    years = sorted(years)
    years_key = ",".join(str(y) for y in years)

    db_path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    ensure_multi_schema(conn)

    # 같은 조건(HS코드·연도·비교 국가 수·관심 국가)의 비교 결과 전체를 캐시한다.
    # 국가 탭을 누를 때마다 순위 조회·후보국 계산·AI 해석을 다시 하던 것이
    # 탭 전환이 느렸던 주된 원인이었다.
    focus_key = "|".join((c or "").strip().lower() for c in (candidate_countries or []))
    result_key = f"{years_key}|top{top_n}|{focus_key}"

    try:
        result = None if force else _load_result_cache(conn, hscode, result_key, ttl_days)
        if result is None:
            result = _compute_comparison(
                conn, hscode, candidate_countries, top_n, years, years_key, ranking_year,
                ttl_days, force, proxy_url,
            )
            _save_result_cache(conn, hscode, result_key, result)

        elif retry_customs and _retry_failed_customs(hscode, result):
            _save_result_cache(conn, hscode, result_key, result)

        if include_ai and not result.get("ai_summary"):
            openai_client, _ = get_config()
            ai_summary, ai_error = interpret_matrix_with_llm(
                openai_client, model, result.get("official_item_desc"), hscode,
                result["candidates"], result["thresholds"],
                korea_presence=result.get("korea_presence", "meaningful"),
            )
            result["ai_summary"] = ai_summary
            result["ai_error"] = ai_error
            if ai_summary is not None:
                _save_result_cache(conn, hscode, result_key, result)
        return result
    finally:
        conn.close()


def _retry_failed_customs(hscode, result):
    """저장된 비교 결과 중 관세청 조회가 "일시적으로" 실패했던 나라만 다시 조회한다.
    (키가 없거나 국가코드 매핑이 없는 경우는 다시 해도 같으므로 건너뜀) 바뀐 게 있으면 True."""
    changed = False
    for c in result.get("candidates", []):
        note = c.get("customs_note") or ""
        if c.get("korea_export_customs_usd") is None and "조회 실패" in note and c.get("data_year"):
            fresh = get_korea_exports(hscode, c.get("iso3"), [c["data_year"]])
            if fresh.get("available") and fresh.get("by_year"):
                c["korea_export_customs_usd"] = fresh["by_year"][0]["export_usd"]
                c["customs_note"] = None
                changed = True
    return changed


def _compute_comparison(conn, hscode, candidate_countries, top_n, years, years_key, ranking_year,
                        ttl_days, force, proxy_url):
    """get_multi_country_comparison()의 실제 계산 부분 (AI 해석 제외)."""
    if True:  # (들여쓰기를 기존 코드와 맞추기 위한 블록)
        _, subscription_key = get_config()

        # 비교 대상 = 수입 상위 top_n개국(자동) + 사용자가 입력한 관심 국가 (합집합).
        # 예전에는 관심 국가를 입력하면 자동 후보가 통째로 사라져서, 한 나라만 넣으면
        # 매트릭스에 점 하나만 남고 평균 기준선도 의미가 없어지는 문제가 있었다.
        targets = []  # [{"label", "iso3"|None, "reporter_code"|None, "iso3_hint", "is_focus"}]
        excluded = []
        if top_n and top_n > 0:
            ranking = get_global_import_ranking(
                subscription_key, hscode, ranking_year, top_n=top_n + 1, proxy_url=proxy_url
            )
            for r in ranking:
                if "reporter_code" not in r:
                    continue  # 국가코드가 없으면(응답 스키마 이슈 등) 후보로 못 씀
                if r.get("iso3") == "KOR":
                    continue  # 한국 자신은 "한국의 수출 후보 시장"이 아님
                if len(targets) >= top_n:
                    break
                targets.append({
                    "label": r["country"], "iso3": None, "reporter_code": r["reporter_code"],
                    "iso3_hint": r.get("iso3"), "is_focus": False,
                })

        for order, raw in enumerate(candidate_countries or []):
            try:
                iso3 = resolve_iso3(raw)
            except ValueError:
                excluded.append({
                    "label": raw,
                    "reason": "국가를 인식할 수 없습니다. ISO3 코드(예: VNM, USA)로 입력해보세요.",
                    "is_focus": True,
                })
                continue
            if iso3 == "KOR":
                excluded.append({"label": raw, "reason": "한국은 한국의 수출 대상 시장이 아니라 제외했습니다.",
                                 "is_focus": True})
                continue
            try:
                codes = set(candidate_reporter_codes(iso3, proxy_url=proxy_url))
            except Exception:  # 국가코드 표를 못 받아도 이름(ISO3)으로만 중복 확인하고 계속 진행
                codes = set()
            existing = next(
                (t for t in targets
                 if (t.get("iso3_hint") or t.get("iso3")) == iso3 or (t.get("reporter_code") in codes)),
                None,
            )
            if existing:
                existing["is_focus"] = True  # 이미 수입 상위권에 있음 -> 관심 표시만
                existing.setdefault("focus_order", order)
            else:
                targets.append({
                    "label": raw.strip(), "iso3": iso3, "reporter_code": None,
                    "iso3_hint": iso3, "is_focus": True, "focus_order": order,
                })

        if not targets:
            raise ValueError(
                "비교할 국가가 없습니다. 비교 국가 수를 1 이상으로 하거나, 관심 국가를 올바르게 입력해주세요."
            )

        official_item_desc = None
        candidates = []
        for t in targets:
            candidate_key = t["iso3"] or f"code:{t['reporter_code']}"
            cached = None if force else _load_point_cache(conn, hscode, candidate_key, years_key, ttl_days)
            if cached:
                point = cached
            else:
                point = _get_candidate_point(
                    subscription_key, hscode, t["label"], t["iso3"], t["reporter_code"],
                    years, proxy_url, iso3_hint=t.get("iso3_hint"),
                    fallback_year=ranking_year, force=force,
                )
                point["fetched_at"] = datetime.now(timezone.utc).isoformat()
                _save_point_cache(conn, hscode, candidate_key, years_key, point)

            # 화면에서 이 후보국을 클릭해 상세 조사할 때 국가명 매칭 없이 바로
            # 조회할 수 있도록 식별 정보를 붙여둔다 (예전 캐시에도 적용됨).
            point["iso3"] = t["iso3"] or t.get("iso3_hint")
            point["reporter_code"] = t["reporter_code"]
            point["label"] = t["label"]  # 캐시에 예전 이름이 남아 있어도 이번 입력 기준 이름으로 표시
            point["is_focus"] = t["is_focus"]
            point["focus_order"] = t.get("focus_order")  # 사용자가 입력한 순서 (⑥ 자동 선택용)

            if official_item_desc is None and point.get("item_desc"):
                official_item_desc = point["item_desc"]

            if point["cagr_pct"] is None or point["korea_share_pct"] is None:
                excluded.append({
                    "label": point["label"],
                    "reason": "성장률 또는 한국 점유율을 계산할 데이터가 부족합니다.",
                    "is_focus": t["is_focus"],
                })
            else:
                candidates.append(point)

        if not candidates:
            raise RuntimeError(
                "매트릭스에 올릴 수 있는 후보국이 없습니다 (모든 후보국의 데이터가 부족합니다)."
            )

        avg_cagr = round(sum(c["cagr_pct"] for c in candidates) / len(candidates), 1)
        avg_share = sum(c["korea_share_pct"] for c in candidates) / len(candidates)
        # 한국 점유율 "높음" 기준: 후보국 평균과 최소 의미 기준(1%) 중 큰 값.
        # 평균만 쓰면 한국이 거의 수출하지 않는 품목에서 0.01% vs 0.06% 차이로
        # "집중 공략"이 나오는 문제가 있었다.
        share_threshold = max(avg_share, MIN_MEANINGFUL_KOREA_SHARE_PCT)
        korea_presence = (
            "meaningful"
            if any(c["korea_share_pct"] >= MIN_MEANINGFUL_KOREA_SHARE_PCT for c in candidates)
            else "negligible"
        )
        max_market = max((c["total_import_usd"] or 0) for c in candidates)
        # 비교 국가가 3개 미만이면 "평균보다 높다/낮다"가 의미가 없어서 사분면을 매기지 않는다
        comparison_too_small = len(candidates) < 3
        for c in candidates:
            c["quadrant"] = None if comparison_too_small else _classify_quadrant(
                c["cagr_pct"], c["korea_share_pct"], avg_cagr, share_threshold
            )
            size = c["total_import_usd"] or 0
            c["is_small_market"] = bool(size < SMALL_MARKET_USD or (max_market and size < max_market * 0.05))
        thresholds = {
            "avg_cagr_pct": avg_cagr,
            "avg_korea_share_pct": round(avg_share, 4),
            "share_threshold_pct": round(share_threshold, 4),
            "min_meaningful_share_pct": MIN_MEANINGFUL_KOREA_SHARE_PCT,
        }

        # 트라이빅 "유망시장 순위" 버블차트의 X축(수입금액 순위)에 대응.
        # 트라이빅의 실제 순위 공식은 공개돼 있지 않아서, 우리는 정직하게
        # "수입금액이 큰 순"으로만 매긴다.
        ranked_by_import = sorted(candidates, key=lambda c: (c["total_import_usd"] or 0), reverse=True)
        for i, c in enumerate(ranked_by_import, 1):
            c["import_rank"] = i

        candidates.sort(key=lambda c: (c["cagr_pct"], c["korea_share_pct"]), reverse=True)

        return {
            "hscode": hscode,
            "official_item_desc": official_item_desc,
            "years": years,
            "ranking_year": ranking_year,
            "thresholds": thresholds,
            "korea_presence": korea_presence,
            "comparison_too_small": comparison_too_small,
            "top_n": top_n,
            "focus_count": sum(1 for c in candidates if c.get("is_focus")),
            "candidates": candidates,
            "excluded": excluded,
            "ai_summary": None,
            "ai_error": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "from_cache": all(c.get("from_cache") for c in candidates) if candidates else False,
        }


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
                pts.append({"year": y, "share_pct": round(row["value_usd"] / total * 100, 2)})
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
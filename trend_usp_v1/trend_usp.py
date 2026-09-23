"""연관 검색어 기반 시장 트렌드 4단계 클러스터링 + 경쟁 대체재 USP + 박람회 부스 컨셉.

원칙: "수집은 현지 소비자의 언어로, 분석·전달은 한국어로."

파이프라인:
    ⓪ 국가 프로필 결정     constants/country_profiles.py (없으면 LLM 추정)
    ① 시드 검색어 생성     LLM - 현지어 + 로마자/영문, 최대 3개 + 상위 카테고리 1개
    ② 연관 검색어 수집     pytrends related_queries, 단계적 확장
                           (seed@국가 → category@국가 → seed@글로벌 → LLM 추정)
    ③ 전처리               코드 - 중복 제거, Breakout 표시, 최대 25개
    ④ 4단계 분류           LLM - 원문 기준 분류 + "제외", 한국어 해석 추가
                           ID로만 참조하게 해서 목록에 없는 검색어는 코드에서 폐기
    ⑤ 배지 수치            코드 - 5년 주간 시계열 기준 전년 동기(YoY) 증감률로 통일
    ⑥ USP·부스 컨셉        LLM - 분석은 한국어, 슬로건·피칭은 바이어 언어 원문 + 한국어

수치(증감률, 급상승 값)는 전부 코드가 계산하고, LLM은 분류와 해석 문장만 만든다.
"""

import datetime
import hashlib
import json
import logging
import os
import time

from openai import OpenAI

from constants.country_profiles import (
    COUNTRY_PROFILES,
    DEFAULT_LOW_RELIABILITY_NOTE_KO,
    KNOWN_CERT_GROUPS,
    RELIABILITY_LABELS_KO,
    RELIABILITY_NOTES_KO,
)

logger = logging.getLogger("sabuzak.trend_usp")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")

DEFAULT_LLM_MODEL = "gpt-4o-mini"   # .env의 TREND_USP_MODEL로 변경 가능

RELATED_TIMEFRAME = "today 12-m"      # 연관 검색어 수집 기간
YOY_TIMEFRAME = "today 5-y"           # YoY 계산용 (주간 데이터)
CACHE_TTL_SEC = 24 * 60 * 60
REQUEST_DELAY_SEC = 1.5               # Google 요청 사이 지연 (429 완화)
MAX_TRENDS_RETRY = 3
MAX_SEEDS = 3
MAX_KEYWORDS = 25
MIN_RELATED_KEYWORDS = 6              # 이보다 적으면 다음 단계로 확장
MAX_KEYWORDS_PER_CLUSTER = 4
MAX_SOLO_RETRY = 4                    # 묶음 조회에서 0으로 눌린 검색어 단독 재조회 상한
BREAKOUT_THRESHOLD = 5000             # Google "Breakout"은 +5000% 이상
YOY_WINDOW_WEEKS = 13                 # 최근 3개월
YOY_MIN_BASE = 1.0                    # 전년 동기 평균이 이보다 작으면 "데이터 부족"
YOY_MAX_ZERO_RATIO = 0.5              # 비교 구간에서 0 비율이 이보다 크면 "데이터 부족"

CLUSTER_KEYS = ["culture_trigger", "intent_funnel", "category_perception", "consumption_habit"]
CLUSTER_META = {
    "culture_trigger": {"label": "CULTURE TRIGGER", "title_ko": "미디어 유입 원인 분석"},
    "intent_funnel": {"label": "INTENT FUNNEL", "title_ko": "소비자 구매 성숙도 추이"},
    "category_perception": {"label": "PERCEPTION", "title_ko": "현지 인접 경쟁군 인식"},
    "consumption_habit": {"label": "HABIT & TPO", "title_ko": "취식 상황 및 번들 소비"},
}
FUNNEL_STAGES_KO = {"awareness": "인지", "consideration": "탐색", "purchase": "구매 전환"}
DATA_LEVEL_LABELS_KO = {
    "seed": "현지 시드 검색어 기준 실측",
    "category": "상위 카테고리 검색어 기준 실측",
    "global": "전 세계(글로벌) 기준 실측",
    "estimated": "AI 추정 (Google 트렌드 데이터 없음)",
}


class PipelineError(Exception):
    """사용자에게 그대로 보여줄 수 있는 파이프라인 오류."""


# ---------------------------------------------------------------------------
# 공통: OpenAI JSON 호출
# ---------------------------------------------------------------------------

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise PipelineError("OPENAI_API_KEY가 설정되어 있지 않습니다.")
        _openai_client = OpenAI(api_key=api_key, timeout=60, max_retries=2)
    return _openai_client


def _chat_json(system_prompt: str, user_prompt: str, temperature: float) -> dict:
    """OpenAI를 JSON 모드로 호출해서 dict를 돌려준다."""
    try:
        response = _get_openai_client().chat.completions.create(
            model=os.getenv("TREND_USP_MODEL") or DEFAULT_LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)
    except PipelineError:
        raise
    except Exception as e:
        logger.exception("OpenAI 호출 실패")
        raise PipelineError(f"AI 분석 호출에 실패했습니다: {e}") from e


# ---------------------------------------------------------------------------
# 공통: 파일 캐시 (pytrends 429 대비)
# ---------------------------------------------------------------------------

def _cache_path(kind: str, *parts) -> str:
    raw = json.dumps([kind, *parts], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{kind}_{digest}.json")


def _cache_get(path: str):
    try:
        if time.time() - os.path.getmtime(path) > CACHE_TTL_SEC:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_set(path: str, data) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        logger.warning("캐시 저장 실패: %s", path)


# ---------------------------------------------------------------------------
# Google Trends 클라이언트 (pytrends 래퍼)
# ---------------------------------------------------------------------------

class TrendsClient:
    """pytrends 호출을 캐시·재시도·요청 간 지연으로 감싼다.

    예외는 호출한 쪽에서 "이 단계 데이터 없음"으로 처리할 수 있도록
    재시도 후에도 실패하면 그대로 올린다."""

    def __init__(self, hl: str, use_cache: bool = True):
        self.hl = hl
        self.use_cache = use_cache
        self._pytrends = None
        self._last_request_at = 0.0

    def _client(self):
        if self._pytrends is None:
            from pytrends.request import TrendReq
            self._pytrends = TrendReq(hl=self.hl, tz=0, timeout=(10, 25))
        return self._pytrends

    def _throttle(self):
        wait = REQUEST_DELAY_SEC - (time.time() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def _with_retry(self, fn):
        last_error = None
        for attempt in range(MAX_TRENDS_RETRY):
            self._throttle()
            try:
                return fn()
            except Exception as e:  # pytrends는 429 등을 여러 예외 타입으로 던진다
                last_error = e
                logger.warning("Google Trends 요청 실패(%d/%d): %s", attempt + 1, MAX_TRENDS_RETRY, e)
                if attempt + 1 < MAX_TRENDS_RETRY:
                    time.sleep(2 ** (attempt + 1))
        raise last_error

    def related_queries(self, keywords: list, geo: str) -> dict:
        """{keyword: {"top": [{"query","value"}], "rising": [...]}} 형태로 반환."""
        path = _cache_path("related", keywords, geo, RELATED_TIMEFRAME, self.hl)
        if self.use_cache:
            cached = _cache_get(path)
            if cached is not None:
                return cached

        def call():
            client = self._client()
            client.build_payload(kw_list=keywords, timeframe=RELATED_TIMEFRAME, geo=geo)
            return client.related_queries()

        raw = self._with_retry(call)
        result = {}
        for kw, frames in (raw or {}).items():
            result[kw] = {
                kind: _df_to_records(frames.get(kind) if frames else None)
                for kind in ("top", "rising")
            }
        _cache_set(path, result)
        return result

    def interest_over_time(self, keywords: list, geo: str) -> dict:
        """{keyword: [주간 값...]} (부분 집계 주 제외)."""
        path = _cache_path("iot", keywords, geo, YOY_TIMEFRAME, self.hl)
        if self.use_cache:
            cached = _cache_get(path)
            if cached is not None:
                return cached

        def call():
            client = self._client()
            client.build_payload(kw_list=keywords, timeframe=YOY_TIMEFRAME, geo=geo)
            return client.interest_over_time()

        df = self._with_retry(call)
        result = {}
        if df is not None and not df.empty:
            if "isPartial" in df.columns:
                df = df[~df["isPartial"].astype(bool)]
            for kw in keywords:
                if kw in df.columns:
                    result[kw] = [float(v) for v in df[kw].tolist()]
        _cache_set(path, result)
        return result


def _df_to_records(df) -> list:
    if df is None:
        return []
    try:
        return [{"query": str(r["query"]), "value": int(r["value"])} for r in df.to_dict("records")]
    except (KeyError, TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# ⓪ 국가 프로필
# ---------------------------------------------------------------------------

def resolve_country_profile(country_input: str) -> dict:
    """한국어/영문/ISO 코드 입력을 국가 프로필로 바꾼다. 상수 테이블에 없으면 LLM 추정."""
    key = (country_input or "").strip().lower()
    if not key:
        raise PipelineError("진출 대상 국가를 입력해 주세요.")
    for profile in COUNTRY_PROFILES.values():
        if key in profile["aliases"]:
            return {**profile, "is_profile_estimated": False}

    data = _chat_json(
        "You are a global market-entry analyst. Answer only in JSON.",
        f"""사용자가 입력한 국가: "{country_input}"

이 국가의 Google 트렌드 조사용 프로필을 JSON으로 답하세요.
- geo: ISO 3166-1 alpha-2 대문자 코드
- name_ko: 한국어 국가명
- languages: 현지 소비자가 실제 검색에 쓰는 언어(영문 언어명) 목록, 주 언어 먼저, 최대 3개
- hl: Google 언어 코드 (예: en-US, fr, ar)
- buyer_language: 현지 식품 바이어와 B2B 상담 시 통용되는 언어(영문 언어명)
- reliability: 이 국가에서 Google 검색 점유율이 압도적이면 "high", 경쟁 검색엔진 비중이 크면 "medium", Google이 주력이 아니면 "low"
- reliability_note_ko: reliability가 high가 아니면 이유를 한국어 한 문장으로, high면 빈 문자열

{{"geo": "", "name_ko": "", "languages": [], "hl": "", "buyer_language": "", "reliability": "", "reliability_note_ko": ""}}""",
        temperature=0,
    )
    geo = str(data.get("geo", "")).upper()[:2]
    if len(geo) != 2:
        raise PipelineError(f"'{country_input}'을(를) 국가로 인식하지 못했습니다. 국가명을 다시 확인해 주세요.")
    reliability = data.get("reliability") if data.get("reliability") in RELIABILITY_LABELS_KO else "medium"
    return {
        "geo": geo,
        "name_ko": data.get("name_ko") or country_input,
        "aliases": [],
        "languages": (data.get("languages") or ["English"])[:3],
        "hl": data.get("hl") or "en-US",
        "buyer_language": data.get("buyer_language") or "English",
        "reliability": reliability,
        "reliability_note_ko": data.get("reliability_note_ko", ""),
        "is_profile_estimated": True,
    }


def _reliability_note(profile: dict) -> str:
    if profile["reliability"] == "high":
        return ""
    return (profile.get("reliability_note_ko")
            or RELIABILITY_NOTES_KO.get(profile["geo"])
            or DEFAULT_LOW_RELIABILITY_NOTE_KO)


# ---------------------------------------------------------------------------
# ① 시드 검색어 생성
# ---------------------------------------------------------------------------

SYSTEM_SEARCH_EXPERT = (
    "You are a multilingual food-market search analyst who knows exactly what local consumers "
    "type into Google in each country. Answer only in JSON."
)


def _product_block(product: dict) -> str:
    return (
        f"- 제품명: {product['name']}\n"
        f"- 제품 강점: {product.get('strengths') or '미입력'}\n"
        f"- 주요 원료: {product.get('ingredients') or '미입력'}\n"
        f"- 보유 인증: {product.get('certifications') or '없음'}\n"
        f"- 가격대: {product.get('price') or '미입력'}"
    )


def generate_seed_keywords(product: dict, profile: dict) -> dict:
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT,
        f"""[한국 수출 제품]
{_product_block(product)}

[대상 시장] {profile['name_ko']} (geo={profile['geo']}), 현지 검색 언어: {', '.join(profile['languages'])}

{profile['name_ko']} 소비자가 이 제품을 찾을 때 Google에 실제로 입력하는 검색어를 만드세요.

규칙:
1. seeds: 최대 {MAX_SEEDS}개, 각 1~3단어.
   - 현지어/현지 문자 표기(예: 일본 キンパ, 태국 คิมบับ, 독일 koreanische ...)와
     로마자/영문 표기(예: kimbap, yakgwa)를 섞으세요. 영어권이면 영문만 써도 됩니다.
   - 현지에서 실제로 쓰일 법한 표기만 쓰세요. 한국어(한글) 표기는 현지에서 널리 쓰일 때만 허용.
   - 'food', 'snack', 'dessert' 같은 거대 일반명사 단독 사용 금지.
2. category: 데이터가 부족할 때 쓸 상위 카테고리 검색어 1개 (예: korean dessert, 韓国 お菓子).
3. 각 검색어에 lang(영문 언어명)과 ko(한국어 뜻)를 붙이세요.

{{"seeds": [{{"keyword": "", "lang": "", "ko": ""}}],
  "category": {{"keyword": "", "lang": "", "ko": ""}},
  "english_name": "제품의 가장 통용되는 영문명"}}""",
        temperature=0.2,
    )
    seeds = []
    seen = set()
    for s in data.get("seeds") or []:
        kw = str(s.get("keyword", "")).strip()
        if kw and kw.casefold() not in seen:
            seen.add(kw.casefold())
            seeds.append({"keyword": kw, "lang": s.get("lang", ""), "ko": s.get("ko", "")})
    if not seeds:
        raise PipelineError("검색어 후보를 만들지 못했습니다. 제품명을 더 구체적으로 입력해 주세요.")
    category = data.get("category") or {}
    return {
        "seeds": seeds[:MAX_SEEDS],
        "category": {"keyword": str(category.get("keyword", "")).strip(),
                     "lang": category.get("lang", ""), "ko": category.get("ko", "")},
        "english_name": data.get("english_name", ""),
    }


# ---------------------------------------------------------------------------
# ② 연관 검색어 수집 (단계적 확장)
# ---------------------------------------------------------------------------

def collect_related_queries(trends: TrendsClient, seed_info: dict, geo: str) -> dict:
    """seed@국가 → category@국가 → seed@글로벌 순서로, 충분한 연관 검색어가 모일 때까지 확장.

    반환: {"records": [...], "data_level": 마지막으로 데이터를 보탠 단계, "attempts": [...]}"""
    seed_keywords = [s["keyword"] for s in seed_info["seeds"]]
    category_kw = seed_info["category"]["keyword"]
    levels = [("seed", seed_keywords, geo)]
    if category_kw and category_kw.casefold() not in {k.casefold() for k in seed_keywords}:
        levels.append(("category", [category_kw], geo))
    if geo:
        levels.append(("global", seed_keywords, ""))

    records = []
    attempts = []
    data_level = None
    for level, keywords, level_geo in levels:
        try:
            result = trends.related_queries(keywords, level_geo)
            error = None
        except Exception as e:
            result, error = {}, str(e)
        added = 0
        for seed_kw, lists in result.items():
            for source in ("rising", "top"):
                for row in lists.get(source) or []:
                    records.append({**row, "source": source, "seed": seed_kw,
                                    "level": level, "geo": level_geo})
                    added += 1
        attempts.append({"level": level, "keywords": keywords, "geo": level_geo or "GLOBAL",
                         "count": added, "error": error})
        if added:
            data_level = level
        if len(_unique_queries(records, seed_keywords)) >= MIN_RELATED_KEYWORDS:
            break
    return {"records": records, "data_level": data_level, "attempts": attempts}


def _unique_queries(records: list, exclude: list) -> set:
    excluded = {k.casefold() for k in exclude}
    return {r["query"].strip().casefold() for r in records} - excluded


# ---------------------------------------------------------------------------
# ③ 전처리
# ---------------------------------------------------------------------------

def preprocess_keywords(records: list, exclude: list) -> list:
    """중복 병합 + 정렬 + 상한. 급상승(rising)을 우선하고 값이 큰 순서로 자른다."""
    excluded = {k.strip().casefold() for k in exclude}
    merged = {}
    for r in records:
        query = " ".join(r["query"].split())
        key = query.casefold()
        if not key or key in excluded:
            continue
        item = merged.get(key)
        if item is None:
            item = merged[key] = {"keyword": query, "sources": set(), "rising_value": None,
                                  "top_value": None, "seed": r["seed"], "level": r["level"], "geo": r["geo"]}
        item["sources"].add(r["source"])
        field = "rising_value" if r["source"] == "rising" else "top_value"
        if item[field] is None or r["value"] > item[field]:
            item[field] = r["value"]

    def sort_key(item):
        is_rising = item["rising_value"] is not None
        return (0 if is_rising else 1, -(item["rising_value"] or item["top_value"] or 0))

    items = sorted(merged.values(), key=sort_key)[:MAX_KEYWORDS]
    out = []
    for i, item in enumerate(items, start=1):
        rising = item["rising_value"]
        out.append({
            "id": i,
            "keyword": item["keyword"],
            "source": "both" if len(item["sources"]) == 2 else next(iter(item["sources"])),
            "rising_value": rising,
            "top_value": item["top_value"],
            "is_breakout": rising is not None and rising >= BREAKOUT_THRESHOLD,
            "seed": item["seed"],
            "level": item["level"],
            "geo": item["geo"],
            "is_estimated": False,
        })
    return out


def estimate_keywords(product: dict, profile: dict, seed_info: dict) -> list:
    """(A) Google 트렌드 데이터가 전혀 없을 때: LLM이 현지 검색어를 추정한다.
    수치 배지는 만들지 않고 화면에 "AI 추정"으로 표시한다."""
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT,
        f"""[한국 수출 제품]
{_product_block(product)}

[대상 시장] {profile['name_ko']}, 현지 검색 언어: {', '.join(profile['languages'])}
[시드 검색어] {', '.join(s['keyword'] for s in seed_info['seeds'])}

Google 트렌드 데이터가 없어, 이 시장 소비자가 입력할 법한 연관 검색어를 추정해야 합니다.
현지어와 로마자/영문 표기를 섞어 12~16개를 만드세요. 다음 관점이 고르게 포함되게 하세요:
미디어/콘텐츠 유입, 구매 의도(레시피·정보 탐색 vs 구매·매장 찾기), 현지 대체재 비교, 취식 상황/페어링.
각 검색어는 1~5단어, 원문 그대로 쓰세요.

{{"keywords": ["", ""]}}""",
        temperature=0.4,
    )
    seed_kws = [s["keyword"] for s in seed_info["seeds"]]
    records = [{"query": str(k), "value": 0, "source": "top", "seed": seed_kws[0],
                "level": "estimated", "geo": profile["geo"]}
               for k in (data.get("keywords") or []) if str(k).strip()]
    items = preprocess_keywords(records, seed_kws)
    for item in items:
        item.update({"source": "estimated", "top_value": None, "is_estimated": True})
    return items


# ---------------------------------------------------------------------------
# ④ 4단계 분류
# ---------------------------------------------------------------------------

def classify_keywords(product: dict, profile: dict, items: list) -> dict:
    listing = "\n".join(
        f"[{it['id']}] {it['keyword']}"
        + (" (급상승)" if it["rising_value"] is not None else "")
        for it in items
    )
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT + " All explanations must be written in Korean.",
        f"""[한국 수출 제품]
{_product_block(product)}
[대상 시장] {profile['name_ko']} (현지 검색 언어: {', '.join(profile['languages'])})

[현지 연관 검색어 목록] (원문 그대로, 번호로만 참조하세요)
{listing}

각 검색어를 아래 4개 분류 중 하나에 넣거나, 제품과 무관하면 excluded에 넣으세요.
- culture_trigger: 소비자가 이 제품을 접하게 된 계기 (드라마·OTT·인플루언서·셀럽·축제·K-콘텐츠)
- intent_funnel: 구매 성숙도. stage를 반드시 지정:
    awareness(뜻·정체 탐색: what is, meaning), consideration(레시피·만드는 법·비교·후기),
    purchase(near me, buy, 가격, 브랜드명, 매장·온라인몰)
- category_perception: 현지 소비자가 비교·대체하는 로컬 친숙 식품이나 경쟁 카테고리
- consumption_habit: 취식 상황, 페어링(음료·술), 보관·섭취 형태, 번들 소비

규칙:
- 목록에 있는 번호만 쓰세요. 새로운 검색어를 만들지 마세요.
- 한 번호는 한 곳에만 넣으세요. 분류당 관련성 높은 순서로 최대 {MAX_KEYWORDS_PER_CLUSTER}개.
- 동음이의어, 무관한 인물·브랜드, 다른 음식이면 excluded.
- ko: 검색어의 한국어 해석(짧게, 검색 의도가 드러나게).
- summary_ko: 이 분류에서 읽히는 현지 소비 맥락 1~2문장 (한국어).
- tag_ko: 카드 우측 상단 뱃지 문구 (한국어 2~6자, 예: "미디어 결합도", "구매 단계 전환", "조력 대체재", "취식 페어링").
- insight_ko: 수출기업이 할 행동 한 줄 (한국어, 25자 내외).
- 분류에 해당 검색어가 하나도 없으면 items는 빈 배열로 두고 summary_ko에 "관련 검색 신호 없음"이라고 쓰세요.

{{"clusters": {{
  "culture_trigger": {{"items": [{{"id": 1, "ko": ""}}], "summary_ko": "", "tag_ko": "", "insight_ko": ""}},
  "intent_funnel": {{"items": [{{"id": 2, "ko": "", "stage": "purchase"}}], "summary_ko": "", "tag_ko": "", "insight_ko": ""}},
  "category_perception": {{"items": [], "summary_ko": "", "tag_ko": "", "insight_ko": ""}},
  "consumption_habit": {{"items": [], "summary_ko": "", "tag_ko": "", "insight_ko": ""}}
}}, "excluded": [{{"id": 3, "reason_ko": ""}}]}}""",
        temperature=0.1,
    )
    return validate_classification(data, items)


def validate_classification(data: dict, items: list) -> dict:
    """LLM 분류 결과에서 목록에 없는 ID·중복 ID를 버리고, 검색어 원문은 코드 쪽 목록에서 가져온다."""
    by_id = {it["id"]: it for it in items}
    used = set()
    clusters_raw = (data or {}).get("clusters") or {}
    clusters = {}
    for key in CLUSTER_KEYS:
        raw = clusters_raw.get(key) or {}
        cluster_items = []
        for entry in raw.get("items") or []:
            try:
                item_id = int(entry.get("id"))
            except (TypeError, ValueError, AttributeError):
                continue
            if item_id not in by_id or item_id in used:
                continue
            used.add(item_id)
            stage = entry.get("stage") if key == "intent_funnel" else None
            cluster_items.append({
                **by_id[item_id],
                "ko": str(entry.get("ko", "")).strip(),
                "stage": stage if stage in FUNNEL_STAGES_KO else None,
            })
            if len(cluster_items) >= MAX_KEYWORDS_PER_CLUSTER:
                break
        if key == "intent_funnel":
            # 인지 → 탐색 → 구매 전환 순서로 보여줘야 퍼널 흐름이 읽힌다
            stage_order = list(FUNNEL_STAGES_KO)
            cluster_items.sort(key=lambda k: stage_order.index(k["stage"]) if k["stage"] else len(stage_order))
        clusters[key] = {
            "summary": str(raw.get("summary_ko", "")).strip() or "관련 검색 신호 없음",
            "tag": str(raw.get("tag_ko", "")).strip(),
            "insight": str(raw.get("insight_ko", "")).strip(),
            "keywords": cluster_items,
        }
    excluded = []
    for entry in (data or {}).get("excluded") or []:
        try:
            item_id = int(entry.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if item_id in by_id and item_id not in used:
            excluded.append({"keyword": by_id[item_id]["keyword"], "reason": entry.get("reason_ko", "")})
    return {"clusters": clusters, "excluded": excluded}


# ---------------------------------------------------------------------------
# ⑤ YoY 증감률 (코드 계산)
# ---------------------------------------------------------------------------

def compute_yoy(series: list) -> dict:
    """주간 시계열에서 최근 13주 평균 vs 1년 전 같은 13주 평균의 증감률."""
    w = YOY_WINDOW_WEEKS
    if not series or len(series) < 52 + w:
        return {"yoy_pct": None, "yoy_status": "insufficient"}
    recent = series[-w:]
    base = series[-(52 + w):-52]
    zero_ratio = sum(1 for v in recent + base if v <= 0) / (2 * w)
    base_mean = sum(base) / w
    if base_mean < YOY_MIN_BASE or zero_ratio > YOY_MAX_ZERO_RATIO:
        return {"yoy_pct": None, "yoy_status": "insufficient"}
    recent_mean = sum(recent) / w
    return {"yoy_pct": round((recent_mean / base_mean - 1) * 100), "yoy_status": "ok"}


def attach_yoy(trends: TrendsClient, clusters: dict) -> list:
    """분류된 검색어 전체에 YoY 배지를 붙인다. 반환: 경고 메시지 목록.

    Google은 한 요청에 최대 5개 검색어를 받고, 묶음 안에서 최댓값 기준으로 0~100을 매긴다.
    증감률은 검색어별 비율이라 묶음 스케일과 무관하지만, 검색량이 큰 검색어와 같이 묶이면
    작은 검색어가 0으로 눌릴 수 있어 그런 검색어는 단독으로 한 번 더 조회한다."""
    warnings = []
    targets = [kw for c in clusters.values() for kw in c["keywords"]]
    for kw in targets:
        kw.update({"yoy_pct": None, "yoy_status": "estimated" if kw["is_estimated"] else "insufficient"})
    measurable = [kw for kw in targets if not kw["is_estimated"]]

    by_geo = {}
    for kw in measurable:
        by_geo.setdefault(kw["geo"], []).append(kw)

    solo_candidates = []
    failed = 0
    for geo, group in by_geo.items():
        for i in range(0, len(group), 5):
            batch = group[i:i + 5]
            try:
                series_map = trends.interest_over_time([k["keyword"] for k in batch], geo)
            except Exception as e:
                logger.warning("YoY 조회 실패(%s): %s", geo or "GLOBAL", e)
                failed += len(batch)
                continue
            batch_has_signal = any(max(series_map.get(k["keyword"]) or [0]) > 0 for k in batch)
            for k in batch:
                k.update(compute_yoy(series_map.get(k["keyword"]) or []))
                if k["yoy_status"] == "insufficient" and batch_has_signal and len(batch) > 1:
                    solo_candidates.append(k)

    for k in solo_candidates[:MAX_SOLO_RETRY]:
        try:
            series_map = trends.interest_over_time([k["keyword"]], k["geo"])
            k.update(compute_yoy(series_map.get(k["keyword"]) or []))
        except Exception as e:
            logger.warning("YoY 단독 재조회 실패(%s): %s", k["keyword"], e)

    if failed:
        warnings.append(f"검색어 {failed}개의 전년 대비 증감률을 Google 트렌드에서 받아오지 못했습니다.")
    return warnings


# ---------------------------------------------------------------------------
# ⑥ USP 매트릭스 + 부스 컨셉
# ---------------------------------------------------------------------------

def generate_strategy(product: dict, profile: dict, trend_analysis: dict) -> dict:
    def fmt(key):
        c = trend_analysis[key]
        kws = ", ".join(
            f"{k['keyword']}({k['ko']}"
            + (f", 전년比 {k['yoy_pct']:+d}%" if k.get("yoy_pct") is not None else "")
            + (f", {FUNNEL_STAGES_KO[k['stage']]}" if k.get("stage") else "")
            + ")"
            for k in c["keywords"]
        ) or "없음"
        return f"- {key}: {c['summary']} / 검색어: {kws}"

    trend_block = "\n".join(fmt(k) for k in CLUSTER_KEYS)
    buyer_lang = profile["buyer_language"]
    data = _chat_json(
        "You are a K-food export strategist who prepares Korean exporters for overseas food trade shows. "
        "Analysis must be written in Korean; buyer-facing copy must be written in the buyer's language. "
        "Answer only in JSON.",
        f"""[한국 수출 제품 스펙 - 이 항목만 근거로 쓰세요]
{_product_block(product)}

[대상 시장] {profile['name_ko']}, 바이어 언어: {buyer_lang}

[현지 연관 검색어 4단계 분석 결과]
{trend_block}

1) usp_matrix: 현지 경쟁 품목/대체재 3개 (category_perception 검색어를 우선 활용, 부족하면 현지 매대의 대표 대체재).
   - target: 경쟁 품목 현지 표기 원문, target_ko: 한국어명
   - weakness_ko: 현지 소비자가 느끼는 해당 품목의 한계·불만 (한국어)
   - our_usp_ko: 우리 제품의 차별점 (한국어). 반드시 위 스펙(강점·원료·인증·가격)에 있는 사실만 근거로.
     스펙에 없는 인증·효능·수치를 만들지 마세요.
   - evidence: our_usp_ko가 근거로 삼은 스펙 항목명 배열 (예: ["제품 강점", "보유 인증"])
   - pitch_headline: 바이어 대상 한 줄 헤드라인 ({buyer_lang}), pitch_headline_ko: 그 한국어 번역
2) booth_concept: 박람회 부스 4요소. 각 항목 title은 {buyer_lang} 컨셉명(짧게), title_ko는 한국어 번역,
   description_ko는 한국어 실행 설명 1~2문장.
   - headline_slogan: 메인 비주얼 & 슬로건. 추가로 slogan({buyer_lang} 한 줄)과 slogan_ko.
   - sampling_strategy: 비교 체험(시식) 설계
   - pitching_wall: 바이어 피칭 월 인포그래픽 구성
   - packaging_display: 패키징·진열 가이드
3) 검색 신호가 없는 분류는 추측하지 말고 다른 분류의 근거를 쓰세요.

{{"usp_matrix": [{{"target": "", "target_ko": "", "weakness_ko": "", "our_usp_ko": "", "evidence": [],
                   "pitch_headline": "", "pitch_headline_ko": ""}}],
  "booth_concept": {{
    "headline_slogan": {{"title": "", "title_ko": "", "slogan": "", "slogan_ko": "", "description_ko": ""}},
    "sampling_strategy": {{"title": "", "title_ko": "", "description_ko": ""}},
    "pitching_wall": {{"title": "", "title_ko": "", "description_ko": ""}},
    "packaging_display": {{"title": "", "title_ko": "", "description_ko": ""}}
  }}}}""",
        temperature=0.5,
    )
    usp_matrix = []
    for row in (data.get("usp_matrix") or [])[:3]:
        if not isinstance(row, dict):
            continue
        row = {k: row.get(k, "") for k in ("target", "target_ko", "weakness_ko", "our_usp_ko",
                                            "pitch_headline", "pitch_headline_ko")} | {
            "evidence": [str(e) for e in (row.get("evidence") or [])]}
        row["unsupported_certs"] = find_unsupported_certs(
            f"{row['our_usp_ko']} {row['pitch_headline']} {row['pitch_headline_ko']}",
            product.get("certifications", ""))
        usp_matrix.append(row)

    booth_raw = data.get("booth_concept") or {}
    booth = {}
    for key in ("headline_slogan", "sampling_strategy", "pitching_wall", "packaging_display"):
        raw = booth_raw.get(key) or {}
        booth[key] = {k: str(raw.get(k, "")) for k in ("title", "title_ko", "description_ko")}
        if key == "headline_slogan":
            booth[key]["slogan"] = str(raw.get("slogan", ""))
            booth[key]["slogan_ko"] = str(raw.get("slogan_ko", ""))
    return {"usp_matrix": usp_matrix, "booth_concept": booth}


def find_unsupported_certs(text: str, certifications_input: str) -> list:
    """문구에 등장하지만 사용자가 입력하지 않은 인증 이름 목록."""
    text_l = (text or "").lower()
    certs_l = (certifications_input or "").lower()
    unsupported = []
    for group in KNOWN_CERT_GROUPS:
        mentioned = any(term in text_l for term in group)
        declared = any(term in certs_l for term in group)
        if mentioned and not declared:
            unsupported.append(group[0].upper() if group[0].isascii() else group[0])
    return unsupported


# ---------------------------------------------------------------------------
# 전체 파이프라인
# ---------------------------------------------------------------------------

def run_trend_usp(product: dict, country: str, use_cache: bool = True) -> dict:
    """제품 스펙(한국어) + 대상 국가 → 한국어 대시보드용 결과 JSON."""
    product = {k: (product.get(k) or "").strip() for k in
               ("name", "strengths", "ingredients", "certifications", "price")}
    if not product["name"]:
        raise PipelineError("제품명을 입력해 주세요.")

    profile = resolve_country_profile(country)
    trends = TrendsClient(hl=profile["hl"], use_cache=use_cache)
    warnings = []

    seed_info = generate_seed_keywords(product, profile)
    seed_keywords = [s["keyword"] for s in seed_info["seeds"]]

    collected = collect_related_queries(trends, seed_info, profile["geo"])
    items = preprocess_keywords(collected["records"], seed_keywords)
    data_level = collected["data_level"]
    if not items:
        data_level = "estimated"
        items = estimate_keywords(product, profile, seed_info)
        errors = [a["error"] for a in collected["attempts"] if a["error"]]
        warnings.append("Google 트렌드에서 연관 검색어를 받지 못해 AI 추정 검색어로 분석했습니다. "
                        "수치 배지는 표시하지 않습니다."
                        + (f" (원인: {errors[-1][:120]})" if errors else ""))
        if not items:
            raise PipelineError("연관 검색어를 수집하지도, 추정하지도 못했습니다.")
    elif data_level in ("category", "global"):
        warnings.append(f"현지 시드 검색어만으로는 데이터가 부족해 {DATA_LEVEL_LABELS_KO[data_level]} 데이터를 함께 사용했습니다.")

    classification = classify_keywords(product, profile, items)
    trend_analysis = classification["clusters"]
    warnings += attach_yoy(trends, trend_analysis)

    strategy = generate_strategy(product, profile, trend_analysis)
    if any(row["unsupported_certs"] for row in strategy["usp_matrix"]):
        warnings.append("USP 문구에 입력하지 않은 인증이 언급되었습니다. 해당 행의 경고를 확인하세요.")

    return {
        "product_info": {
            "name": product["name"],
            "strengths": product["strengths"],
            "ingredients": product["ingredients"],
            "certifications": product["certifications"],
            "price": product["price"],
        },
        "trend_analysis": trend_analysis,
        "usp_matrix": strategy["usp_matrix"],
        "booth_concept": strategy["booth_concept"],
        "excluded_keywords": classification["excluded"],
        "meta": {
            "country_ko": profile["name_ko"],
            "geo": profile["geo"],
            "languages": profile["languages"],
            "buyer_language": profile["buyer_language"],
            "is_profile_estimated": profile.get("is_profile_estimated", False),
            "reliability": profile["reliability"],
            "reliability_label_ko": RELIABILITY_LABELS_KO[profile["reliability"]],
            "reliability_note_ko": _reliability_note(profile),
            "seed_keywords": seed_info["seeds"],
            "category_keyword": seed_info["category"],
            "english_name": seed_info["english_name"],
            "data_level": data_level,
            "data_level_label_ko": DATA_LEVEL_LABELS_KO[data_level],
            "is_estimated": data_level == "estimated",
            "collection_attempts": collected["attempts"],
            "keyword_pool_size": len(items),
            "related_timeframe": RELATED_TIMEFRAME,
            "yoy_basis_ko": "최근 13주 평균 vs 1년 전 같은 13주 평균 (Google 트렌드 주간 지수)",
            "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "warnings": warnings,
        },
    }

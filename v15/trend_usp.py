"""연관 검색어 기반 시장 트렌드 4단계 클러스터링 + 경쟁 제품 USP + 박람회 부스 컨셉 (v2).

원칙
- 수집은 현지 소비자의 언어로, 분석·전달은 한국어로.
- 화면의 모든 정보에 근거 종류를 붙인다: 실측 / 탐색 검증 / 검색 확인 / 사용자 입력 / AI 참고.
- 숫자는 코드만 만든다. LLM 문구 속 숫자는 입력값에 있는 것만 허용한다.
- 신호가 없는 칸은 억지로 채우지 않는다.

파이프라인
    ⓪ 국가 프로필          constants/country_profiles.py (없으면 LLM 추정)
    ① 시드 생성 [light]    제품 시드(현지어+영문) 최대 3개 + 카테고리 시드 1~2개
    ② 수집 [pytrends]      제품+카테고리 시드를 항상 함께, related_queries + related_topics
                           풀이 부족하면 최근 5년 → 글로벌 → (최후) AI 추정
    ③ 전처리 [코드]        검색어·주제 병합, 급상승/Breakout 표시, 최대 30개
    ④ 분류 [light]         4개 분류 + 제외(명백히 무관한 것만). ID로만 참조 → 코드 검증
    ④-b 탐색 검증 [light]  검색어 2개 미만인 분류만 탐색 검색어 제안 → ⑤-통합에서 검색량 확인
    ⑤ 시장 맥락 [strategy] 경쟁 제품 후보(브랜드+제품/구체적 현지 음식) + 바이어 체크포인트
    ⑤-통합 [pytrends]      5년 주간 조회 한 단계에서: 증감 배지, 탐색 검증, 경쟁 제품 검색량 비교
                           (우리 제품 시드를 모든 묶음에 기준점으로 넣어 묶음 간 비교 가능)
    ⑥ 배지 [코드]          전년 대비 증감 → 구글 급상승 % → 없음
    ⑦ USP [strategy]       경쟁 제품 불만 → 우리의 해결 → 대비가 드러나는 헤드라인 (코드 검사 후 1회 재생성)
    ⑧ 부스 [strategy]      카드별 구조화 + 근거 참조. 피칭 월은 피칭용 입력이 있을 때만, 숫자는 입력값만
"""

import datetime
import hashlib
import json
import logging
import os
import re
import time

from openai import OpenAI

from constants.country_profiles import (
    COUNTRY_PROFILES,
    DEFAULT_LOW_RELIABILITY_NOTE_KO,
    KNOWN_CERT_GROUPS,
    RELIABILITY_LABELS_KO,
    RELIABILITY_NOTES_KO,
)
from http_compat import SAFE_HEADERS, apply_brotli_workaround
import model_upgrade

logger = logging.getLogger("sabuzak.trend_usp")

apply_brotli_workaround()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".cache")

DEFAULT_LIGHT_MODEL = model_upgrade.TASK_MODEL    # 시드·분류·탐색 (.env V12_TASK_MODEL)
DEFAULT_STRATEGY_MODEL = model_upgrade.TASK_MODEL  # v12 대시보드에서는 쓰지 않음

RELATED_TIMEFRAME = "today 12-m"
EXTENDED_TIMEFRAME = "today 5-y"      # 연관 검색어가 부족할 때 확장 기간
YOY_TIMEFRAME = "today 5-y"           # 증감 배지·검색량 비교용 (주간 데이터)
CACHE_TTL_SEC = 24 * 60 * 60
REQUEST_DELAY_SEC = 2.0               # Google 요청 사이 지연 (429 완화)
MAX_TRENDS_RETRY = 3
MAX_SEEDS = 3
MAX_CATEGORY_SEEDS = 2
MAX_PAYLOAD = 5                       # Google은 한 요청에 검색어 5개까지
MAX_KEYWORDS = 30
MIN_POOL_SIZE = 10                    # 연관 검색어가 이보다 적으면 다음 단계로 확장
MAX_KEYWORDS_PER_CLUSTER = 4
PROBE_TRIGGER_COUNT = 2               # 분류 검색어가 이보다 적으면 탐색 검색어 제안
MAX_PROBES_PER_CLUSTER = 3
MAX_SOLO_RETRY = 4
MAX_COMPETITORS = 6
MAX_USP_ROWS = 3
MAX_PITCH_BLOCKS = 4
BREAKOUT_THRESHOLD = 5000             # Google "Breakout"은 +5000% 이상
YOY_WINDOW_WEEKS = 13
YOY_MIN_BASE = 1.0
YOY_MAX_ZERO_RATIO = 0.5

CLUSTER_KEYS = ["culture_trigger", "intent_funnel", "category_perception", "consumption_habit"]
CLUSTER_META = {
    "culture_trigger": {"label": "CULTURE TRIGGER", "title_ko": "미디어 유입 원인 분석", "short_ko": "미디어 유입"},
    "intent_funnel": {"label": "INTENT FUNNEL", "title_ko": "소비자 구매 성숙도 추이", "short_ko": "구매 의도"},
    "category_perception": {"label": "PERCEPTION", "title_ko": "현지 인접 경쟁군 인식", "short_ko": "경쟁 인식"},
    "consumption_habit": {"label": "HABIT & TPO", "title_ko": "취식 상황 및 번들 소비", "short_ko": "취식 상황"},
}
FUNNEL_STAGES_KO = {"awareness": "인지", "consideration": "탐색", "purchase": "구매 전환"}
DATA_LEVEL_LABELS_KO = {
    "seed": "현지 검색어 기준 실측",
    "extended": "현지 검색어 기준 실측 (기간 5년으로 확장)",
    "global": "전 세계 기준 실측 포함",
    "estimated": "AI 추정 (Google 트렌드 데이터 없음)",
}
EVIDENCE_LABELS_KO = {
    "measured": "실측",
    "probe": "탐색 검증",
    "search_verified": "검색 확인",
    "user": "사용자 입력",
    "ai": "AI 참고",
    "estimated": "AI 추정",
}

PRODUCT_FIELDS = ["name", "strengths", "ingredients", "certifications", "price",
                  "shelf_life", "pack_format", "moq_price", "channel", "known_competitors"]
INPUT_LABELS_KO = {
    "strengths": "제품 강점",
    "ingredients": "주요 원료",
    "certifications": "보유 인증",
    "price": "가격대",
    "shelf_life": "유통기한",
    "pack_format": "포장 단위·형태",
    "moq_price": "MOQ·납품가",
    "channel": "타깃 유통채널",
    "known_competitors": "알고 있는 경쟁 제품",
}
# 이 중 하나라도 입력해야 바이어 피칭 월을 만든다
PITCH_INPUT_FIELDS = ["shelf_life", "pack_format", "moq_price", "channel"]
# 피칭 월 숫자의 출처로 인정하는 입력 항목
PITCH_SOURCE_FIELDS = ["price", "certifications", "strengths", "ingredients"] + PITCH_INPUT_FIELDS

# 헤드라인 상투어: 어느 제품에나 붙일 수 있어 USP와의 연결이 끊기는 표현
CLICHE_PATTERNS = [
    r"\bexperience\b", r"\bdiscover\b", r"\bunique\b", r"\btaste the tradition\b", r"\bsavor\b",
    r"\bindulge\b", r"\bdelight(ful)?\b", r"\bauthentic taste\b", r"\bjourney\b", r"\bexplore\b",
]
# 경쟁 대상 이름이 이 단어들로만 이뤄지면 "카테고리"로 보고 버린다
GENERIC_TARGET_WORDS = {
    "asian", "korean", "korea", "snack", "snacks", "sweet", "sweets", "cookie", "cookies", "dessert",
    "desserts", "food", "foods", "candy", "candies", "cake", "cakes", "pastry", "pastries", "biscuit",
    "biscuits", "coffee", "drink", "drinks", "beverage", "beverages", "noodle", "noodles", "sauce",
    "sauces", "product", "products", "brand", "brands", "traditional", "local", "imported", "generic",
    "instant", "mix", "mixes", "treat", "treats", "confectionery", "bakery",
}
HEADLINE_STOPWORDS = {"with", "without", "that", "your", "from", "this", "into", "more", "less", "than",
                      "the", "and", "for", "you", "our", "are", "not", "any", "all"}


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
        # br 압축을 요청하지 않아 예전 brotli가 설치된 PC에서도 동작 (http_compat.py 참고)
        # 추론형 모델 대응(temperature 제거·추론 깊이)과 모델 자동 대체는 model_upgrade가 맡는다
        _openai_client = model_upgrade.wrap(
            OpenAI(api_key=api_key, timeout=180, max_retries=2, default_headers=SAFE_HEADERS))
    return _openai_client


def _model_name(strategy: bool) -> str:
    if strategy:
        return os.getenv("TREND_USP_STRATEGY_MODEL") or DEFAULT_STRATEGY_MODEL
    return os.getenv("TREND_USP_MODEL") or DEFAULT_LIGHT_MODEL


def _chat_json(system_prompt: str, user_prompt: str, temperature: float, strategy: bool = False) -> dict:
    """OpenAI를 JSON 모드로 호출해서 dict를 돌려준다. strategy=True면 전략용(상위) 모델."""
    try:
        response = _get_openai_client().chat.completions.create(
            model=_model_name(strategy),
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

    재시도 후에도 실패하면 예외를 그대로 올려서, 호출한 쪽이 "이 단계 데이터 없음"으로 처리한다."""

    def __init__(self, hl: str, use_cache: bool = True):
        self.hl = hl
        self.use_cache = use_cache
        self._pytrends = None
        self._last_request_at = 0.0

    def _client(self):
        if self._pytrends is None:
            from pytrends.request import TrendReq
            self._pytrends = TrendReq(hl=self.hl, tz=0, timeout=(10, 25),
                                     requests_args={"headers": dict(SAFE_HEADERS)})
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

    def related(self, keywords: list, geo: str, timeframe: str) -> dict:
        """연관 검색어와 연관 주제를 한 번의 payload로 받는다.

        반환: {"queries": {kw: {"top": [...], "rising": [...]}}, "topics": {kw: {...}}}
        연관 주제는 pytrends 버전에 따라 실패하는 경우가 있어 실패해도 검색어 결과는 살린다."""
        path = _cache_path("related2", keywords, geo, timeframe, self.hl)
        if self.use_cache:
            cached = _cache_get(path)
            if cached is not None:
                return cached

        def call():
            client = self._client()
            client.build_payload(kw_list=keywords, timeframe=timeframe, geo=geo)
            queries = client.related_queries()
            try:
                time.sleep(REQUEST_DELAY_SEC)
                topics = client.related_topics()
            except Exception as e:
                logger.warning("연관 주제 조회 실패(검색어 결과만 사용): %s", e)
                topics = {}
            return queries, topics

        raw_queries, raw_topics = self._with_retry(call)
        result = {"queries": {}, "topics": {}}
        for kw, frames in (raw_queries or {}).items():
            result["queries"][kw] = {kind: _df_to_records(frames.get(kind) if frames else None)
                                     for kind in ("top", "rising")}
        for kw, frames in (raw_topics or {}).items():
            result["topics"][kw] = {kind: _topic_df_to_records(frames.get(kind) if frames else None)
                                    for kind in ("top", "rising")}
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


def _topic_df_to_records(df) -> list:
    """연관 주제 DataFrame(topic_title, topic_type, value) → 검색어와 같은 레코드 형태."""
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for r in df.to_dict("records"):
        title = str(r.get("topic_title") or "").strip()
        try:
            value = int(r.get("value"))
        except (TypeError, ValueError):
            continue
        if title:
            out.append({"query": title, "value": value, "topic_type": str(r.get("topic_type") or "")})
    return out


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
# ① 시드 생성
# ---------------------------------------------------------------------------

SYSTEM_SEARCH_EXPERT = (
    "You are a multilingual food-market search analyst who knows exactly what local consumers "
    "type into Google in each country. Answer only in JSON."
)


def _product_block(product: dict, fields: list = None) -> str:
    fields = fields or ["strengths", "ingredients", "certifications", "price"]
    lines = [f"- 제품명: {product['name']}"]
    for f in fields:
        lines.append(f"- {INPUT_LABELS_KO[f]}: {product.get(f) or '미입력'}")
    return "\n".join(lines)


def _dedupe_keywords(entries: list, limit: int, taken: set = None) -> list:
    taken = taken if taken is not None else set()
    out = []
    for s in entries or []:
        if not isinstance(s, dict):
            continue
        kw = " ".join(str(s.get("keyword", "")).split())
        if kw and kw.casefold() not in taken:
            taken.add(kw.casefold())
            out.append({"keyword": kw, "lang": s.get("lang", ""), "ko": s.get("ko", "")})
    return out[:limit]


def generate_seed_keywords(product: dict, profile: dict) -> dict:
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT,
        f"""[한국 수출 제품]
{_product_block(product)}

[대상 시장] {profile['name_ko']} (geo={profile['geo']}), 현지 검색 언어: {', '.join(profile['languages'])}

{profile['name_ko']} 소비자가 이 제품을 찾을 때 Google에 실제로 입력하는 검색어를 만드세요.

규칙:
1. seeds: 최대 {MAX_SEEDS}개, 각 1~3단어. 이 제품 자체를 가리키는 검색어.
   - 현지어/현지 문자 표기(예: 일본 キンパ, 태국 คิมบับ, 독일 koreanische ...)와
     로마자/영문 표기(예: kimbap, yakgwa)를 섞으세요. 영어권이면 영문만 써도 됩니다.
   - 현지에서 실제로 쓰일 법한 표기만. 한글 표기는 현지에서 널리 쓰일 때만 허용.
2. categories: 1~{MAX_CATEGORY_SEEDS}개. 이 제품이 속한 현지 카테고리 검색어
   (예: korean dessert, honey cookies, 韓国 お菓子). 'food', 'snack' 단독 같은 거대 일반명사 금지.
3. 각 검색어에 lang(영문 언어명)과 ko(한국어 뜻)를 붙이세요.

{{"seeds": [{{"keyword": "", "lang": "", "ko": ""}}],
  "categories": [{{"keyword": "", "lang": "", "ko": ""}}],
  "english_name": "제품의 가장 통용되는 영문명"}}""",
        temperature=0.2,
    )
    taken = set()
    seeds = _dedupe_keywords(data.get("seeds"), MAX_SEEDS, taken)
    if not seeds:
        raise PipelineError("검색어 후보를 만들지 못했습니다. 제품명을 더 구체적으로 입력해 주세요.")
    categories = data.get("categories")
    if not categories and isinstance(data.get("category"), dict):
        categories = [data["category"]]
    categories = _dedupe_keywords(categories, MAX_CATEGORY_SEEDS, taken)
    return {"seeds": seeds, "categories": categories, "english_name": data.get("english_name", "")}


# ---------------------------------------------------------------------------
# ② 수집 (제품+카테고리 시드 항상 함께, 부족하면 5년 → 글로벌)
# ---------------------------------------------------------------------------

def collect_related(trends: TrendsClient, seed_info: dict, geo: str) -> dict:
    """반환: {"records": [...], "data_level": 데이터를 보탠 가장 넓은 단계, "attempts": [...]}"""
    seed_kws = [s["keyword"] for s in seed_info["seeds"]]
    category_kws = [c["keyword"] for c in seed_info["categories"]]
    payload = (seed_kws + category_kws)[:MAX_PAYLOAD]
    levels = [("seed", geo, RELATED_TIMEFRAME)]
    if geo:
        levels += [("extended", geo, EXTENDED_TIMEFRAME), ("global", "", RELATED_TIMEFRAME)]

    records, attempts = [], []
    data_level = None
    exclude = seed_kws + category_kws
    for level, level_geo, timeframe in levels:
        try:
            result = trends.related(payload, level_geo, timeframe)
            error = None
        except Exception as e:
            result, error = {"queries": {}, "topics": {}}, str(e)
        added = 0
        for kind in ("queries", "topics"):
            for seed_kw, lists in (result.get(kind) or {}).items():
                for source in ("rising", "top"):
                    for row in lists.get(source) or []:
                        records.append({
                            **row, "source": source, "kind": "topic" if kind == "topics" else "query",
                            "seed": seed_kw, "is_category": seed_kw in category_kws,
                            "level": level, "geo": level_geo,
                        })
                        added += 1
        attempts.append({"level": level, "keywords": payload, "geo": level_geo or "GLOBAL",
                         "timeframe": timeframe, "count": added, "error": error})
        if added:
            data_level = level
        if len(_unique_queries(records, exclude)) >= MIN_POOL_SIZE:
            break
    return {"records": records, "data_level": data_level, "attempts": attempts}


def _unique_queries(records: list, exclude: list) -> set:
    excluded = {k.casefold() for k in exclude}
    return {r["query"].strip().casefold() for r in records} - excluded


# ---------------------------------------------------------------------------
# ③ 전처리
# ---------------------------------------------------------------------------

def _new_item(item_id: int, keyword: str, **overrides) -> dict:
    item = {
        "id": item_id, "keyword": keyword, "source": "top", "rising_value": None, "top_value": None,
        "is_breakout": False, "kind": "query", "topic_type": "", "is_category": False,
        "level": "seed", "geo": "", "is_estimated": False, "is_probe": False,
    }
    item.update(overrides)
    return item


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
            item = merged[key] = {"keyword": query, "sources": set(), "kinds": set(), "rising_value": None,
                                  "top_value": None, "topic_type": "", "is_category": r.get("is_category", False),
                                  "level": r["level"], "geo": r["geo"]}
        item["sources"].add(r["source"])
        item["kinds"].add(r.get("kind", "query"))
        item["topic_type"] = item["topic_type"] or r.get("topic_type", "")
        item["is_category"] = item["is_category"] and r.get("is_category", False)
        field = "rising_value" if r["source"] == "rising" else "top_value"
        if item[field] is None or r["value"] > item[field]:
            item[field] = r["value"]

    def sort_key(item):
        is_rising = item["rising_value"] is not None
        return (0 if is_rising else 1, -(item["rising_value"] or item["top_value"] or 0))

    out = []
    for i, item in enumerate(sorted(merged.values(), key=sort_key)[:MAX_KEYWORDS], start=1):
        rising = item["rising_value"]
        out.append(_new_item(
            i, item["keyword"],
            source="both" if len(item["sources"]) == 2 else next(iter(item["sources"])),
            rising_value=rising, top_value=item["top_value"],
            is_breakout=rising is not None and rising >= BREAKOUT_THRESHOLD,
            kind="query" if "query" in item["kinds"] else "topic", topic_type=item["topic_type"],
            is_category=item["is_category"], level=item["level"], geo=item["geo"],
        ))
    return out


def estimate_keywords(product: dict, profile: dict, seed_info: dict) -> list:
    """(최후 수단) Google 트렌드 데이터가 전혀 없을 때 LLM이 현지 검색어를 추정한다."""
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT,
        f"""[한국 수출 제품]
{_product_block(product)}

[대상 시장] {profile['name_ko']}, 현지 검색 언어: {', '.join(profile['languages'])}
[시드 검색어] {', '.join(s['keyword'] for s in seed_info['seeds'])}

Google 트렌드 데이터가 없어, 이 시장 소비자가 입력할 법한 연관 검색어를 추정해야 합니다.
현지어와 로마자/영문 표기를 섞어 12~16개를 만드세요. 다음 관점이 고르게 포함되게 하세요:
미디어/콘텐츠 유입, 구매 의도(레시피·정보 탐색 vs 구매·매장 찾기), 현지 경쟁 브랜드·대체재, 취식 상황/페어링.
각 검색어는 1~5단어, 원문 그대로 쓰세요.

{{"keywords": ["", ""]}}""",
        temperature=0.4,
    )
    seed_kws = [s["keyword"] for s in seed_info["seeds"]]
    records = [{"query": str(k), "value": 0, "source": "top", "kind": "query", "seed": seed_kws[0],
                "level": "estimated", "geo": profile["geo"]}
               for k in (data.get("keywords") or []) if str(k).strip()]
    items = preprocess_keywords(records, seed_kws)
    for item in items:
        item.update({"source": "estimated", "top_value": None, "is_estimated": True})
    return items


# ---------------------------------------------------------------------------
# ④ 분류
# ---------------------------------------------------------------------------

def classify_keywords(product: dict, profile: dict, items: list) -> dict:
    def label(it):
        text = f"[{it['id']}] {it['keyword']}"
        if it["rising_value"] is not None:
            text += " (급상승)"
        if it["kind"] == "topic":
            text += f" (연관 주제{': ' + it['topic_type'] if it['topic_type'] else ''})"
        return text

    listing = "\n".join(label(it) for it in items)
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT + " All explanations must be written in Korean.",
        f"""[한국 수출 제품]
{_product_block(product)}
[대상 시장] {profile['name_ko']} (현지 검색 언어: {', '.join(profile['languages'])})

[현지 연관 검색어·연관 주제 목록] (원문 그대로, 번호로만 참조하세요)
{listing}

각 항목을 아래 4개 분류 중 하나에 넣으세요.
- culture_trigger: 소비자가 이 제품군을 접하게 된 계기 (드라마·OTT·인플루언서·셀럽·축제·틱톡 트렌드·K-콘텐츠)
- intent_funnel: 구매 성숙도. stage를 반드시 지정:
    awareness(뜻·정체 탐색: what is, meaning), consideration(레시피·만드는 법·비교·후기·칼로리),
    purchase(near me, buy, 가격, amazon/costco 등 판매처, 브랜드+제품 구매 검색)
- category_perception: 현지 소비자가 비교·대체하는 것. **경쟁 브랜드명·경쟁 제품명**(예: Nescafé, Starbucks VIA),
    로컬 친숙 식품, 경쟁 카테고리
- consumption_habit: 취식 상황, 페어링(음료·술·디저트), 보관·섭취 형태(iced, with milk), 번들 소비

규칙:
- 브랜드라는 이유로 제외하지 마세요. 경쟁 브랜드는 category_perception, 브랜드+구매 검색은 intent_funnel(purchase).
- excluded에는 **명백히 무관한 것만** 넣으세요 (동음이의어, 전혀 다른 분야, 무관한 인물). 애매하면 가장 가까운 분류에 넣으세요.
- 목록에 있는 번호만 쓰세요. 새 검색어를 만들지 마세요. 한 번호는 한 곳에만.
- 분류당 관련성 높은 순서로 최대 {MAX_KEYWORDS_PER_CLUSTER}개.
- ko: 검색어의 한국어 해석(짧게, 검색 의도가 드러나게).
- summary_ko: 이 분류에서 읽히는 현지 소비 맥락 1~2문장 (한국어). 항목이 없으면 빈 문자열.
- tag_ko: 카드 뱃지 문구 (한국어 2~6자, 예: "미디어 결합도", "구매 단계 전환", "경쟁 브랜드", "취식 페어링").
- insight_ko: 수출기업이 할 행동 한 줄 (한국어, 25자 내외). 항목이 없으면 빈 문자열.

{{"clusters": {{
  "culture_trigger": {{"items": [{{"id": 1, "ko": ""}}], "summary_ko": "", "tag_ko": "", "insight_ko": ""}},
  "intent_funnel": {{"items": [{{"id": 2, "ko": "", "stage": "purchase"}}], "summary_ko": "", "tag_ko": "", "insight_ko": ""}},
  "category_perception": {{"items": [], "summary_ko": "", "tag_ko": "", "insight_ko": ""}},
  "consumption_habit": {{"items": [], "summary_ko": "", "tag_ko": "", "insight_ko": ""}}
}}, "excluded": [{{"id": 3, "reason_ko": ""}}]}}""",
        temperature=0.1,
    )
    return validate_classification(data, items)


def _stage_sort(cluster_items: list) -> None:
    """인지 → 탐색 → 구매 전환 순서로 보여줘야 퍼널 흐름이 읽힌다."""
    order = list(FUNNEL_STAGES_KO)
    cluster_items.sort(key=lambda k: order.index(k["stage"]) if k.get("stage") in order else len(order))


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
            _stage_sort(cluster_items)
        clusters[key] = {
            "summary": str(raw.get("summary_ko", "")).strip(),
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
            used.add(item_id)
            excluded.append({"keyword": by_id[item_id]["keyword"], "reason": entry.get("reason_ko", "")})
    return {"clusters": clusters, "excluded": excluded}


# ---------------------------------------------------------------------------
# ④-b 탐색 검증: 빈약한 분류에 탐색 검색어 제안 (검색량 확인은 ⑤-통합에서)
# ---------------------------------------------------------------------------

def add_probe_keywords(product: dict, profile: dict, clusters: dict, items: list, geo: str) -> int:
    """검색어가 PROBE_TRIGGER_COUNT개 미만인 분류에 탐색 검색어 후보를 넣는다. 반환: 추가된 후보 수.

    후보는 is_probe=True로 표시되고, ⑤-통합 조회에서 검색량이 확인된 것만 최종 화면에 남는다."""
    thin = [k for k in CLUSTER_KEYS if len(clusters[k]["keywords"]) < PROBE_TRIGGER_COUNT]
    if not thin:
        return 0
    guide = {
        "culture_trigger": "이 제품군과 엮여 화제가 된 드라마·예능·셀럽·틱톡 트렌드·레시피 챌린지 검색어",
        "intent_funnel": "구매 단계 검색어 (buy, near me, amazon, price, best brand 등과 제품명 결합)",
        "category_perception": "현지 소비자가 비교할 경쟁 브랜드·경쟁 제품명·로컬 대체 식품",
        "consumption_habit": "취식 상황·페어링 검색어 (with milk, iced, with coffee, for breakfast 등과 제품명 결합)",
    }
    request = "\n".join(f"- {k}: {guide[k]}" for k in thin)
    data = _chat_json(
        SYSTEM_SEARCH_EXPERT + " All explanations must be written in Korean.",
        f"""[한국 수출 제품]
{_product_block(product)}
[대상 시장] {profile['name_ko']} (현지 검색 언어: {', '.join(profile['languages'])})

아래 분류는 Google 연관 검색어에서 신호가 부족했습니다. 분류마다 {profile['name_ko']} 소비자가 실제로 검색할 법한
탐색 검색어를 최대 {MAX_PROBES_PER_CLUSTER}개 제안하세요. 이 검색어들은 Google 트렌드로 실제 검색량을 확인한 뒤에만 사용됩니다.
{request}

규칙: 각 1~4단어, 현지어 또는 현지에서 통용되는 영문 표기, 거대 일반명사 단독 금지.
intent_funnel에는 stage(awareness/consideration/purchase)를 붙이세요. ko는 한국어 해석.

{{"probes": {{"culture_trigger": [{{"keyword": "", "ko": ""}}], "intent_funnel": [{{"keyword": "", "ko": "", "stage": "purchase"}}]}}}}""",
        temperature=0.3,
    )
    taken = {it["keyword"].casefold() for it in items}
    next_id = max([it["id"] for it in items] + [0]) + 1
    added = 0
    for key in thin:
        for entry in ((data.get("probes") or {}).get(key) or [])[:MAX_PROBES_PER_CLUSTER]:
            if not isinstance(entry, dict):
                continue
            kw = " ".join(str(entry.get("keyword", "")).split())
            if not kw or kw.casefold() in taken or len(kw.split()) > 5:
                continue
            taken.add(kw.casefold())
            stage = entry.get("stage") if key == "intent_funnel" else None
            clusters[key]["keywords"].append(_new_item(
                next_id, kw, source="probe", geo=geo, is_probe=True, level="probe",
                ko=str(entry.get("ko", "")).strip(), stage=stage if stage in FUNNEL_STAGES_KO else None,
            ))
            next_id += 1
            added += 1
    return added


# ---------------------------------------------------------------------------
# ⑤ 시장 맥락 보강: 경쟁 제품 후보 + 바이어 체크포인트 (AI 참고)
# ---------------------------------------------------------------------------

def is_generic_target(name: str) -> bool:
    """"Korean Snacks", "Asian Sweets"처럼 경쟁 '제품'이 아닌 카테고리 이름이면 True."""
    words = re.findall(r"[a-zA-Z]+", (name or "").lower())
    if "korean" in words or "korea" in words or "한국" in (name or ""):
        return True
    return bool(words) and all(w in GENERIC_TARGET_WORDS for w in words)


def generate_market_context(product: dict, profile: dict, clusters: dict) -> dict:
    perception = ", ".join(k["keyword"] for k in clusters["category_perception"]["keywords"]) or "없음"
    data = _chat_json(
        "You are a food-retail analyst who knows which products actually sit on shelves in each country. "
        "Be factual; if unsure, leave the field empty instead of guessing. Answer only in JSON, explanations in Korean.",
        f"""[한국 수출 제품]
{_product_block(product, ["strengths", "ingredients", "certifications", "price", "channel"])}
[사용자가 알고 있는 경쟁 제품·가격] {product.get('known_competitors') or '없음'}
[대상 시장] {profile['name_ko']}
[현지 검색에서 보인 경쟁 신호] {perception}

1) competitors: {profile['name_ko']} 매대·온라인몰에서 이 제품과 실제로 경쟁하는 제품 {MAX_COMPETITORS}개 이내.
   - 반드시 "브랜드 + 제품명"(예: Nescafé Taster's Choice 3in1) 또는 구체적인 현지 음식명(예: Baklava).
   - "Korean snacks", "Asian sweets", "honey cookies" 같은 카테고리 이름 금지. 한국 제품 금지.
   - 사용자가 알려준 경쟁 제품이 있으면 가장 먼저 넣고 from_user=true.
   - search_term: 현지 소비자가 이 경쟁 제품을 Google에 검색할 때 쓰는 1~4단어 표기
   - features_ko: 특징 한 줄(한국어), price_local: 현지 소매가(현지 통화, 모르면 빈 문자열),
     channel_ko: 주요 판매 채널, confidence: high/medium/low (이 제품이 실제로 있다는 확신도)
2) buyer_checkpoints: {profile['name_ko']} 식품 바이어가 이 카테고리 수입품을 검토할 때 주로 확인하는 항목 3~4개
   (예: 유통기한, 라벨 규정, 인증, 물류 조건). item_ko와 why_ko(한 줄).

{{"competitors": [{{"name": "", "name_ko": "", "search_term": "", "features_ko": "", "price_local": "",
                    "channel_ko": "", "confidence": "medium", "from_user": false}}],
  "buyer_checkpoints": [{{"item_ko": "", "why_ko": ""}}]}}""",
        temperature=0.2,
        strategy=True,
    )
    competitors, taken = [], set()
    for c in data.get("competitors") or []:
        if not isinstance(c, dict):
            continue
        name = " ".join(str(c.get("name", "")).split())
        if not name or name.casefold() in taken or is_generic_target(name):
            continue
        taken.add(name.casefold())
        from_user = bool(c.get("from_user")) and bool(product.get("known_competitors"))
        competitors.append({
            "id": f"C{len(competitors) + 1}",
            "name": name,
            "name_ko": str(c.get("name_ko", "")).strip(),
            "search_term": " ".join(str(c.get("search_term") or name).split()),
            "features_ko": str(c.get("features_ko", "")).strip(),
            "price_local": str(c.get("price_local", "")).strip(),
            "price_evidence": "user" if from_user else "ai",
            "channel_ko": str(c.get("channel_ko", "")).strip(),
            "confidence": c.get("confidence") if c.get("confidence") in ("high", "medium", "low") else "low",
            "from_user": from_user,
            "vs_anchor": None, "has_volume": None,
        })
        if len(competitors) >= MAX_COMPETITORS:
            break
    checkpoints = [{"item": str(c.get("item_ko", "")).strip(), "why": str(c.get("why_ko", "")).strip()}
                   for c in (data.get("buyer_checkpoints") or [])[:4]
                   if isinstance(c, dict) and str(c.get("item_ko", "")).strip()]
    return {"competitors": competitors, "buyer_checkpoints": checkpoints}


# ---------------------------------------------------------------------------
# ⑤-통합: 증감 배지 + 탐색 검증 + 경쟁 제품 검색량 비교 (5년 주간 조회 한 단계)
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


def _mean_last_year(series: list):
    if not series:
        return None
    window = series[-52:]
    return sum(window) / len(window)


def attach_trend_metrics(trends: TrendsClient, clusters: dict, competitors: list,
                         anchor: str, geo: str) -> list:
    """분류 검색어·탐색 후보·경쟁 제품을 한 단계에서 5년 주간 조회한다. 반환: 경고 목록.

    Google은 묶음(최대 5개) 안에서 최댓값 기준으로 0~100을 매긴다. 그래서
    - 증감률(YoY)은 검색어별 비율이라 묶음 스케일과 무관하고,
    - 묶음 간 비교를 위해 우리 제품 시드(anchor)를 모든 묶음에 넣어 "우리 제품 대비 ×N"을 구한다."""
    warnings = []
    entries = []  # (target dict, keyword, geo, kind)
    for c in clusters.values():
        for kw in c["keywords"]:
            kw.update({"yoy_pct": None, "yoy_status": "insufficient", "has_volume": None, "vs_anchor": None})
            if not kw["is_estimated"]:
                entries.append((kw, kw["keyword"], kw["geo"], "keyword"))
    for comp in competitors:
        entries.append((comp, comp["search_term"], geo, "competitor"))

    by_geo = {}
    for entry in entries:
        by_geo.setdefault(entry[2], []).append(entry)

    anchor_cf = anchor.casefold()
    solo_candidates, failed = [], 0
    for group_geo, group in by_geo.items():
        others = [e for e in group if e[1].casefold() != anchor_cf]
        for i in range(0, len(others), MAX_PAYLOAD - 1):
            batch = others[i:i + MAX_PAYLOAD - 1]
            keywords = [anchor] + [e[1] for e in batch]
            try:
                series_map = trends.interest_over_time(keywords, group_geo)
            except Exception as e:
                logger.warning("검색량 조회 실패(%s): %s", group_geo or "GLOBAL", e)
                failed += len(batch)
                for target, *_ in batch:
                    target["lookup_failed"] = True
                continue
            anchor_mean = _mean_last_year(series_map.get(anchor) or [])
            batch_has_signal = any(max(series_map.get(k) or [0]) > 0 for k in keywords)
            for target, keyword, _, kind in batch:
                series = series_map.get(keyword) or []
                mean = _mean_last_year(series)
                target["has_volume"] = bool(mean and mean > 0)
                target["vs_anchor"] = round(mean / anchor_mean, 1) if (mean and anchor_mean) else None
                target["anchor_zero"] = bool(mean) and not anchor_mean
                if kind == "keyword":
                    target.update(compute_yoy(series))
                    if target["yoy_status"] == "insufficient" and batch_has_signal:
                        solo_candidates.append(target)

    # 큰 검색어와 같이 묶여 0으로 눌렸을 수 있는 검색어는 단독으로 한 번 더 조회
    for target in solo_candidates[:MAX_SOLO_RETRY]:
        try:
            series = trends.interest_over_time([target["keyword"]], target["geo"]).get(target["keyword"]) or []
        except Exception as e:
            logger.warning("단독 재조회 실패(%s): %s", target["keyword"], e)
            continue
        target.update(compute_yoy(series))
        mean = _mean_last_year(series)
        target["has_volume"] = target["has_volume"] or bool(mean and mean > 0)

    if failed:
        warnings.append(f"검색어·경쟁 제품 {failed}개의 검색량을 Google 트렌드에서 받아오지 못했습니다.")
    return warnings


def finalize_clusters(clusters: dict) -> int:
    """검색량이 확인되지 않은 탐색 후보를 버리고, 배지·근거를 확정한다. 반환: 버린 탐색 후보 수."""
    dropped = 0
    for key, c in clusters.items():
        kept = []
        for kw in c["keywords"]:
            if kw["is_probe"] and not kw.get("has_volume"):
                dropped += 1
                continue
            kw["evidence"] = "estimated" if kw["is_estimated"] else ("probe" if kw["is_probe"] else "measured")
            kw["badge"] = decide_badge(kw)
            kept.append(kw)
        c["keywords"] = kept[:MAX_KEYWORDS_PER_CLUSTER]
        if key == "intent_funnel":
            _stage_sort(c["keywords"])
        if not c["summary"] and c["keywords"]:
            c["summary"] = "탐색 검색어로 확인된 신호입니다." if all(k["is_probe"] for k in c["keywords"]) else ""
    return dropped


def decide_badge(kw: dict):
    """배지 우선순위: 전년 대비 증감 → 구글 급상승 % → 없음."""
    if kw.get("yoy_pct") is not None:
        return {"kind": "yoy", "pct": kw["yoy_pct"]}
    if kw.get("rising_value") is not None and not kw["is_estimated"] and not kw["is_probe"]:
        return {"kind": "rising", "pct": kw["rising_value"]}
    return None


def build_competitor_search(competitors: list) -> list:
    """경쟁 인식 카드의 '우리 제품 대비 검색량' 막대 데이터."""
    rows = [c for c in competitors if c.get("has_volume")]
    # 우리 제품 검색량이 0이라 배수를 못 구한 경쟁 제품(= 압도적으로 큼)을 맨 앞에
    rows.sort(key=lambda c: -(10 ** 6 if c.get("anchor_zero") else (c["vs_anchor"] or 0)))
    comparable = [c["vs_anchor"] for c in rows if c["vs_anchor"]]
    max_ratio = max(comparable + [1.0])
    return [{
        "name": c["name"], "name_ko": c["name_ko"], "vs_anchor": c["vs_anchor"],
        "anchor_zero": c.get("anchor_zero", False),
        "bar_pct": 100 if c.get("anchor_zero") else round(min(c["vs_anchor"] or 0, max_ratio) / max_ratio * 100),
    } for c in rows]


# ---------------------------------------------------------------------------
# ⑦ USP 매트릭스
# ---------------------------------------------------------------------------

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


def headline_issues(headline: str, benefit_phrase: str) -> list:
    """헤드라인 코드 검사: 상투어, USP 핵심어(benefit_phrase)와의 연결."""
    issues = []
    h = (headline or "").lower()
    if not h.strip():
        return ["헤드라인이 비어 있음"]
    for pattern in CLICHE_PATTERNS:
        if re.search(pattern, h):
            issues.append(f"상투어 사용({re.sub(r'[^a-z ]', '', pattern.replace(chr(92) + 'b', ''))})")
            break
    b = (benefit_phrase or "").lower().strip()
    if b:
        words = [w for w in re.findall(r"[a-zà-ÿ]{4,}", b) if w not in HEADLINE_STOPWORDS]
        if words:
            linked = any(w[:5] in h for w in words)  # 어미 변화(sticky/stick) 허용
        else:  # 한자·일본어·태국어 등 공백 없는 언어
            linked = b[:2] in h
        if not linked:
            issues.append("헤드라인에 USP 핵심 이점이 드러나지 않음")
    return issues


def _competitor_block(competitors: list) -> str:
    lines = []
    for c in competitors:
        verified = (f"현지 검색 확인, 우리 제품 대비 검색량 ×{c['vs_anchor']}" if c["vs_anchor"]
                    else "현지 검색 확인" if c.get("has_volume") else "검색 흔적 미확인")
        lines.append(f"- {c['id']}: {c['name']} ({c['name_ko']}) / 특징: {c['features_ko'] or '미상'} / "
                     f"가격: {c['price_local'] or '미상'} / {verified}")
    return "\n".join(lines)


def _usp_prompt(product: dict, profile: dict, competitors: list, trend_block: str, extra: str = "") -> str:
    field_keys = ", ".join(f"{k}({INPUT_LABELS_KO[k]})" for k in ["strengths", "ingredients", "certifications", "price",
                                                                    "shelf_life", "pack_format"])
    return f"""[한국 수출 제품 스펙 - 우리의 해결은 이 항목만 근거로]
{_product_block(product, ["strengths", "ingredients", "certifications", "price", "shelf_life", "pack_format"])}

[대상 시장] {profile['name_ko']}, 바이어 언어: {profile['buyer_language']}

[경쟁 제품 후보]
{_competitor_block(competitors)}

[현지 검색 트렌드 요약]
{trend_block}

경쟁 제품 후보 중 {MAX_USP_ROWS}개를 골라(검색 확인된 것 우선) USP 행을 만드세요.
각 행은 하나의 논리로 이어져야 합니다: 경쟁 제품의 불만 → 우리의 해결 → 그 대비가 드러나는 헤드라인.
- competitor_id: 위 목록의 ID
- consumer_pain_ko: 현지 소비자가 그 경쟁 제품에서 느끼는 구체적 불만 (한국어 한 문장)
- our_fix_ko: 그 불만을 우리 제품이 어떻게 해결하는지 (한국어 한 문장). 스펙에 없는 인증·효능·수치 금지.
- evidence_fields: our_fix_ko의 근거 항목 키 배열. 사용 가능: {field_keys}
- benefit_phrase: 우리 해결의 핵심 이점을 {profile['buyer_language']} 2~5단어로 (예: "no sticky fingers")
- pitch_headline: 바이어 대상 한 줄 ({profile['buyer_language']}). benefit_phrase의 핵심 단어를 반드시 포함하고
  경쟁 제품 대비 차이가 드러나게. "Experience", "Discover", "Unique", "Taste the Tradition", "Savor" 같은 상투어 금지.
- pitch_headline_ko: 헤드라인의 한국어 번역
{extra}
{{"rows": [{{"competitor_id": "C1", "consumer_pain_ko": "", "our_fix_ko": "", "evidence_fields": ["strengths"],
            "benefit_phrase": "", "pitch_headline": "", "pitch_headline_ko": ""}}]}}"""


def _trend_block(clusters: dict) -> str:
    lines = []
    for key in CLUSTER_KEYS:
        c = clusters[key]
        kws = ", ".join(
            f"{k['keyword']}({k.get('ko', '')}"
            + (f", 전년 대비 {k['yoy_pct']:+d}%" if k.get("yoy_pct") is not None else "")
            + (f", {FUNNEL_STAGES_KO[k['stage']]}" if k.get("stage") else "") + ")"
            for k in c["keywords"]
        ) or "신호 없음"
        lines.append(f"- {CLUSTER_META[key]['short_ko']}: {c['summary'] or '-'} / 검색어: {kws}")
    return "\n".join(lines)


def _build_usp_row(raw: dict, comp: dict, product: dict) -> dict:
    fields = [f for f in (raw.get("evidence_fields") or []) if f in INPUT_LABELS_KO and product.get(f)]
    row = {
        "competitor_id": comp["id"],
        "target": comp["name"], "target_ko": comp["name_ko"],
        "features_ko": comp["features_ko"],
        "price_local": comp["price_local"], "price_evidence": comp["price_evidence"],
        "target_evidence": "user" if comp["from_user"] else ("search_verified" if comp.get("has_volume") else "ai"),
        "vs_anchor": comp.get("vs_anchor"),
        "consumer_pain_ko": str(raw.get("consumer_pain_ko", "")).strip(),
        "our_fix_ko": str(raw.get("our_fix_ko", "")).strip(),
        "evidence": [INPUT_LABELS_KO[f] for f in fields],
        "benefit_phrase": str(raw.get("benefit_phrase", "")).strip(),
        "pitch_headline": str(raw.get("pitch_headline", "")).strip(),
        "pitch_headline_ko": str(raw.get("pitch_headline_ko", "")).strip(),
    }
    row["unsupported_certs"] = find_unsupported_certs(
        f"{row['our_fix_ko']} {row['pitch_headline']} {row['pitch_headline_ko']}", product.get("certifications", ""))
    row["issues"] = headline_issues(row["pitch_headline"], row["benefit_phrase"])
    if not fields:
        row["issues"].append("근거 항목 없음")
    return row


def generate_usp(product: dict, profile: dict, clusters: dict, competitors: list) -> list:
    if not competitors:
        return []
    by_id = {c["id"]: c for c in competitors}
    ordered = sorted(competitors, key=lambda c: (not c["from_user"], not c.get("has_volume"),
                                                 {"high": 0, "medium": 1, "low": 2}[c["confidence"]]))
    trend_block = _trend_block(clusters)
    system = ("You are a K-food export strategist writing buyer-facing USP lines for trade shows. "
              "Analysis in Korean; buyer-facing copy in the buyer's language. Answer only in JSON.")

    def parse(data, allowed_ids):
        rows, seen = [], set()
        for raw in (data or {}).get("rows") or []:
            if not isinstance(raw, dict):
                continue
            cid = str(raw.get("competitor_id", "")).strip()
            if cid not in allowed_ids or cid in seen:
                continue
            seen.add(cid)
            rows.append(_build_usp_row(raw, by_id[cid], product))
        return rows

    data = _chat_json(system, _usp_prompt(product, profile, ordered, trend_block), temperature=0.5, strategy=True)
    rows = parse(data, set(by_id))[:MAX_USP_ROWS]

    # 코드 검사에 걸린 행만 문제를 알려주고 1회 재생성
    failing = [r for r in rows if r["issues"] or r["unsupported_certs"]]
    if failing:
        def problems(r):
            found = list(r["issues"])
            if r["unsupported_certs"]:
                found.append(f"입력하지 않은 인증 언급({', '.join(r['unsupported_certs'])})")
            return ", ".join(found)

        feedback = "\n".join(f"- {r['competitor_id']}: {problems(r)}" for r in failing)
        extra = f"\n[재작성 요청] 아래 행만 다시 작성하세요. 같은 competitor_id를 쓰세요.\n{feedback}\n"
        retry_comps = [by_id[r["competitor_id"]] for r in failing]
        retry = parse(_chat_json(system, _usp_prompt(product, profile, retry_comps, trend_block, extra),
                                 temperature=0.4, strategy=True), {c["id"] for c in retry_comps})
        fixed = {r["competitor_id"]: r for r in retry if not r["issues"] and not r["unsupported_certs"]}
        rows = [fixed.get(r["competitor_id"], r) for r in rows]
    for r in rows:
        if r["issues"]:
            logger.info("USP 행 품질 경고(%s): %s", r["target"], r["issues"])
    return rows


# ---------------------------------------------------------------------------
# ⑧ 부스 컨셉
# ---------------------------------------------------------------------------

def _numbers(text: str) -> set:
    return {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)*", text or "")}


def has_pitch_inputs(product: dict) -> bool:
    return any(product.get(f) for f in PITCH_INPUT_FIELDS)


def validate_pitch_blocks(blocks: list, product: dict) -> list:
    """피칭 월 블록: 출처 입력 항목이 실제로 입력돼 있고, 블록 속 숫자가 모두 그 입력값에 있어야 통과."""
    valid = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        field = b.get("source_field")
        if field not in PITCH_SOURCE_FIELDS or not product.get(field):
            continue
        text = f"{b.get('headline', '')} {b.get('value', '')} {b.get('headline_ko', '')}"
        if not _numbers(text) <= _numbers(product[field]):
            continue
        valid.append({
            "headline": str(b.get("headline", "")).strip(),
            "headline_ko": str(b.get("headline_ko", "")).strip(),
            "value": str(b.get("value", "")).strip(),
            "source_label": INPUT_LABELS_KO[field],
        })
        if len(valid) >= MAX_PITCH_BLOCKS:
            break
    return valid


def _resolve_refs(refs, clusters: dict, usp_rows: list, product: dict) -> list:
    """LLM이 준 근거 참조(K12 / U1 / input:shelf_life)를 화면용 한국어 라벨로 바꾼다. 모르는 참조는 버림."""
    kw_by_id = {f"K{k['id']}": k["keyword"] for c in clusters.values() for k in c["keywords"]}
    labels = []
    for ref in refs or []:
        ref = str(ref).strip()
        if ref in kw_by_id:
            label = f"검색어 {kw_by_id[ref]}"
        elif re.fullmatch(r"U[1-9]", ref) and int(ref[1:]) <= len(usp_rows):
            label = f"USP: {usp_rows[int(ref[1:]) - 1]['target']}"
        elif ref.startswith("input:") and product.get(ref[6:]) and ref[6:] in INPUT_LABELS_KO:
            label = f"입력: {INPUT_LABELS_KO[ref[6:]]}"
        else:
            continue
        if label not in labels:
            labels.append(label)
    return labels[:3]


def generate_booth(product: dict, profile: dict, clusters: dict, usp_rows: list, checkpoints: list) -> dict:
    buyer_lang = profile["buyer_language"]
    pitch_enabled = has_pitch_inputs(product)
    kw_lines = "\n".join(
        f"- K{k['id']}: {k['keyword']} ({k.get('ko', '')}, {CLUSTER_META[key]['short_ko']})"
        for key, c in clusters.items() for k in c["keywords"]) or "- 없음"
    usp_lines = "\n".join(
        f"- U{i}: 경쟁 {r['target']} / 불만: {r['consumer_pain_ko']} / 해결: {r['our_fix_ko']} / 헤드라인: {r['pitch_headline']}"
        for i, r in enumerate(usp_rows, start=1)) or "- 없음"
    provided = [f for f in PITCH_SOURCE_FIELDS if product.get(f)]
    input_lines = "\n".join(f"- input:{f} ({INPUT_LABELS_KO[f]}): {product[f]}" for f in provided) or "- 없음"
    checkpoint_lines = "\n".join(f"- {c['item']}: {c['why']}" for c in checkpoints) or "- 없음"
    pitch_spec = (f"""  "pitching_wall": {{"title": "", "title_ko": "", "refs": [],
    "blocks": [{{"headline": "({buyer_lang})", "headline_ko": "", "value": "입력값 그대로", "source_field": "shelf_life"}}]}},"""
                  if pitch_enabled else "")
    pitch_rule = (f"""- pitching_wall: 인포그래픽 블록 {MAX_PITCH_BLOCKS}개 이내. 각 블록의 숫자·값은 반드시 [입력값]에 있는 그대로.
  source_field는 그 값을 가져온 입력 키. 바이어 체크포인트에 답하는 블록을 우선.""" if pitch_enabled else "")

    data = _chat_json(
        "You are a trade-show booth planner for Korean food exporters. Every idea must be traceable to the "
        "given evidence. Analysis in Korean; buyer-facing copy in the buyer's language. Answer only in JSON.",
        f"""[제품] {product['name']} → [시장] {profile['name_ko']}, 바이어 언어: {buyer_lang}

[트렌드 검색어] (근거 참조 ID: K번호)
{kw_lines}

[USP 행] (근거 참조 ID: U번호)
{usp_lines}

[입력값] (근거 참조 ID: input:키)
{input_lines}

[바이어 체크포인트]
{checkpoint_lines}

박람회 부스 카드를 만드세요. 모든 카드에 refs(위 근거 참조 ID 1~3개)를 붙이세요.
- headline_slogan: 슬로건(slogan, {buyer_lang})과 한국어(slogan_ko), 보조 문구(sub_copy/sub_copy_ko),
  key_visual_ko(부스 메인 비주얼 묘사 한 문장)
- sampling_strategy: compare_with(비교 시식할 USP 행 ID, 예: "U1"), serving_ko(제공 형태),
  staff_line(직원 안내 멘트, {buyer_lang})/staff_line_ko, collect_ko(시식 후 받아낼 것: 명함·피드백 등)
{pitch_rule}
- packaging_display: layout_ko(진열 방법 2~3개 배열), pop_copy(매대 POP 문구, {buyer_lang})/pop_copy_ko
- title은 {buyer_lang} 짧은 컨셉명, title_ko는 한국어. 입력값에 없는 숫자는 쓰지 마세요.

{{"headline_slogan": {{"title": "", "title_ko": "", "slogan": "", "slogan_ko": "", "sub_copy": "", "sub_copy_ko": "",
                      "key_visual_ko": "", "refs": []}},
  "sampling_strategy": {{"title": "", "title_ko": "", "compare_with": "U1", "serving_ko": "", "staff_line": "",
                        "staff_line_ko": "", "collect_ko": "", "refs": []}},
{pitch_spec}
  "packaging_display": {{"title": "", "title_ko": "", "layout_ko": [], "pop_copy": "", "pop_copy_ko": "", "refs": []}}}}""",
        temperature=0.6,
        strategy=True,
    )

    def text(raw, key):
        return str((raw or {}).get(key, "") or "").strip()

    slogan_raw = data.get("headline_slogan") or {}
    sampling_raw = data.get("sampling_strategy") or {}
    display_raw = data.get("packaging_display") or {}
    compare_ref = text(sampling_raw, "compare_with")
    compare_with = None
    if re.fullmatch(r"U[1-9]", compare_ref) and int(compare_ref[1:]) <= len(usp_rows):
        compare_with = usp_rows[int(compare_ref[1:]) - 1]["target"]

    booth = {
        "headline_slogan": {k: text(slogan_raw, k) for k in
                            ("title", "title_ko", "slogan", "slogan_ko", "sub_copy", "sub_copy_ko", "key_visual_ko")},
        "sampling_strategy": {k: text(sampling_raw, k) for k in
                              ("title", "title_ko", "serving_ko", "staff_line", "staff_line_ko", "collect_ko")},
        "pitching_wall": None,
        "packaging_display": {k: text(display_raw, k) for k in ("title", "title_ko", "pop_copy", "pop_copy_ko")},
    }
    booth["sampling_strategy"]["compare_with"] = compare_with
    booth["packaging_display"]["layout_ko"] = [str(x).strip() for x in (display_raw.get("layout_ko") or [])
                                               if str(x).strip()][:3]
    for key, raw in (("headline_slogan", slogan_raw), ("sampling_strategy", sampling_raw),
                     ("packaging_display", display_raw)):
        booth[key]["refs"] = _resolve_refs(raw.get("refs"), clusters, usp_rows, product)

    if pitch_enabled:
        wall_raw = data.get("pitching_wall") or {}
        blocks = validate_pitch_blocks(wall_raw.get("blocks"), product)
        if blocks:
            booth["pitching_wall"] = {"title": text(wall_raw, "title"), "title_ko": text(wall_raw, "title_ko"),
                                      "blocks": blocks,
                                      "refs": _resolve_refs(wall_raw.get("refs"), clusters, usp_rows, product)}
    return booth


# ---------------------------------------------------------------------------
# 전체 파이프라인
# ---------------------------------------------------------------------------

def run_trend_usp(product: dict, country: str, use_cache: bool = True) -> dict:
    """제품 스펙(한국어) + 대상 국가 → 한국어 대시보드용 결과 JSON."""
    product = {k: (product.get(k) or "").strip() for k in PRODUCT_FIELDS}
    if not product["name"]:
        raise PipelineError("제품명을 입력해 주세요.")

    profile = resolve_country_profile(country)
    trends = TrendsClient(hl=profile["hl"], use_cache=use_cache)
    warnings = []

    # ①~③ 시드 → 수집 → 전처리
    seed_info = generate_seed_keywords(product, profile)
    seed_keywords = [s["keyword"] for s in seed_info["seeds"]]
    collected = collect_related(trends, seed_info, profile["geo"])
    exclude = seed_keywords + [c["keyword"] for c in seed_info["categories"]]
    items = preprocess_keywords(collected["records"], exclude)
    data_level = collected["data_level"]
    is_estimated = not items
    if is_estimated:
        data_level = "estimated"
        items = estimate_keywords(product, profile, seed_info)
        errors = [a["error"] for a in collected["attempts"] if a["error"]]
        warnings.append("Google 트렌드에서 연관 검색어를 받지 못해 AI 추정 검색어로 분석했습니다. "
                        "수치 배지는 표시하지 않습니다." + (f" (원인: {errors[-1][:120]})" if errors else ""))
        if not items:
            raise PipelineError("연관 검색어를 수집하지도, 추정하지도 못했습니다.")
    elif data_level in ("extended", "global"):
        warnings.append(f"연관 검색어가 적어 {DATA_LEVEL_LABELS_KO[data_level]} 데이터를 함께 사용했습니다.")

    # ④ 분류 → ④-b 탐색 후보
    classification = classify_keywords(product, profile, items)
    clusters = classification["clusters"]
    probe_count = 0 if is_estimated else add_probe_keywords(product, profile, clusters, items, profile["geo"])

    # ⑤ 시장 맥락 → ⑤-통합 검색량 조회
    context = generate_market_context(product, profile, clusters)
    competitors = context["competitors"]
    if not is_estimated:
        warnings += attach_trend_metrics(trends, clusters, competitors, seed_keywords[0], profile["geo"])
    else:
        for c in clusters.values():
            for kw in c["keywords"]:
                kw.update({"yoy_pct": None, "yoy_status": "estimated", "has_volume": None, "vs_anchor": None})

    # ⑥ 배지 확정 (검색량 없는 탐색 후보 제거)
    finalize_clusters(clusters)
    kept_probes = sum(1 for c in clusters.values() for k in c["keywords"] if k["is_probe"])

    # ⑦ USP → ⑧ 부스
    usp_rows = generate_usp(product, profile, clusters, competitors)
    if any(r["unsupported_certs"] for r in usp_rows):
        warnings.append("USP 문구에 입력하지 않은 인증이 언급되었습니다. 해당 행의 경고를 확인하세요.")
    booth = generate_booth(product, profile, clusters, usp_rows, context["buyer_checkpoints"])

    return {
        "product_info": product,
        "trend_analysis": clusters,
        "competitor_search": build_competitor_search(competitors),
        "competitors": competitors,
        "usp_matrix": usp_rows,
        "booth_concept": booth,
        "buyer_checkpoints": context["buyer_checkpoints"],
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
            "category_keywords": seed_info["categories"],
            "english_name": seed_info["english_name"],
            "data_level": data_level,
            "data_level_label_ko": DATA_LEVEL_LABELS_KO[data_level],
            "is_estimated": is_estimated,
            "collection_attempts": collected["attempts"],
            "keyword_pool_size": len(items),
            "probe_candidates": probe_count,
            "probe_verified": kept_probes,
            "has_pitch_inputs": has_pitch_inputs(product),
            "anchor_keyword": seed_keywords[0],
            "models": {"light": _model_name(False), "strategy": _model_name(True)},
            "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "warnings": warnings,
        },
    }

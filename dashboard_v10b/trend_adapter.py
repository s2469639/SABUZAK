"""섹션 1·2 연결.

섹션 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링
        trend_usp_v1의 pytrends 함수들을 "분류·검색량 배지"까지만 조합한다
        (시장 맥락·USP·부스 단계는 쓰지 않아 호출 비용을 줄임. 부스 컨셉은 섹션 4가 담당)
섹션 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석
        j_test/retail_research.py의 analyze_retail_market()을 그대로 호출한다 (booth_solution은 쓰지 않음)

두 폴더의 코드는 수정하지 않는다.
"""

import os
import sys

from country_names import COUNTRY_EN

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREND_DIR = os.path.join(ROOT_DIR, "trend_usp_v1")
J_TEST_DIR = os.path.join(ROOT_DIR, "j_test")


def _load_trend_usp():
    """trend_usp_v1/trend_usp.py를 불러온다.

    trend_usp_v1과 tavily_v9 둘 다 'constants'라는 패키지를 가지고 있어서, trend_usp를 불러온 뒤
    sys.modules에서 trend_usp_v1의 constants를 지워 tavily_v9가 자기 constants를 찾을 수 있게 한다.
    (trend_usp 모듈은 필요한 상수를 이미 자기 이름공간에 가져와 두었으므로 지워도 동작한다)"""
    sys.path.insert(0, TREND_DIR)
    try:
        import trend_usp  # noqa: E402
    finally:
        sys.path.remove(TREND_DIR)
        for name in [m for m in sys.modules if m == "constants" or m.startswith("constants.")]:
            del sys.modules[name]
    return trend_usp


trend_usp = _load_trend_usp()


def _upgrade_trend_usp():
    """섹션 1(trend_usp_v1)의 분류 모델을 상위 모델로 바꾸고 클라이언트를 감싼다 (.env TREND_USP_MODEL이 있으면 그 값이 우선)."""
    import model_upgrade  # noqa: E402
    trend_usp.DEFAULT_LIGHT_MODEL = model_upgrade.TASK_MODEL
    original = trend_usp._get_openai_client
    cache = {}

    def get_client():
        if "c" not in cache:
            cache["c"] = model_upgrade.wrap(original())
        return cache["c"]

    trend_usp._get_openai_client = get_client


_upgrade_trend_usp()
_retail_module = None


def _retail():
    """j_test/retail_research.py는 불러오는 순간 OpenAI·Tavily 클라이언트를 만들기 때문에 (.env가 읽힌 뒤) 처음 쓸 때 불러온다.
    예전 brotli가 깔린 PC에서도 동작하도록 OpenAI 클라이언트만 br 압축을 요청하지 않는 것으로 바꿔 끼운다(원본 파일은 그대로)."""
    global _retail_module
    if _retail_module is None:
        if J_TEST_DIR not in sys.path:
            sys.path.append(J_TEST_DIR)
        import retail_research  # noqa: E402
        from http_compat import SAFE_HEADERS  # noqa: E402  (trend_usp_v1/http_compat.py, 이미 로드됨)
        from openai import OpenAI
        import model_upgrade  # noqa: E402  (코드에 적힌 gpt-4o-mini를 상위 모델로 바꿔 보냄)
        retail_research.openai_client = model_upgrade.wrap(
            OpenAI(api_key=os.getenv("OPENAI_API_KEY"), default_headers=SAFE_HEADERS))
        _retail_module = retail_research
    return _retail_module


KOREAN_BY_EN = {}
for _ko, _en in COUNTRY_EN.items():
    if any("가" <= ch <= "힣" for ch in _ko):
        KOREAN_BY_EN.setdefault(_en.lower(), _ko)


def korean_country(country: str) -> str:
    """j_test는 한국어 국가명(말레이시아 등)으로 통화를 찾으므로, 영문으로 입력해도 한국어로 바꿔 넘긴다."""
    c = (country or "").strip()
    if any("가" <= ch <= "힣" for ch in c):
        return c
    return KOREAN_BY_EN.get(COUNTRY_EN.get(c.lower(), c).lower(), c)


# ---------------------------------------------------------------------------
# 섹션 1
# ---------------------------------------------------------------------------

def run_section1(inputs: dict, use_cache: bool = True) -> dict:
    t = trend_usp
    product = {"name": inputs["name"], "strengths": inputs["strengths"], "ingredients": inputs["ingredients"],
               "certifications": inputs["certifications"], "price": inputs["price"]}
    profile = t.resolve_country_profile(inputs["country"])
    trends = t.TrendsClient(hl=profile["hl"], use_cache=use_cache)
    warnings = []

    seed_info = t.generate_seed_keywords(product, profile)
    seed_keywords = [s["keyword"] for s in seed_info["seeds"]]
    collected = t.collect_related(trends, seed_info, profile["geo"])
    items = t.preprocess_keywords(collected["records"], seed_keywords + [c["keyword"] for c in seed_info["categories"]])
    data_level = collected["data_level"]
    is_estimated = not items
    if is_estimated:
        data_level = "estimated"
        items = t.estimate_keywords(product, profile, seed_info)
        warnings.append("Google 트렌드에서 연관 검색어를 받지 못해 AI 추정 검색어로 분류했습니다. 수치 배지는 표시하지 않습니다.")
    elif data_level in ("extended", "global"):
        warnings.append(f"연관 검색어가 적어 {t.DATA_LEVEL_LABELS_KO[data_level]} 데이터를 함께 사용했습니다.")

    classification = t.classify_keywords(product, profile, items)
    clusters = classification["clusters"]
    if not is_estimated:
        t.add_probe_keywords(product, profile, clusters, items, profile["geo"])
        warnings += t.attach_trend_metrics(trends, clusters, [], seed_keywords[0], profile["geo"])
    else:
        for c in clusters.values():
            for kw in c["keywords"]:
                kw.update({"yoy_pct": None, "yoy_status": "estimated", "has_volume": None, "vs_anchor": None})
    t.finalize_clusters(clusters)

    return {
        "clusters": [{"key": key, **t.CLUSTER_META[key], **clusters[key]} for key in t.CLUSTER_KEYS],
        "country_ko": profile["name_ko"], "geo": profile["geo"], "languages": profile["languages"],
        "reliability_label_ko": t.RELIABILITY_LABELS_KO[profile["reliability"]],
        "reliability_note_ko": t._reliability_note(profile),
        "data_level_label_ko": t.DATA_LEVEL_LABELS_KO[data_level],
        "seed_keywords": seed_keywords,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 섹션 2
# ---------------------------------------------------------------------------

def run_section2(inputs: dict) -> dict:
    data = _retail().analyze_retail_market(inputs["name"], korean_country(inputs["country"]), inputs["strengths"],
                                           inputs["ingredients"], inputs["price"])
    data = dict(data)
    data.pop("booth_solution", None)   # 부스 컨셉은 섹션 4(OpenAI 단독 기획)만 사용
    return data

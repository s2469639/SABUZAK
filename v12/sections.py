"""섹션 1·2 조립.

섹션 1. 연관 검색어 기반 시장 트렌드 4단계 클러스터링 (trend_usp.py 함수를 "분류·검색량 배지"까지만 조합)
섹션 2. 현지 리테일 벤치마킹 & 경쟁 제품 가격 분석 (retail_research.py)
"""

from country_names import COUNTRY_EN
import retail_research
import trend_usp

TREND_STEPS = 6   # 진행률 표시용 단계 수 (run_section1의 step() 호출 횟수)

KOREAN_BY_EN = {}
for _ko, _en in COUNTRY_EN.items():
    if any("가" <= ch <= "힣" for ch in _ko):
        KOREAN_BY_EN.setdefault(_en.lower(), _ko)


def korean_country(country: str) -> str:
    """리테일 분석은 한국어 국가명(말레이시아 등)으로 통화를 찾으므로, 영문으로 입력해도 한국어로 바꿔 넘긴다."""
    c = (country or "").strip()
    if any("가" <= ch <= "힣" for ch in c):
        return c
    return KOREAN_BY_EN.get(COUNTRY_EN.get(c.lower(), c).lower(), c)


def run_section1(inputs: dict, use_cache: bool = True, progress=None) -> dict:
    t = trend_usp
    step = progress or (lambda label: None)
    product = {"name": inputs["name"], "strengths": inputs["strengths"], "ingredients": inputs["ingredients"],
               "certifications": inputs["certifications"], "price": inputs["price"]}
    step("국가 프로필 확인")
    profile = t.resolve_country_profile(inputs["country"])
    trends = t.TrendsClient(hl=profile["hl"], use_cache=use_cache)
    warnings = []

    step("현지어 시드 검색어 생성")
    seed_info = t.generate_seed_keywords(product, profile)
    seed_keywords = [s["keyword"] for s in seed_info["seeds"]]
    step("Google 트렌드 연관 검색어 수집")
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

    step("검색어 4단계 분류")
    classification = t.classify_keywords(product, profile, items)
    clusters = classification["clusters"]
    step("검색량·전년 대비 증감 측정")
    if not is_estimated:
        t.add_probe_keywords(product, profile, clusters, items, profile["geo"])
        warnings += t.attach_trend_metrics(trends, clusters, [], seed_keywords[0], profile["geo"])
    else:
        for c in clusters.values():
            for kw in c["keywords"]:
                kw.update({"yoy_pct": None, "yoy_status": "estimated", "has_volume": None, "vs_anchor": None})
    step("클러스터 정리")
    t.finalize_clusters(clusters)

    return {
        "clusters": [{"key": key, **t.CLUSTER_META[key], **clusters[key]} for key in t.CLUSTER_KEYS],
        "country_ko": profile["name_ko"], "geo": profile["geo"], "languages": profile["languages"],
        "buyer_language": profile.get("buyer_language") or "English",
        "reliability": profile["reliability"],
        "reliability_label_ko": t.RELIABILITY_LABELS_KO[profile["reliability"]],
        "reliability_note_ko": t._reliability_note(profile),
        "data_level": data_level,
        "data_level_label_ko": t.DATA_LEVEL_LABELS_KO[data_level],
        "seed_keywords": seed_keywords,
        "warnings": warnings,
    }


def run_section2(inputs: dict, progress=None) -> dict:
    return retail_research.analyze_retail_market(inputs["name"], korean_country(inputs["country"]),
                                                 inputs["strengths"], inputs["ingredients"], inputs["price"],
                                                 progress=progress)

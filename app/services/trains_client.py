"""
UNCTAD TRAINS Online(trainsonline.unctad.org) 내부 API 클라이언트.

macmap.org 대신 사용. macmap은 Cloudflare로 완전히 막혀서(403 + JS challenge)
requests로는 접근 불가능해졌다.

2026-09 기준 실제로 확인된 엔드포인트(브라우저 개발자도구 Network 탭 Headers/
Response 탭으로 직접 확인함 - 예전에 이 파일이 쓰던 denormalisedMeasures는
더 이상 사이트가 쓰지 않는 옛날 경로였던 것으로 보임, EXPLORE REGULATIONS 화면):

    POST https://api-trains2.unctad.org/denormalisedRegulations
    Content-Type: application/json
    {
      "imposingCountries": ["DEU"],          # ISO3 코드 그대로! (내부 숫자 ID 아님)
      "internationalStandardsImposing": false,
      "products": ["1905", "190531", ...],   # 실제 HS 코드 문자열 그 자체 (내부 ID 아님!)
      "NTMType": null, "FromDate": null, "ToDate": null,
      "pageNumber": 1, "pageSize": 20,
      "columnsVisibility": {...},
      "exportTo": "excel"
    }
    ("View source"로 확인한 실제 payload에는 allImposingCountries/allProducts/
    productsHsCodes 같은 필드가 없다 - 이런 값들을 같이 보내면 500 에러가 남.)
    -> JSON 배열 응답. 필드명: imposingCountryName, officialTitle,
       officialTitleOriginal, description, descriptionOriginal,
       implementationDate, repealDate, source, originalLanguageCode, symbol,
       publicationSymbol, publicationDate, agencies, documentation, links,
       ntmTypes, hsCodes, affectedProductsDesc.
    응답 헤더에 X-Total-Count로 전체 건수가 옴 (Access-Control-Expose-Headers에
    노출되어 있어 브라우저/requests 양쪽에서 다 읽을 수 있음).

중요: "affectedCountries"(어느 나라에 영향을 주는지, 예: 한국) 같은 필터는
이 API에 아예 없다. 즉 "한국에 영향 주는 규정만" 걸러주는 기능 자체가 없고,
그냥 "이 나라가 부과한 규정"을 조회하는 것 뿐이다. 그래서 예전 코드처럼
전세계를 다 긁어서 국가명으로 걸러낼 필요가 없다 - imposingCountries에
원하는 나라 ISO3 하나만 넣으면 그 나라 것만 바로 온다. 나라별로 직접
조회 가능해지면서, 예전에 있던 "전세계 조회 후 필터링"과 그로 인한 429/
장기 IP 차단 문제가 근본적으로 없어진다.
"""

import json
import time
from pathlib import Path
from urllib.parse import quote

import requests

# 페이지 요청 사이 최소 대기 (매너 호출 - 너무 빨리 연달아 부르면 429 뜸, 심하면
# 장기 IP 차단까지 감)
REQUEST_DELAY_SEC = 2.0
# 429(Too Many Requests) 받았을 때 재시도 대기 시간(초), 점점 늘어남
RETRY_BACKOFF_SEC = [2, 5, 10]
# 서버가 Retry-After 헤더로 이보다 큰 값을 요구해도 이 이상은 기다리지 않는다
# (큰 값을 그대로 따르면 로그 없이 오래 멈춰있는 것처럼 보임)
MAX_RETRY_AFTER_SEC = 15
# Retry-After가 이 값(초)을 넘으면 "잠깐 느린 것"이 아니라 IP가 장기간(보통
# 몇 시간~하루) 차단된 것으로 보고, 재시도하지 말고 바로 명확한 에러로
# 끝낸다. 계속 재시도하면 차단만 더 길어질 수 있음.
LONG_BAN_THRESHOLD_SEC = 300

BASE = "https://api-trains2.unctad.org"
ENDPOINT = f"{BASE}/denormalisedRegulations"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://trainsonline.unctad.org",
    "Referer": "https://trainsonline.unctad.org/",
    "User-Agent": UA,
}

# "Products affected"에 실제로 전송되는 값은 내부 숫자 ID가 아니라 HS코드
# 문자열 리스트 자체 ("products" 키로 그대로 들어감). 우리는 등록된 제품마다
# HS코드가 다르므로 이 상수는 하드코딩된 특정 카테고리가 아니라, hs_code
# 하나를 받아서 후보 코드 목록(원본 그대로 + 4자리 챕터 단위)을 만드는
# 함수로 대체한다 - 챕터 단위도 같이 보내는 이유는 TRAINS 데이터의
# hsCodes 태깅이 느슨해서, 정확히 같은 세부코드보다 넓게(챕터 단위로) 걸어야
# 관련 규정을 놓치지 않기 때문.
DEFAULT_DEBUG_HS_CODES = ["1905", "190531", "190532", "190510", "190520", "190540", "190590"]


def normalize_hs_code(hs_code: str) -> str:
    """등록된 HS코드(예: "1905.90", "19 05 90")에서 숫자만 남긴다."""
    return "".join(ch for ch in (hs_code or "") if ch.isdigit())


def _product_codes_for_query(hs_code: str) -> list:
    """제품의 HS코드로 TRAINS "products" 필터에 넣을 후보 코드 목록을 만든다.
    원본 코드 그대로 + 4자리(챕터) 단위를 같이 보낸다 (챕터 단위까지 넣어야
    TRAINS의 느슨한 품목 태깅에서 관련 규정을 놓치지 않음)."""
    digits = normalize_hs_code(hs_code)
    if not digits:
        return DEFAULT_DEBUG_HS_CODES
    codes = [digits]
    if len(digits) > 4:
        codes.append(digits[:4])
    return codes

COLUMNS_VISIBILITY = {
    "imposingCountryName": True,
    "officialTitle": True,
    "officialTitleOriginal": False,
    "implementationDate": True,
    "repealDate": True,
    "agencies": True,
    "hsCodes": True,
    "affectedProductsDesc": True,
    "links": True,
    "documentation": True,
    "description": True,
    "descriptionOriginal": False,
    "source": False,
    "publicationDate": False,
    "publicationSymbol": False,
    "symbol": False,
    "ntmTypes": True,
}


def _payload(country_iso3: str, product_codes: list, page_number: int, page_size: int) -> dict:
    return {
        "imposingCountries": [country_iso3],
        "internationalStandardsImposing": False,
        "products": product_codes,
        "NTMType": None,
        "FromDate": None,
        "ToDate": None,
        "pageNumber": page_number,
        "pageSize": page_size,
        "columnsVisibility": COLUMNS_VISIBILITY,
        "exportTo": "excel",
    }


# (나라, 제품 HS코드)별 조회 결과 캐시(메모리 + 디스크). 등록된 제품마다
# HS코드가 다르므로 캐시 키도 나라만이 아니라 "나라:HS코드"로 나눈다.
# 박람회 상세페이지에서 여러 제품/나라를 연달아 조회하거나, 디버그 스크립트를
# 여러 번 재실행해도 CACHE_TTL_SEC 안에는 같은 조합을 다시 네트워크로 긁지
# 않는다. 디스크에도 저장하는 이유는 `python debug_trains_ntm.py`처럼 매번
# 새 프로세스로 실행하는 스크립트는 메모리 캐시만으로는 재실행할 때마다
# 초기화된 것과 같기 때문 - 이걸 몰라서 테스트로 반복 실행하다가 실제로
# 장기 IP 차단을 당한 적이 있다.
CACHE_TTL_SEC = 6 * 60 * 60  # 6시간
_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "instance" / "trains_country_cache.json"
_memory_cache: dict = {}  # {"iso3:hs코드": {"rows": [...], "fetched_at": ts}}


def _cache_key(country_iso3: str, hs_code: str) -> str:
    return f"{country_iso3}:{normalize_hs_code(hs_code) or 'DEFAULT'}"


def _load_disk_cache() -> dict:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save_disk_cache(all_cache: dict):
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(all_cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 캐싱 실패해도 기능 자체는 계속 동작해야 하므로 조용히 무시


# EU는 식품 수입 규정을 개별 회원국이 아니라 EU 차원에서 통합 관리해서,
# TRAINS에도 개별 회원국 이름으로는 더미 행만 잡히고 "European Union"으로
# 조회해야 실제 데이터가 나온다 (실제로 확인함 - 네덜란드 개별조회는 더미
# 1건, EU로는 데이터 있음. WTO 관세율 때와 같은 패턴). imposingCountries에
# 실제로 쓰는 코드는 "EUN" (응답의 documentation 파일명이 "EUN_..."로
# 시작하는 걸로 확인함 - TRAINS엔 WTO의 /reporters 같은 코드 조회
# 엔드포인트가 없어서 이렇게 역추적함).
EU_MEMBER_ISO3 = {
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA",
    "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD",
    "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE",
}
EU_TRAINS_CODE = "EUN"


def _fetch_pages(reporter_code: str, product_codes: list, page_size: int, max_pages: int, log_key: str) -> list:
    """실제로 페이지네이션 돌면서 TRAINS를 호출하는 부분. 캐싱은 호출부
    (fetch_regulations_for_country)에서 처리하고, 여기는 순수하게 이
    reporter_code로 데이터를 받아오는 것만 담당한다 (EU 폴백 때 같은
    로직을 재사용하기 위해 분리함)."""
    all_rows = []
    total_count = None
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(REQUEST_DELAY_SEC)

        total_note = f"/{total_count}" if total_count is not None else ""
        print(f"  [TRAINS] {log_key} page {page} 요청 중... (누적 {len(all_rows)}{total_note}건)", flush=True)

        resp = None
        for attempt, backoff in enumerate([0] + RETRY_BACKOFF_SEC):
            if backoff:
                time.sleep(backoff)
            try:
                # timeout=(연결 타임아웃, 응답 타임아웃) - 연결 자체가 막혀서
                # 응답이 아예 안 오는 경우(방화벽 등)에도 10초 안에 실패로
                # 끝나도록 분리.
                resp = requests.post(
                    ENDPOINT,
                    json=_payload(reporter_code, product_codes, page, page_size),
                    headers=HEADERS,
                    timeout=(10, 60),
                )
            except requests.exceptions.RequestException as exc:
                print(f"  [TRAINS] {log_key} page {page} 요청 실패: {exc}", flush=True)
                raise
            print(f"  [TRAINS] {log_key} page {page} 응답: {resp.status_code}", flush=True)
            if resp.status_code != 429:
                break
            # 서버가 Retry-After로 대기시간을 알려주기도 하는데, 이 값을 그대로
            # 믿고 sleep하면 서버가 큰 값(몇십초~그 이상)을 줄 경우 아무 로그도
            # 없이 통째로 멈춰버린 것처럼 보인다. 그래서 상한(MAX_RETRY_AFTER_SEC)을
            # 씌우고, 대기 전에 몇 초 기다리는지 꼭 출력한다.
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    retry_after_sec = float(retry_after)
                except ValueError:
                    retry_after_sec = None
                if retry_after_sec is not None and retry_after_sec > LONG_BAN_THRESHOLD_SEC:
                    raise RuntimeError(
                        f"TRAINS가 이 IP를 장기간 차단한 것으로 보입니다 "
                        f"(Retry-After={retry_after_sec:.0f}초 ≈ {retry_after_sec / 3600:.1f}시간). "
                        f"단순 429 재시도로는 해결 안 되니, 시간이 지나거나 IP를 바꿔서 "
                        f"다시 시도해야 합니다."
                    )
                if retry_after_sec is not None:
                    wait_sec = min(retry_after_sec, MAX_RETRY_AFTER_SEC)
                    print(f"  [TRAINS] {log_key} page {page} 429, Retry-After={retry_after}s -> {wait_sec}s 대기", flush=True)
                    time.sleep(wait_sec)
        resp.raise_for_status()

        if total_count is None:
            header_total = resp.headers.get("X-Total-Count")
            if header_total and header_total.isdigit():
                total_count = int(header_total)

        try:
            batch = resp.json()
        except ValueError as exc:
            preview = resp.text[:300]
            raise ValueError(
                f"TRAINS 응답이 JSON이 아닙니다 (형식이 또 바뀌었을 수 있음). "
                f"응답 앞부분: {preview!r}"
            ) from exc

        if not isinstance(batch, list):
            raise ValueError(f"TRAINS 응답이 예상한 배열 형식이 아닙니다: {type(batch)}")

        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < page_size or (total_count is not None and len(all_rows) >= total_count):
            break

    return all_rows


def fetch_regulations_for_country(
    country_iso3: str, hs_code: str, page_size: int = 20, max_pages: int = 5, force_refresh: bool = False
) -> list:
    """UNCTAD TRAINS에서 country_iso3(예: 'DEU')가 이 제품의 hs_code(마이페이지에
    등록된 실제 HS코드, 예: "1905.90")에 대해 부과 중인 규정을 직접 조회한다
    (해당 국가만 콕 집어서 조회 - 전세계를 다 긁을 필요 없음).

    EU 회원국은 개별 국가로 조회하면 더미 행만 나오는 경우가 많아, 그럴 때
    EU 코드(EUN)로 한 번 더 시도한다 (위 EU_MEMBER_ISO3 참고).

    최종적으로 쓰는 건 top_relevant_regulations()로 추린 상위 6건뿐이지만,
    관련도 필터링이 고를 수 있는 후보가 너무 적으면 걸러낼 게 없어서
    무관한 것까지 올라올 수 있다. max_pages 기본값 5(최대 100건)면 후보가
    더 넉넉해서 필터링이 더 잘 추릴 수 있다 (3->5로 올려도 딜레이 몇 초
    늘어나는 정도라 부담 적음).

    페이지마다 REQUEST_DELAY_SEC만큼 쉬고, 429를 받으면 잠깐 대기 후
    재시도한다. Retry-After가 비정상적으로 크면(장기 IP 차단) 재시도 없이
    바로 에러로 끝낸다."""
    now = time.time()
    cache_key = _cache_key(country_iso3, hs_code)
    product_codes = _product_codes_for_query(hs_code)

    if not force_refresh:
        cached = _memory_cache.get(cache_key)
        if cached and (now - cached["fetched_at"]) < CACHE_TTL_SEC:
            return cached["rows"]

        disk_cache = _load_disk_cache()
        entry = disk_cache.get(cache_key)
        if entry and (now - entry.get("fetched_at", 0.0)) < CACHE_TTL_SEC:
            print(
                f"  [TRAINS] {cache_key} 디스크 캐시 사용 "
                f"(마지막 수집: {now - entry['fetched_at']:.0f}초 전, {len(entry['rows'])}건)",
                flush=True,
            )
            _memory_cache[cache_key] = entry
            return entry["rows"]

    all_rows = _fetch_pages(country_iso3, product_codes, page_size, max_pages, cache_key)

    real_rows = [r for r in all_rows if not _is_placeholder_row(r)]
    if not real_rows and country_iso3 in EU_MEMBER_ISO3:
        eu_log_key = f"{cache_key}(EU 폴백)"
        print(f"  [TRAINS] {cache_key} 개별 조회에 실데이터 없음 -> EU 코드로 재시도", flush=True)
        eu_rows = _fetch_pages(EU_TRAINS_CODE, product_codes, page_size, max_pages, eu_log_key)
        if any(not _is_placeholder_row(r) for r in eu_rows):
            all_rows = eu_rows

    now = time.time()
    _memory_cache[cache_key] = {"rows": all_rows, "fetched_at": now}
    disk_cache = _load_disk_cache()
    disk_cache[cache_key] = {"rows": all_rows, "fetched_at": now}
    _save_disk_cache(disk_cache)
    return all_rows


# 식품/농산물 전반에 관련 있을 법한 규정 점수용 키워드 (관련 있다고 이미
# 판정된 것들 사이에서 순위만 매길 때 씀 - 아래 _PRODUCT_SPECIFIC_KEYWORDS와
# 달리 이것만으로는 "관련 있다"고 판정하지 않음. "food"/"import" 같은 너무
# 넓은 단어라 이것만 기준으로 삼으면 아프리카돼지열병, 수산물 수입중단 같은
# 완전히 무관한 규정까지 다 상위로 올라옴)
_FOOD_RELEVANCE_KEYWORDS = [
    "food", "animal", "plant", "fish", "meat", "agricultur", "consumer",
    "biological", "sanitary", "phytosanitary", "veterinary", "poultry",
    "livestock", "seafood", "beverage", "packaging", "labell", "labeling",
    "import", "export", "custom",
]

# 위 목록 중 "food"/"animal"/"plant"류처럼 실제로 식품·농산물임을 강하게
# 시사하는 키워드만 추림. "import"/"export"/"custom"/"consumer"/"packaging"/
# "labell(ing)"은 화장품·의류 등 다른 품목 규정에도 흔해서 이것만으로는
# 통과시키지 않는다 (hsCodes가 없는 규정을 거를 때 이 강한 키워드가 최소
# 하나는 있어야 관련 있다고 본다).
_STRONG_FOOD_KEYWORDS = [
    "food", "animal", "plant", "fish", "meat", "agricultur", "biological",
    "sanitary", "phytosanitary", "veterinary", "poultry", "livestock",
    "seafood", "beverage",
]


def _has_strong_food_signal(reg: dict) -> bool:
    text = " ".join([reg.get("officialTitle") or "", reg.get("description") or ""]).lower()
    return any(kw in text for kw in _STRONG_FOOD_KEYWORDS)


def _hs_code_overlaps_product(hs_codes_field, product_codes: list) -> bool:
    """응답의 hsCodes 필드가 조회에 쓴 product_codes(등록된 제품의 실제
    HS코드 기준)와 겹치는지 확인."""
    if not hs_codes_field:
        return False
    text = str(hs_codes_field)
    return any(code in text for code in product_codes)


def _is_placeholder_row(reg: dict) -> bool:
    """TRAINS는 해당 조합의 실제 데이터가 없을 때 빈 배열 대신 title/
    description이 "-"인 더미 1행을 돌려주는 경우가 있다 (실제로 확인함 -
    품목 필터 없이 검색했을 때, 그리고 데이터가 아예 없는 국가+품목 조합에서
    똑같이 나왔음). 이런 행은 처음부터 걸러낸다."""
    title = (reg.get("officialTitle") or "").strip()
    desc = (reg.get("description") or "").strip()
    return title in ("", "-") and desc in ("", "-")


def is_product_relevant(reg: dict, product_codes: list) -> bool:
    """이 규정이 이 제품(product_codes)과 관련 있어 보이는지 판단.
    hsCodes가 있는데 우리 코드와 안 겹치면 다른 품목 규정이라고 보고 제외한다.
    hsCodes가 없는 규정(TRAINS 원본 데이터 대부분이 그렇다 - 중국 등 국가별
    관세청 공지는 특정 HS코드 없이 국가 전체 공지로만 등록된 경우가 많음)은
    특정 품목까지는 구분할 수 없으므로, 최소한 식품/농산물과 관련은 있어야
    한다는 느슨한 기준(_has_strong_food_signal)만 적용한다. 즉 hsCodes가 없는
    쪽은 "이 품목 전용"이 아니라 "그 나라의 식품·농산물 수입 규정 중 참고할
    만한 것" 정도의 느슨한 관련도이니, 화면에도 그렇게 표시해야 한다."""
    if _is_placeholder_row(reg):
        return False
    if _hs_code_overlaps_product(reg.get("hsCodes"), product_codes):
        return True
    if reg.get("hsCodes"):
        return False
    return _has_strong_food_signal(reg)


def _relevance_score(reg: dict) -> int:
    text = " ".join([
        reg.get("officialTitle") or "",
        reg.get("description") or "",
    ]).lower()
    return sum(1 for kw in _FOOD_RELEVANCE_KEYWORDS if kw in text)


def _llm_filter_relevant(product_name: str, candidates: list) -> list:
    """hsCodes가 없어서 키워드로만 느슨하게 통과된 후보들을, LLM한테 제품명을
    주고 진짜 관련 있는 것만 골라달라고 한다 (예: "비건만두"인데 "축산물 수출
    라이선스"가 걸러지지 않는 문제 - "sanitary"/"livestock" 같은 키워드만으로는
    이런 걸 구분 못 함). 건별로 부르면 비용/시간이 커지니 목록 하나를 통째로
    주고 관련 있는 번호만 답하게 한다. OpenAI 키가 없거나 호출 실패하면
    후보 목록을 그대로 돌려줘서(필터링 전 상태) 기능이 안 죽게 한다."""
    if not candidates:
        return candidates
    try:
        import re

        from app.services.openai_client import get_client

        listing = "\n".join(
            f"{i}. {reg.get('officialTitle') or ''} - {(reg.get('description') or '')[:200]}"
            for i, reg in enumerate(candidates)
        )
        prompt = (
            f"다음은 어떤 나라의 수입 규제 공지 목록입니다. 이 중에서 한국 식품 "
            f"'{product_name}' 수출과 실질적으로 관련 있는 항목의 번호만 콤마로 "
            f"구분해서 답하세요 (예: 0,2,5). 두 가지 경우를 관련 있다고 판단하세요: "
            f"(1) 특정 원재료/품목을 콕 집었는데 그게 '{product_name}'와 일치하는 경우, "
            f"(2) 특정 품목을 콕 집지 않고 수입식품 전반에 공통 적용되는 규정(예: 수입식품 "
            f"공통 부과금/통관 절차/표시 규정 등)인 경우. 반대로 축산물/수산물/화장품/의약품처럼 "
            f"'{product_name}'와 원재료·품목이 명백히 다른 것을 콕 집은 규정만 관련 없다고 "
            f"판단하세요. 관련 있는 게 하나도 없으면 빈 문자열만 출력하세요. 다른 설명 없이 "
            f"번호만 출력하세요.\n\n{listing}"
        )
        response = get_client().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (response.choices[0].message.content or "").strip()
        indices = {int(x) for x in re.findall(r"\d+", text)}
        return [reg for i, reg in enumerate(candidates) if i in indices]
    except Exception:
        return candidates


def top_relevant_regulations(regulations: list, hs_code: str, product_name: str = None, limit: int = 6) -> list:
    """이 제품(hs_code)과 실제로 관련 있는 것만 남기고, 그중에서 식품/농산물
    관련도가 높은 순으로 상위 N개만 남긴다 (전체를 다 저장하면 화면도
    지저분해지고 AI 요약 비용도 커지므로, 정말 중요한 것만 추림).

    hsCodes가 응답에 있어서 우리 제품 코드와 실제로 겹치는 건("확실한 매치")
    무조건 남긴다. hsCodes가 없어서 키워드(_has_strong_food_signal)로만
    느슨하게 통과된 건("애매한 매치")은, product_name이 주어지면 LLM에게
    한 번 더 검증시켜서(_llm_filter_relevant) 진짜 무관한 걸 걸러낸다 -
    이게 없으면 "비건만두"인데 "돼지열병"/"축산물 수출 라이선스" 같은 게
    "sanitary"/"livestock" 키워드만으로 끼어드는 걸 못 막는다."""
    product_codes = _product_codes_for_query(hs_code)

    confirmed = []
    soft = []
    for reg in regulations:
        if _is_placeholder_row(reg):
            continue
        if _hs_code_overlaps_product(reg.get("hsCodes"), product_codes):
            confirmed.append(reg)
        elif not reg.get("hsCodes") and _has_strong_food_signal(reg):
            soft.append(reg)

    soft.sort(key=_relevance_score, reverse=True)
    # LLM에 통째로 넘기는 비용을 아끼려고, 어차피 최종 limit보다 훨씬 넉넉한
    # 상위 후보만 검증시킨다 (넘치게 있어봤자 어차피 순위 밖이라 의미 없음).
    soft_candidates = soft[: max(limit * 3, 15)]
    if product_name and soft_candidates:
        soft_candidates = _llm_filter_relevant(product_name, soft_candidates)

    combined = confirmed + soft_candidates
    combined.sort(key=_relevance_score, reverse=True)
    return combined[:limit]


def summarize_regulation_ko(title: str, description: str) -> str:
    """영문 규정 제목/설명을 한국 식품 수출 담당자가 바로 이해할 수 있게
    한국어 1~2문장으로 요약. OpenAI 키가 없거나 호출이 실패하면 원문을
    그냥 짧게 잘라서 대체한다 (기능이 완전히 멈추지 않도록)."""
    try:
        from app.services.openai_client import get_client

        prompt = (
            "다음은 어떤 나라가 수입 식품에 대해 시행 중인 법령/비관세조치(NTM) 설명입니다. "
            "한국 식품 수출업체 담당자가 실무에서 바로 참고할 수 있도록, "
            "핵심만 한국어 1~2문장으로 요약하세요. 다른 설명 없이 요약 문장만 출력하세요.\n\n"
            f"제목: {title or '(제목 없음)'}\n"
            f"설명: {(description or '')[:2000]}"
        )
        response = get_client().chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = (response.choices[0].message.content or "").strip()
        if summary:
            return summary
    except Exception:
        pass

    # 폴백: 원문 앞부분만 잘라서라도 보여준다 (AI 요약 실패해도 완전히 비진 않게)
    fallback = (description or title or "").strip()
    return (fallback[:200] + "…") if len(fallback) > 200 else fallback


def to_ntm_measure_rows(country_iso3: str, product_key: str, regulations: list, summarize: bool = True) -> list:
    """denormalisedRegulations 응답 dict 리스트 -> NtmMeasure(**row)에 바로 넣을 dict 리스트.
    summarize=True면 각 항목을 한국어 1~2문장으로 요약해서 저장한다 (호출부에서
    이미 top_relevant_regulations로 최대 6개까지 추린 뒤에 넘기는 걸 권장 -
    그래야 AI 요약 호출 횟수도 6번으로 제한됨)."""
    rows = []
    for reg in regulations:
        title = reg.get("officialTitle") or ""
        description = reg.get("description") or ""
        summary_ko = summarize_regulation_ko(title, description) if summarize else description

        # documentation은 파일명만 옴(예: "CHN_..._1.pdf"). links가 있으면 그걸
        # 우선 쓰고, 없으면 예전에 쓰던 get-regulation-file 경로로 추정해서
        # 만든다 (이 경로가 새 API에서도 유효한지는 아직 미확인 - 안 열리면
        # documentation 필드를 다른 방식으로 다뤄야 함).
        web_link = reg.get("links") or ""
        if not web_link:
            documentation = reg.get("documentation")
            if documentation:
                web_link = f"{BASE}/get-regulation-file?filename={quote(documentation)}"

        rows.append({
            "reporter": country_iso3,
            "partner": "KOR",
            "product": product_key,
            "measure_code": reg.get("hsCodes") or "",
            "measure_section": reg.get("ntmTypes") or "",
            "measure_title": title,
            "measure_summary": summary_ko,
            "legislation_title": title,
            "legislation_summary": summary_ko,
            "implementation_authority": reg.get("agencies") or "",
            "start_date": reg.get("implementationDate") or "",
            "end_date": reg.get("repealDate") or "",
            "web_link": web_link,
            "data_source": "UNCTAD TRAINS",
        })
    return rows


# NtmMeasure 테이블에 이 (국가, 품목) 조합으로 저장된 행이 하나도 없으면
# "아직 한 번도 조회 안 함"인지 "조회는 했는데 관련 규정이 진짜 0건"인지
# 구분이 안 된다. 후자일 때는 이 마커 하나짜리 행을 대신 저장해서 구분한다
# (app/services/hscode.py의 get_country_regulations가 이 마커를 인식해서
# 빈 리스트로 처리 - 정적 예시 데이터로 폴백하지 않고 "규정 없음"을 그대로 보여줌).
NO_MATCH_MARKER = "__NTM_NO_MATCH__"


def no_match_row(country_iso3: str, product_key: str) -> dict:
    """조회는 했지만 관련 규정이 하나도 없을 때 저장할 마커 행."""
    return {
        "reporter": country_iso3,
        "partner": "KOR",
        "product": product_key,
        "measure_code": "",
        "measure_section": "",
        "measure_title": NO_MATCH_MARKER,
        "measure_summary": "",
        "legislation_title": NO_MATCH_MARKER,
        "legislation_summary": "",
        "implementation_authority": "",
        "start_date": "",
        "end_date": "",
        "web_link": "",
        "data_source": "UNCTAD TRAINS",
    }

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

# "Products affected"에서 "Crispbread, Gingerbread..."(HS 1905 계열 - 약과/
# 유과 등 사부작 제품군과 일치) 카테고리를 선택했을 때 실제로 전송된 값.
# "View source"로 확인한 실제 payload에는 내부 숫자 ID가 아니라 이 HS코드
# 문자열 리스트 자체가 "products" 키로 그대로 들어간다.
SNACK_HS_CODES = ["1905", "190531", "190532", "190510", "190520", "190540", "190590"]

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


def _payload(country_iso3: str, page_number: int, page_size: int) -> dict:
    return {
        "imposingCountries": [country_iso3],
        "internationalStandardsImposing": False,
        "products": SNACK_HS_CODES,
        "NTMType": None,
        "FromDate": None,
        "ToDate": None,
        "pageNumber": page_number,
        "pageSize": page_size,
        "columnsVisibility": COLUMNS_VISIBILITY,
        "exportTo": "excel",
    }


# 나라별 조회 결과 캐시(메모리 + 디스크). 박람회 상세페이지에서 여러 나라를
# 연달아 조회하거나, 디버그 스크립트를 여러 번 재실행해도 CACHE_TTL_SEC
# 안에는 같은 나라를 다시 네트워크로 긁지 않는다. 디스크에도 저장하는 이유는
# `python debug_trains_ntm.py`처럼 매번 새 프로세스로 실행하는 스크립트는
# 메모리 캐시만으로는 재실행할 때마다 초기화된 것과 같기 때문 - 이걸 몰라서
# 테스트로 반복 실행하다가 실제로 장기 IP 차단을 당한 적이 있다.
CACHE_TTL_SEC = 6 * 60 * 60  # 6시간
_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "instance" / "trains_country_cache.json"
_memory_cache: dict = {}  # {iso3: {"rows": [...], "fetched_at": ts}}


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


def fetch_regulations_for_country(
    country_iso3: str, page_size: int = 20, max_pages: int = 2, force_refresh: bool = False
) -> list:
    """UNCTAD TRAINS에서 country_iso3(예: 'DEU')가 사부작 제품군(HS 1905류)에
    대해 부과 중인 규정을 직접 조회한다 (해당 국가만 콕 집어서 조회 - 예전처럼
    전세계를 다 긁을 필요 없음).

    최종적으로 쓰는 건 top_relevant_regulations()로 추린 상위 6건뿐이라,
    끝까지 다 받을 필요가 없다. max_pages 기본값을 2(최대 40건)로 낮춰서
    요청 자체를 적게 보낸다 - 그래도 6건 추리기엔 충분하고, 429/차단 위험도
    그만큼 줄어든다. 정말 다 필요하면 max_pages를 늘려서 호출하면 된다.

    페이지마다 REQUEST_DELAY_SEC만큼 쉬고, 429를 받으면 잠깐 대기 후
    재시도한다. Retry-After가 비정상적으로 크면(장기 IP 차단) 재시도 없이
    바로 에러로 끝낸다."""
    now = time.time()

    if not force_refresh:
        cached = _memory_cache.get(country_iso3)
        if cached and (now - cached["fetched_at"]) < CACHE_TTL_SEC:
            return cached["rows"]

        disk_cache = _load_disk_cache()
        entry = disk_cache.get(country_iso3)
        if entry and (now - entry.get("fetched_at", 0.0)) < CACHE_TTL_SEC:
            print(
                f"  [TRAINS] {country_iso3} 디스크 캐시 사용 "
                f"(마지막 수집: {now - entry['fetched_at']:.0f}초 전, {len(entry['rows'])}건)",
                flush=True,
            )
            _memory_cache[country_iso3] = entry
            return entry["rows"]

    all_rows = []
    total_count = None
    for page in range(1, max_pages + 1):
        if page > 1:
            time.sleep(REQUEST_DELAY_SEC)

        total_note = f"/{total_count}" if total_count is not None else ""
        print(f"  [TRAINS] {country_iso3} page {page} 요청 중... (누적 {len(all_rows)}{total_note}건)", flush=True)

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
                    json=_payload(country_iso3, page, page_size),
                    headers=HEADERS,
                    timeout=(10, 60),
                )
            except requests.exceptions.RequestException as exc:
                print(f"  [TRAINS] {country_iso3} page {page} 요청 실패: {exc}", flush=True)
                raise
            print(f"  [TRAINS] {country_iso3} page {page} 응답: {resp.status_code}", flush=True)
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
                    print(f"  [TRAINS] {country_iso3} page {page} 429, Retry-After={retry_after}s -> {wait_sec}s 대기", flush=True)
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

    now = time.time()
    _memory_cache[country_iso3] = {"rows": all_rows, "fetched_at": now}
    disk_cache = _load_disk_cache()
    disk_cache[country_iso3] = {"rows": all_rows, "fetched_at": now}
    _save_disk_cache(disk_cache)
    return all_rows


# 식품/농산물 수출과 관련 있을 법한 규정을 상위로 올리는 키워드
# (app/services/hscode.py의 _FOOD_RELEVANCE_KEYWORDS와 같은 기준)
_FOOD_RELEVANCE_KEYWORDS = [
    "food", "animal", "plant", "fish", "meat", "agricultur", "consumer",
    "biological", "sanitary", "phytosanitary", "veterinary", "poultry",
    "livestock", "seafood", "beverage", "packaging", "labell", "labeling",
    "import", "export", "custom",
]


def _relevance_score(reg: dict) -> int:
    text = " ".join([
        reg.get("officialTitle") or "",
        reg.get("description") or "",
    ]).lower()
    return sum(1 for kw in _FOOD_RELEVANCE_KEYWORDS if kw in text)


def top_relevant_regulations(regulations: list, limit: int = 6) -> list:
    """식품/농산물 관련도가 높은 순으로 상위 N개만 남긴다 (전체를 다 저장하면
    화면도 지저분해지고 AI 요약 비용도 커지므로, 정말 중요한 것만 추림)."""
    return sorted(regulations, key=_relevance_score, reverse=True)[:limit]


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

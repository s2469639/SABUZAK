"""
macmap.org 프록시 서버 (Flask) - CORS 우회용

브라우저 -> 이 서버 -> macmap.org 순으로 요청을 대신 넘겨준다.
서버(파이썬)가 macmap을 호출하는 거라 브라우저의 CORS 제약을 받지 않는다.

설치:
    pip install flask flask-cors requests

실행:
    python proxy_server.py
    (기본 포트 5000, http://localhost:5000 에서 대기)

프론트엔드(export_check_test.html)에서는
    https://www.macmap.org/api/results/... 대신
    http://localhost:5000/api/tariff?importer=..&product=..
    http://localhost:5000/api/ntm?importer=..&product=..
로 호출하도록 바꾸면 됨.
"""

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False  # 유니코드 이스케이프 없이 그대로 UTF-8로 응답
CORS(app)  # 프론트엔드 다른 origin에서 호출 허용 (필요시 origins=["http://내프론트주소"]로 제한)

APP_DIR = Path(__file__).parent


@app.route("/")
def index():
    # export_check_test.html이 이 파일과 같은 폴더에 있어야 함
    return send_from_directory(APP_DIR, "export_check_test.html")

BASE = "https://www.macmap.org"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
EXPORTER_DEFAULT = "410"  # 대한민국 고정

_session = None


def get_macmap_session() -> requests.Session:
    """세션 쿠키를 한 번만 발급받아 재사용 (매 요청마다 새로 받을 필요 없음)."""
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        s.get(f"{BASE}/en/query/results", timeout=15)
        _session = s
    return _session


def call_macmap(endpoint: str, reporter: str, partner: str, product: str):
    session = get_macmap_session()
    url = f"{BASE}/api/results/{endpoint}"
    params = {"reporter": reporter, "partner": partner, "product": product}
    referer = f"{BASE}/en/query/results?reporter={reporter}&partner={partner}&product={product}&level=6"
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    resp = session.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"  # requests가 인코딩을 잘못 추측해서 특수문자가 깨지는 것 방지
    return resp.json()


# 식품 수출과 무관한 항목을 걸러내기 위한 키워드 블록리스트.
# UNCTAD 원본 데이터 자체에 가끔 엉뚱한 카테고리(가전제품, 에너지기기 등)가
# 섞여 태깅되는 경우가 있어(예: 식품 A220 밑에 "Television sets" 규정이 들어간 사례),
# 법령 제목/요약에 이런 키워드가 있으면 화면에서 제외한다.
IRRELEVANT_KEYWORDS = [
    "television", "energy star", "vehicle", "automobile", "textile",
    "apparel", "footwear", "electronics", "battery", "firearm",
    "tobacco product", "motor fuel", "aircraft",
]


def is_relevant_measure(measure: dict) -> bool:
    text = " ".join([
        str(measure.get("LegislationTitle", "") or ""),
        str(measure.get("LegislationSummary", "") or ""),
        str(measure.get("Title", "") or ""),
        str(measure.get("Summary", "") or ""),
    ]).lower()
    return not any(kw in text for kw in IRRELEVANT_KEYWORDS)


def filter_ntm_response(data: list) -> list:
    """각 그룹의 AllMeasures(+Measures 카운트)에서 무관 항목을 제거한다."""
    for group in data:
        original = group.get("AllMeasures", [])
        filtered = [m for m in original if is_relevant_measure(m)]
        removed = len(original) - len(filtered)
        group["AllMeasures"] = filtered
        if removed:
            group["FilteredOutCount"] = removed
    return data


TEXT_FIELDS = ("Title", "Summary", "LegislationTitle", "LegislationSummary", "Comment")


def clean_mojibake(text):
    """원본 소스(UNCTAD 스크래핑 데이터) 자체가 깨진 문자를 담고 있는 경우가 있어
    후처리로 최대한 복구한다. \\ufffd(깨진 문자, 브라우저에는 물음표/네모로 보임)는
    미국 법령 원문(CFR 등)에서 거의 항상 섹션 기호(§) 자리라 그걸로 치환한다.
    """
    if not isinstance(text, str):
        return text
    return text.replace("�", "§")


def clean_measure_text(measure: dict) -> dict:
    for field in TEXT_FIELDS:
        if field in measure:
            measure[field] = clean_mojibake(measure[field])
    return measure


def clean_ntm_response(data: list) -> list:
    for group in data:
        for m in group.get("AllMeasures", []):
            clean_measure_text(m)
        for m in group.get("Measures", []):
            clean_measure_text(m)
    return data


def resolve_ntlc_codes(country_code: str, hs6: str) -> list[str]:
    """국가별 실제 세관코드(NTLC)를 HS 6자리 기준으로 조회한다.

    macmap은 국가마다 6자리 이후 세부 관세코드 체계가 달라서, ntm-measures/
    customduties를 부르기 전에 이 변환 단계가 필요하다. 응답의 정확한 키 이름은
    아직 미확인이라 흔한 이름들을 넓게 시도한다.
    """
    session = get_macmap_session()
    url = f"{BASE}/api/v2/ntlc-products"
    params = {"countryCode": country_code, "level": 8, "code": hs6}
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/en/query/results?reporter={country_code}&product={hs6}&level=6",
    }
    resp = session.get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    data = resp.json()

    items = data if isinstance(data, list) else data.get("list", data.get("Products", []))
    codes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("Code", "NTLCCode", "ProductCode", "code"):
            if item.get(key):
                codes.append(str(item[key]))
                break
    return codes or [hs6]  # 변환 실패 시 원래 코드로 폴백


def resolve_product_code(importer: str, product: str) -> str:
    """product가 6자리면 해당 importer 기준 실제 세관코드로 변환, 이미 8자리 이상이면 그대로 사용."""
    if len(product) <= 6:
        codes = resolve_ntlc_codes(importer, product)
        return codes[0] if codes else product
    return product


def fallback_codes(importer: str, product: str) -> list[str]:
    """6/7/8/9/10자리 어떤 걸 입력해도 시도할 후보 코드 목록을 만든다.

    1순위: 입력값 그대로 (8자리 등 이미 국가 고유 코드일 가능성)
    2순위: 앞 6자리(HS 국제표준) 기준으로 그 나라 실제 세관코드 재변환
    """
    candidates = [product]
    hs6 = product[:6]
    try:
        resolved = resolve_ntlc_codes(importer, hs6)
    except Exception:
        resolved = []
    for code in resolved:
        if code not in candidates:
            candidates.append(code)
    return candidates


def call_with_fallback(endpoint: str, importer: str, exporter: str, product: str):
    """후보 코드들을 순서대로 시도해서 데이터가 있는 첫 결과를 반환한다."""
    last_result = None
    for code in fallback_codes(importer, product):
        data = call_macmap(endpoint, importer, exporter, code)
        last_result = data
        has_data = bool(data.get("CustomDuty")) if isinstance(data, dict) else bool(data)
        if has_data:
            return data
    return last_result


@app.route("/api/tariff")
def api_tariff():
    importer = request.args.get("importer")
    product = request.args.get("product")
    exporter = request.args.get("exporter", EXPORTER_DEFAULT)
    if not importer or not product:
        return jsonify({"error": "importer, product 파라미터 필요"}), 400
    try:
        data = call_with_fallback("customduties", importer, exporter, product)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/ntm")
def api_ntm():
    importer = request.args.get("importer")
    product = request.args.get("product")
    exporter = request.args.get("exporter", EXPORTER_DEFAULT)
    if not importer or not product:
        return jsonify({"error": "importer, product 파라미터 필요"}), 400
    try:
        data = call_with_fallback("ntm-measures", importer, exporter, product)
        data = filter_ntm_response(data)
        data = clean_ntm_response(data)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/debug/resolve")
def api_debug_resolve():
    """product 6자리가 실제로 어떤 국가별 코드로 변환되는지 확인용 디버그 엔드포인트."""
    importer = request.args.get("importer")
    product = request.args.get("product")
    if not importer or not product:
        return jsonify({"error": "importer, product 파라미터 필요"}), 400
    try:
        codes = resolve_ntlc_codes(importer, product)
        return jsonify({"input_hs6": product, "importer": importer, "resolved_codes": codes})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

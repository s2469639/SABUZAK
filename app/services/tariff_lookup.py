"""
관세율 조회 - 농림축산식품부 "농축산물 FTA 협정세율 현황" 실데이터 기반.

출처: 공공데이터포털(data.go.kr) "농림축산식품부_농축산물 FTA 협정세율 현황"을
사용자가 한글(HWP) 원본에서 직접 표를 복사해 CSV로 만들어 제공한 파일.
scripts/market/농축산물_FTA_협정세율_2026.csv 에 원본 그대로(가공 없이) 저장해뒀다.

이 파일이 들어오기 전까지 app/services/hscode.py는 나라별로 사람이 손으로
추정한 고정 관세율표(TARIFF_PROFILES)를 썼는데, 그중 상당수가 실제로 체결된
적 없는 협정을 있는 것처럼 보여주는 오류가 있었다. 이 모듈은 그 자리를
대체해서, HS코드 + 국가 조합으로 실제 표에 있는 값을 찾아 보여준다.

주의:
- 표에 없는 국가(예: 브라질, 멕시코, 사우디)는 그냥 "정보 없음"으로 표시한다.
  없는 협정을 지어내지 않는다.
- "미양허"(WTO 양허하지 않음 - 협정상 상한이 없다는 뜻이지 0%라는 뜻이
  아님)는 숫자로 표시하지 않고 그대로 "미양허"라고 보여준다.
- TRQ(관세율할당), ASG(특별긴급관세), 원화 단위 복합세율처럼 단순 %로
  못 나타내는 값은 원문 그대로 보여주고, "최적 관세" 자동 추천 대상에서는
  제외한다(잘못된 숫자 비교를 피하기 위해).
- HS코드를 세부코드(10자리)까지 정확히 입력하지 않고 상위 6~4자리만 입력한
  경우, 그 아래 여러 세부 품목의 세율이 다를 수 있어 범위(예: "0~5%")로
  보여준다.
"""

import csv
import os
import re
from datetime import date
from functools import lru_cache

_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "market", "농축산물_FTA_협정세율_2026.csv"
)

# 국가별 관세청 관세율표에서 뽑은 MFN(최혜국/기본) 관세율 - scripts/market/
# build_mfn_rates.py 로 생성. 위 FTA CSV는 협정세율만 있고 MFN 기준값이
# 없어서, "협정 미체결시 원래 얼마인지" 비교 기준으로 별도로 둔다.
_MFN_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "market", "mfn_base_rates.csv"
)

_EU_MEMBERS = {
    "DEU", "FRA", "ITA", "ESP", "NLD", "BEL", "AUT", "PRT", "GRC", "SWE",
    "DNK", "FIN", "POL", "CZE", "IRL", "HUN", "ROU", "BGR", "HRV", "SVK",
    "SVN", "LTU", "LVA", "EST", "CYP", "MLT", "LUX",
}

# CSV 컬럼 순서(0-indexed, 번호/HSK/한글품명/영문품명 다음부터).
# 표 헤더 텍스트가 줄바꿈 때문에 공백이 들쭉날쭉해서 이름 매칭 대신 위치로 잡는다.
_COL_CHL = 4
_COL_SGP = 5
_COL_EFTA = 6
_COL_ASEAN = 7
_COL_IND = 8
_COL_EU_PERIOD1 = 9  # EU (25.7.1~26.6.30)
_COL_EU_PERIOD2 = 10  # EU (26.7.1~27.6.30)
_COL_PER = 11
_COL_USA = 12
_COL_COL = 13
_COL_TUR = 14
_COL_CAN = 15
_COL_AUS = 16
_COL_VNM = 17
_COL_CHN = 18
_COL_NZL = 19
_COL_CRI = 20
_COL_SLV = 21
_COL_HND = 22
_COL_NIC = 23
_COL_PAN = 24
_COL_GBR_PERIOD1 = 25
_COL_GBR_PERIOD2 = 26
_COL_IDN = 27
_COL_ISR = 28
_COL_KHM = 29
_COL_RCEP_NZL = 30
_COL_RCEP_ASEAN = 31
_COL_RCEP_JPN = 32
_COL_RCEP_CHN = 33
_COL_RCEP_AUS = 34
_COL_PHL = 35
_COL_ARE = 36


def _eu_col():
    today = date.today()
    return _COL_EU_PERIOD1 if today < date(2026, 7, 1) else _COL_EU_PERIOD2


def _gbr_col():
    today = date.today()
    return _COL_GBR_PERIOD1 if today < date(2026, 7, 1) else _COL_GBR_PERIOD2


# 국가(ISO3) -> 이 표에서 적용 가능한 (컬럼 인덱스, 협정 이름) 목록.
# 여러 개면 그중 최저 관세를 추천한다 (예: 호주는 한-호주FTA와 RCEP 둘 다 있음).
# 표에 아예 없는 국가(BRA, MEX, SAU 등)는 여기 없으면 자동으로 "정보 없음" 처리.
def _country_columns(country_iso3: str):
    mapping = {
        "CHL": [(_COL_CHL, "한-칠레 FTA")],
        "SGP": [(_COL_SGP, "한-싱가포르 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "CHE": [(_COL_EFTA, "한-EFTA FTA")],
        "NOR": [(_COL_EFTA, "한-EFTA FTA")],
        "ISL": [(_COL_EFTA, "한-EFTA FTA")],
        "LIE": [(_COL_EFTA, "한-EFTA FTA")],
        "THA": [(_COL_ASEAN, "한-아세안 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "MYS": [(_COL_ASEAN, "한-아세안 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "LAO": [(_COL_ASEAN, "한-아세안 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "MMR": [(_COL_ASEAN, "한-아세안 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "BRN": [(_COL_ASEAN, "한-아세안 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "IND": [(_COL_IND, "한-인도 CEPA")],
        "PER": [(_COL_PER, "한-페루 FTA")],
        "USA": [(_COL_USA, "한-미 FTA (KORUS)")],
        "COL": [(_COL_COL, "한-콜롬비아 FTA")],
        "TUR": [(_COL_TUR, "한-튀르키예 FTA")],
        "CAN": [(_COL_CAN, "한-캐나다 FTA")],
        "AUS": [(_COL_AUS, "한-호주 FTA"), (_COL_RCEP_AUS, "RCEP (호주)")],
        "VNM": [(_COL_VNM, "한-베트남 FTA"), (_COL_RCEP_ASEAN, "RCEP (아세안)")],
        "CHN": [(_COL_CHN, "한-중 FTA"), (_COL_RCEP_CHN, "RCEP (중국)")],
        "NZL": [(_COL_NZL, "한-뉴질랜드 FTA"), (_COL_RCEP_NZL, "RCEP (뉴질랜드)")],
        "CRI": [(_COL_CRI, "한-중미 FTA (코스타리카)")],
        "SLV": [(_COL_SLV, "한-중미 FTA (엘살바도르)")],
        "HND": [(_COL_HND, "한-중미 FTA (온두라스)")],
        "NIC": [(_COL_NIC, "한-중미 FTA (니카라과)")],
        "PAN": [(_COL_PAN, "한-중미 FTA (파나마)")],
        "GBR": [(_gbr_col(), "한-영 FTA")],
        "IDN": [(_COL_IDN, "한-인도네시아 CEPA")],
        "ISR": [(_COL_ISR, "한-이스라엘 FTA")],
        "KHM": [(_COL_KHM, "한-캄보디아 FTA")],
        "JPN": [(_COL_RCEP_JPN, "RCEP (일본)")],  # 한-일 양자 FTA는 체결된 적 없음
        "PHL": [(_COL_PHL, "한-필리핀 FTA")],
        "ARE": [(_COL_ARE, "한-UAE CEPA")],
    }
    eu_members = {
        "DEU", "FRA", "ITA", "ESP", "NLD", "BEL", "AUT", "PRT", "GRC", "SWE",
        "DNK", "FIN", "POL", "CZE", "IRL", "HUN", "ROU", "BGR", "HRV", "SVK",
        "SVN", "LTU", "LVA", "EST", "CYP", "MLT", "LUX",
    }
    if country_iso3 in eu_members:
        return [(_eu_col(), "한-EU FTA")]
    return mapping.get(country_iso3, [])


_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _parse_cell(raw: str):
    """셀 원문 -> (숫자값 또는 None, 화면표시용 문자열).
    '미양허', 'NS', TRQ/ASG 복합세율처럼 단순 %가 아닌 값은 숫자를 None으로
    두고(최적관세 비교에서 제외됨) 원문을 그대로 표시용으로 남긴다."""
    text = (raw or "").strip()
    if not text:
        return None, "정보 없음"
    if text == "미양허":
        return None, "미양허"
    if text == "NS":
        return None, "NS"

    # 순수 숫자(소수 포함)면 그대로 사용
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text), f"{text}%"

    # "6.4(CH 미양허)", "미양허(IS 4)"처럼 기본값 + 국가별 예외가 붙은 경우:
    # 맨 앞 숫자만 대표값으로 쓰고, 괄호 안 예외는 표시 문자열에 그대로 남긴다.
    m = _VALUE_RE.match(text)
    if m and text.startswith(m.group(1)):
        return float(m.group(1)), f"{text}%"

    # TRQ/ASG/원화 복합세율 등 단순 %로 환산 불가 - 원문 그대로 보여주고
    # 숫자 비교(최적관세 추천)에서는 제외
    return None, text


@lru_cache(maxsize=1)
def _load_rows():
    """CSV를 한 번만 읽어 HS코드(숫자만) -> 원본 row(list) 딕셔너리로 캐싱."""
    rows = {}
    if not os.path.exists(_CSV_PATH):
        return rows
    with open(_CSV_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not row or not row[1]:
                continue
            hs_digits = re.sub(r"\D", "", row[1])
            if hs_digits:
                rows[hs_digits] = row
    return rows


def find_matching_rows(hs_code: str):
    """등록된 HS코드(자릿수 상관없이, 예: '1905.90' 또는 '1905901050') ->
    이 표에서 그 코드로 시작하는 모든 세부품목 row 리스트."""
    digits = re.sub(r"\D", "", hs_code or "")
    if not digits:
        return []
    rows = _load_rows()
    if digits in rows:
        return [rows[digits]]
    return [row for code, row in rows.items() if code.startswith(digits)]


def get_tariff_regimes(hs_code: str, country_iso3: str):
    """HS코드 + 국가(ISO3) -> [{regime, tariff_ave, display}, ...].
    이 표에 나라 자체가 없으면 빈 리스트를 반환한다(정보 없음 처리는
    호출부에서)."""
    columns = _country_columns(country_iso3)
    if not columns:
        return []

    matched_rows = find_matching_rows(hs_code)
    if not matched_rows:
        return []

    # 항상 MFN(기본세율)이 있는 건 아니라서 - 이 표는 FTA/RCEP만 다루므로
    # MFN은 이 표 범위 밖. 국가별 협정 세율만 보여준다.
    regimes = []
    for col_idx, regime_name in columns:
        values = []
        displays = []
        for row in matched_rows:
            if col_idx >= len(row):
                continue
            num, disp = _parse_cell(row[col_idx])
            displays.append(disp)
            if num is not None:
                values.append(num)

        if not displays:
            continue

        unique_displays = set(displays)
        is_range = len(unique_displays) > 1
        if not is_range:
            display = displays[0]
        elif values and len(set(values)) == 1:
            display = f"{values[0]}%"
            is_range = False
        elif values:
            display = f"{min(values)}~{max(values)}% (세부품목별 상이)"
        else:
            display = "값 혼재 (세부품목별 상이)"

        tariff_ave = min(values) if values else None
        regimes.append({
            "regime": regime_name,
            "tariff_ave": tariff_ave,
            "display": display,
            "is_range": is_range,
        })

    return regimes


def get_subitem_breakdown(hs_code: str, country_iso3: str):
    """등록된 HS코드가 6~8자리라서 여러 10자리 세부품목에 걸칠 때, 그
    세부품목 각각의 코드/품명/실제 세율을 보여주기 위한 상세 목록.
    (범위 표시("0~5%")가 왜 나왔는지 사용자가 직접 확인할 수 있게 함).
    MFN(기본세율)도 FTA 협정과 같은 표에서 첫 번째 컬럼으로 함께 보여준다 -
    범위가 FTA 쪽이 아니라 MFN 쪽에서만 생겨도(예: 협정은 전부 0%인데
    MFN만 세부품목별로 다름) 이 표에서 바로 확인할 수 있어야 하기 때문."""
    matched_rows = {
        re.sub(r"\D", "", row[1]): row for row in find_matching_rows(hs_code) if len(row) > 1
    }
    fta_columns = _country_columns(country_iso3)
    mfn_by_code = {code: (name_ko, rate) for code, name_ko, rate in find_mfn_rows(hs_code, country_iso3)}

    # FTA 세부품목도, MFN 세부품목도 둘 다 1개 이하면 굳이 상세표를 보여줄 필요 없다.
    if len(matched_rows) <= 1 and len(mfn_by_code) <= 1:
        return []

    all_codes = sorted(set(matched_rows) | set(mfn_by_code))
    items = []
    for digits in all_codes:
        row = matched_rows.get(digits)
        rates = []
        if mfn_by_code:
            _, mfn_raw = mfn_by_code.get(digits, (None, None))
            _, mfn_disp = _parse_mfn_cell(mfn_raw) if mfn_raw is not None else (None, None)
            rates.append({"regime": "MFN(기본세율)", "display": mfn_disp or "정보 없음"})
        if row:
            for col_idx, regime_name in fta_columns:
                if col_idx >= len(row):
                    continue
                _, disp = _parse_cell(row[col_idx])
                rates.append({"regime": regime_name, "display": disp})
        name_ko = row[2].strip() if row and len(row) > 2 else (mfn_by_code.get(digits, ("", ""))[0] or "")
        code = row[1].strip() if row and len(row) > 1 else digits
        items.append({"code": code, "name_ko": name_ko, "rates": rates})
    return items


def get_best_regime(hs_code: str, country_iso3: str):
    regimes = [r for r in get_tariff_regimes(hs_code, country_iso3) if r["tariff_ave"] is not None]
    if not regimes:
        return None
    return min(regimes, key=lambda r: r["tariff_ave"])


def has_country_data(country_iso3: str) -> bool:
    """이 국가에 대한 협정세율 컬럼이 표에 있는지 (브라질/멕시코/사우디처럼
    아예 없는 나라와 구분하기 위함)."""
    return bool(_country_columns(country_iso3))


def _mfn_country_key(country_iso3: str) -> str:
    """EU 회원국은 MFN CSV에 개별 국가로 안 들어있고 'EEC'(EU 전체) 한
    묶음으로만 있다 (관세율표 자체가 EU 공동관세이기 때문)."""
    if country_iso3 in _EU_MEMBERS:
        return "EEC"
    return country_iso3


def _parse_mfn_cell(raw: str):
    """MFN CSV의 원문 세율 텍스트(이미 '%'/단위가 붙어있는 원본 그대로) ->
    (숫자값 또는 None, 화면표시용 문자열). 'Free'는 무관세 0%로,
    '8% + 21 GBP / 100 kg' 같은 복합세율은 앞의 %만 숫자로 쓰고 원문을
    그대로 보여준다(단순 % 비교가 부정확할 수 있어 최적관세 추천에선
    복합세율 여부와 무관하게 그대로 노출만 함)."""
    text = (raw or "").strip()
    if not text:
        return None, None
    if text.lower() == "free":
        return 0.0, "무관세 (Free)"
    m = _VALUE_RE.match(text)
    if m:
        return float(m.group(1)), text
    return None, text


@lru_cache(maxsize=1)
def _load_mfn_rows():
    """MFN CSV를 한 번만 읽어 국가키 -> {HS코드(숫자만): (품명, 세율원문)} 로 캐싱."""
    data = {}
    if not os.path.exists(_MFN_CSV_PATH):
        return data
    with open(_MFN_CSV_PATH, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 4:
                continue
            country, hs_code, name_ko, rate_display = row[0], row[1], row[2], row[3]
            digits = re.sub(r"\D", "", hs_code or "")
            if not digits:
                continue
            data.setdefault(country, {})[digits] = (name_ko, rate_display)
    return data


def find_mfn_rows(hs_code: str, country_iso3: str):
    """등록된 HS코드(자릿수 상관없이) -> 그 나라 MFN표에서 그 코드로
    시작하는 모든 세부품목 (HS코드, 품명, 세율원문) 리스트.

    나라마다 관세율표의 세분류 자릿수가 우리 관세청 10자리 기준과 다를 수
    있다. 예를 들어 한국 관세청은 "1212211010"(김, 건조한 것)처럼 10자리로
    세분화하지만, 미국 관세율표는 같은 품목을 "1212210000"(식용 김 전체)
    한 줄로만 관리한다 - 앞 6자리(HS6, 국제 공통 부분)까지만 같고 그 뒤는
    양쪽 다 0으로 채워져 있어 서로 startswith로는 안 걸린다. 그래서 정확히
    일치/앞부분 일치가 둘 다 실패하면 마지막으로 HS6(앞 6자리) 일치로
    한 번 더 시도한다."""
    digits = re.sub(r"\D", "", hs_code or "")
    if not digits:
        return []
    country_data = _load_mfn_rows().get(_mfn_country_key(country_iso3), {})
    if digits in country_data:
        name_ko, rate = country_data[digits]
        return [(digits, name_ko, rate)]

    matches = [
        (code, name_ko, rate)
        for code, (name_ko, rate) in country_data.items()
        if code.startswith(digits)
    ]
    if matches or len(digits) < 6:
        return matches

    hs6 = digits[:6]
    return [
        (code, name_ko, rate)
        for code, (name_ko, rate) in country_data.items()
        if code[:6] == hs6
    ]


def get_mfn_rate(hs_code: str, country_iso3: str):
    """HS코드 + 국가(ISO3) -> {"tariff_ave", "display", "is_range"} 또는
    None(그 나라 관세율표 자체가 없거나 이 HS코드가 없는 경우)."""
    matched = find_mfn_rows(hs_code, country_iso3)
    if not matched:
        return None

    values = []
    displays = []
    for _, _, rate in matched:
        num, disp = _parse_mfn_cell(rate)
        if disp is None:
            continue
        displays.append(disp)
        if num is not None:
            values.append(num)

    if not displays:
        return None

    unique_displays = set(displays)
    is_range = len(unique_displays) > 1
    if not is_range:
        display = displays[0]
    elif values and len(set(values)) == 1:
        display = f"{values[0]}%"
        is_range = False
    elif values:
        display = f"{min(values)}~{max(values)}% (세부품목별 상이)"
    else:
        display = "값 혼재 (세부품목별 상이)"

    return {
        "tariff_ave": min(values) if values else None,
        "display": display,
        "is_range": is_range,
    }


def has_mfn_data(country_iso3: str) -> bool:
    """이 국가의 관세청 원본 관세율표가 MFN CSV에 있는지."""
    return bool(_load_mfn_rows().get(_mfn_country_key(country_iso3)))

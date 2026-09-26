#!/usr/bin/env python3
"""
각국 관세청 관세율표(HWP/엑셀 원본, 사용자가 직접 업로드) -> 식품(HS 01~24류)
MFN(최혜국/기본) 관세율만 뽑아 scripts/market/mfn_base_rates.csv 로 통합.

기존 scripts/market/농축산물_FTA_협정세율_2026.csv 는 한국이 체결한 FTA/RCEP
"협정세율"만 다루고 MFN(기본) 관세율은 없다. 이 스크립트는 그 빈틈(관세율
탭에서 "기본세율"로 보여줄 MFN 기준값)을 채우기 위한 것.

국가별로 헤더 이름이 제각각이라( 기본세율 / 최혜국 / MFN / ERGA OMNES(EU) /
Column I(대만) / 종가세(페루) ) 우선순위 키워드로 그 나라의 실제 MFN에
해당하는 컬럼을 고른다. 상세 근거는 KEYWORD_NOTES 주석 참고.

튀르키예는 품목 카테고리(농산물/공산품/가공농산물/수산물)마다 헤더 구조가
통째로 다른 매트릭스표라 일반 로직으로 못 뽑아서 process_turkey()로 별도
처리한다: 헤더 1행(카테고리)+2행(국가그룹) 2단 구조에서, 데이터 행마다
실제 값이 채워진 컬럼들("활성 블록")을 찾고 그 안에서 'SOUTH KOREA' 단독
컬럼 -> 'S.KOREA'/'SOUTH KOREA'가 포함된 묶음 컬럼 -> 'Other'/'Other
Count.'(그 어떤 특혜 그룹에도 안 걸리는 국가용) 순으로 우선순위를 매겨
한국에 적용될 세율 컬럼을 고른다.

몽골은 사부작 박람회 목록에 없는 국가라 제외.

관세청 원본 엑셀을 못 구한 국가는 WTO Tariff Download Facility의 CSV
(컬럼: Reporter_ISO_N/ProductCode/SimpleAverage 등, HS 6자리 단순평균 MFN)로
보충한다 - process_wto_csv(). 엑셀 원본(10자리 세부품목)보다는 거칠지만
없는 것보다 낫다. Reporter_ISO_N은 UN M49 숫자코드라 pycountry로 ISO3 변환.

실행: python scripts/market/build_mfn_rates.py
"""

import csv
import glob
import re
from pathlib import Path

import openpyxl
import pycountry

UPLOAD_DIR = "/root/.claude/uploads/138da99a-9f5c-50ea-b27d-c52753a83a9a"
OUT_PATH = Path(__file__).resolve().parent / "mfn_base_rates.csv"

# 코드가 표준 ISO3가 아닌 경우만 정규화 (Cambodia/Brunei/Myanmar 원본 표기가
# 비표준이었음)
ISO3_FIX = {"CAM": "KHM", "BRU": "BRN", "MYA": "MMR"}

# 스킵할 파일(국가코드 기준): 몽골(박람회 목록에 없음). 튀르키예는
# process_turkey()로 별도 처리하므로 여기서 스킵하지 않는다.
SKIP_COUNTRIES = {"MNG"}
TURKEY_SPECIAL = {"TUR"}

# 이 순서대로 헤더에서 첫 매치되는 컬럼을 그 나라의 "MFN 기준 관세율"로 쓴다.
# 최혜국/MFN을 기본세율보다 먼저 두는 이유: 중국·캐나다·콜롬비아·필리핀
# 파일은 "기본세율"(비WTO국 대상 일반세율)과 "최혜국"(MFN, WTO회원국 대상)이
# 별도 컬럼으로 존재해서 반드시 최혜국 쪽을 골라야 한다.
KEYWORD_PRIORITY = [
    "최혜국",
    "MFN",
    "기본세율",
    "ERGA OMNES",  # EU
    "Column I -",  # 대만(WTO/상호대우국 대상 컬럼. "Column II"와 헷갈리지 않게 "-" 포함)
    "종가세",  # 페루(다른 기본세율 컬럼이 없어 종가세를 기준값으로 사용)
]

FOOD_CHAPTERS = {f"{i:02d}" for i in range(1, 25)}  # HS 01류~24류


def _flatten(cell):
    return (str(cell) if cell is not None else "").replace("\n", " ").strip()


def _find_mfn_col(header):
    flat = [_flatten(c) for c in header]
    for kw in KEYWORD_PRIORITY:
        for i, h in enumerate(flat):
            if kw in h:
                return i
    return None


def _extract_rate(raw):
    text = _flatten(raw)
    if not text:
        return None
    return text


def process_file(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter)
    mfn_col = _find_mfn_col(header)
    if mfn_col is None:
        print(f"  건너뜀 (MFN 컬럼 못찾음): {Path(path).name}")
        return None, []

    country = None
    out_rows = []
    for row in rows_iter:
        if len(row) < 4:
            continue
        code_cell = _flatten(row[2])
        hs_cell = _flatten(row[3])
        if code_cell:
            country = ISO3_FIX.get(code_cell, code_cell)
        if not hs_cell:
            continue
        digits = re.sub(r"\D", "", hs_cell)
        if not digits or len(digits) < 2:
            continue
        if digits[:2] not in FOOD_CHAPTERS:
            continue
        rate = _extract_rate(row[mfn_col]) if mfn_col < len(row) else None
        if not rate:
            continue
        name_ko = _flatten(row[5]) if len(row) > 5 else ""
        out_rows.append((country, digits, name_ko, rate))
    return country, out_rows


def process_turkey(path):
    """튀르키예: 카테고리(농산물/공산품/가공농산물/수산물)마다 헤더가 통째로
    다른 매트릭스표. 데이터 행마다 값이 채워진 컬럼 범위("활성 블록")를 찾고,
    그 안에서 한국에 적용되는 컬럼을 고른다(모듈 docstring 참고)."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    header1 = next(rows_iter)
    header2 = next(rows_iter)
    col_header = [_flatten(header2[i]) if i < len(header2) else "" for i in range(len(header1))]

    out_rows = []
    for row in rows_iter:
        if len(row) < 4:
            continue
        hs_cell = _flatten(row[3])
        digits = re.sub(r"\D", "", hs_cell)
        if not digits or len(digits) < 2 or digits[:2] not in FOOD_CHAPTERS:
            continue

        filled = [i for i in range(8, len(row)) if row[i] not in (None, "")]
        if not filled:
            continue

        chosen = None
        # 1) 'SOUTH KOREA' 단독 컬럼
        for i in filled:
            if col_header[i] == "SOUTH KOREA":
                chosen = i
                break
        # 2) 한국이 포함된 묶음 컬럼 (예: "EU, BOS-HERZ, UK, EFTA, F.ISLAND, S.KOREA, MYS")
        if chosen is None:
            for i in filled:
                if "S.KOREA" in col_header[i] or "SOUTH KOREA" in col_header[i]:
                    chosen = i
                    break
        # 3) 어떤 특혜 그룹에도 안 걸리는 나라용 "기타" 컬럼
        if chosen is None:
            for i in filled:
                if "Other" in col_header[i]:
                    chosen = i
                    break
        # 4) 최후 수단: 그 행에서 값이 채워진 첫 컬럼(활성 블록의 첫 컬럼이라
        #    보통 그 블록 전체에 적용되는 기본/일반 세율일 가능성이 높음)
        if chosen is None:
            chosen = filled[0]

        rate = _extract_rate(row[chosen])
        if not rate:
            continue
        name_ko = _flatten(row[5]) if len(row) > 5 else ""
        out_rows.append(("TUR", digits, name_ko, rate))
    return out_rows


def _m49_to_iso3(numeric: str):
    try:
        return pycountry.countries.get(numeric=str(int(numeric)).zfill(3)).alpha_3
    except (AttributeError, ValueError):
        return None


def process_wto_csv(path):
    """WTO Tariff Download Facility CSV -> (country_iso3, [(hs6, '', 세율표시), ...]).
    HS 6자리 단순평균(SimpleAverage) MFN 세율. 국가원본 엑셀이 없는 나라를
    보충하는 용도라 6자리보다 세부적인 값은 애초에 없다."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not {"Reporter_ISO_N", "ProductCode", "SimpleAverage"} <= set(reader.fieldnames or []):
            return None, []
        rows = list(reader)

    if not rows:
        return None, []
    iso3 = _m49_to_iso3(rows[0]["Reporter_ISO_N"])
    if not iso3:
        print(f"  건너뜀 (국가코드 변환 실패, M49={rows[0]['Reporter_ISO_N']}): {Path(path).name}")
        return None, []

    out_rows = []
    for row in rows:
        digits = re.sub(r"\D", "", row.get("ProductCode", ""))
        if not digits or digits[:2] not in FOOD_CHAPTERS:
            continue
        avg = (row.get("SimpleAverage") or "").strip()
        if not avg:
            continue
        out_rows.append((iso3, digits, "", f"{float(avg):g}%"))
    return iso3, out_rows


def main():
    files = sorted(glob.glob(f"{UPLOAD_DIR}/*.xlsx"))
    all_rows = []
    seen_countries = set()
    for f in files:
        name = Path(f).name
        wb_peek = openpyxl.load_workbook(f, data_only=True, read_only=True)
        ws_peek = wb_peek[wb_peek.sheetnames[0]]
        first_data_row = None
        for r in ws_peek.iter_rows(min_row=2, max_row=5, values_only=True):
            if r[2]:
                first_data_row = r
                break
        peek_country = _flatten(first_data_row[2]) if first_data_row else ""
        peek_country = ISO3_FIX.get(peek_country, peek_country)
        if peek_country in SKIP_COUNTRIES:
            print(f"  건너뜀 (제외 대상: {peek_country}): {name}")
            continue

        if peek_country in TURKEY_SPECIAL:
            print(f"처리 중 (특수 매트릭스): {name} ({peek_country})")
            rows = process_turkey(f)
            if rows:
                seen_countries.add("TUR")
                all_rows.extend(rows)
            continue

        print(f"처리 중: {name} ({peek_country})")
        country, rows = process_file(f)
        if not rows:
            continue
        seen_countries.add(country)
        all_rows.extend(rows)

    # WTO Tariff Download Facility CSV로 보충 (관세청 원본 엑셀이 없는 나라만 -
    # 엑셀로 이미 받은 나라는 10자리 세부품목이 있는 엑셀 쪽이 더 정확하니 그대로 둔다)
    for f in sorted(glob.glob(f"{UPLOAD_DIR}/*.csv")) + sorted(glob.glob(f"{UPLOAD_DIR}/*.CSV")):
        name = Path(f).name
        iso3, wto_rows = process_wto_csv(f)
        if not iso3 or not wto_rows:
            continue
        if iso3 in seen_countries:
            print(f"  건너뜀 (이미 엑셀 원본으로 커버됨: {iso3}): {name}")
            continue
        print(f"처리 중 (WTO CSV): {name} ({iso3})")
        seen_countries.add(iso3)
        all_rows.extend(wto_rows)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["country_iso3", "hs_code", "name_ko", "mfn_rate_display"])
        writer.writerows(all_rows)

    print(f"\n완료: {len(all_rows)}행, {len(seen_countries)}개국 -> {OUT_PATH}")
    print("국가 목록:", ", ".join(sorted(seen_countries)))


if __name__ == "__main__":
    main()

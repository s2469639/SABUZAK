#!/usr/bin/env python3
"""
UNCTAD TRAINS Online(trainsonline.unctad.org)에서 (박람회 국가 x 등록 제품)
조합별 무역 규정을 가져와서 NtmMeasure 캐시 테이블에 채워넣는 배치 스크립트.

macmap.org는 Cloudflare로 막혀서(403 + JS challenge) requests로 접근 불가능해져
포기했고, macmap이 원래 참조하는 원본 데이터 출처인 TRAINS Online으로 교체했다.
로그인/세션쿠키 없이 호출 가능해서 macmap보다 오히려 쉽다.

TRAINS의 현재 API(denormalisedRegulations)는 imposingCountries에 ISO3
코드를, products에 실제 HS코드를 그대로 받아서, (국가, 제품 HS코드)
조합별로 바로바로 따로 조회한다 (app.services.trains_client.
fetch_regulations_for_country). 제품마다 HS코드가 다르므로 캐시도
NtmMeasure.product 컬럼에 그 제품의 실제 HS코드로 저장한다.

웹앱은 이 캐시 테이블만 읽고, TRAINS를 직접 호출하지 않는다 (박람회 상세
페이지의 "지금 실제 데이터 가져오기" 버튼은 국가+제품 1쌍만 즉시 조회하는
별도 경로 - app/routes/exhibition.py의 sync_ntm).

국가는 pycountry로 전세계를 다 인식한다 (pip install pycountry 필요).
--importers 없이 실행하면 raw_exhibitions에 실제로 등록된 국가들만 대상으로 하고,
제품은 체크된(is_checked) + HS코드가 있는 전체 유저의 제품을 대상으로 한다.

실행 (sabuzak 루트에서):
    python scripts/market/sync_ntm_cache.py                          # DB에 있는 박람회 국가 x 등록 제품 전부
    python scripts/market/sync_ntm_cache.py --importers USA,CHN,SGP  # 특정 국가만 (ISO3)
    python scripts/market/sync_ntm_cache.py --force                  # 이미 캐시된 것도 재수집
"""

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Exhibition, NtmMeasure, Product  # noqa: E402
from app.services.hscode import resolve_country_iso  # noqa: E402
from app.services.trains_client import (  # noqa: E402
    fetch_regulations_for_country,
    no_match_row,
    to_ntm_measure_rows,
    top_relevant_regulations,
)

def _countries_from_exhibitions():
    """raw_exhibitions에 실제로 등록된 국가들을 ISO3로 변환한 목록."""
    country_names = [
        row[0]
        for row in Exhibition.query.filter(Exhibition.is_active == 1)
        .with_entities(Exhibition.country)
        .distinct()
        .all()
        if row[0]
    ]
    iso3_list = set()
    for name in country_names:
        iso3 = resolve_country_iso(name)
        if iso3:
            iso3_list.add(iso3)
        else:
            print(f"  국가명 인식 실패(건너뜀): {name}")
    return sorted(iso3_list)


def _hs_codes_from_products():
    """체크되고 HS코드가 등록된 전체 유저의 제품 HS코드 -> 제품명 매핑.
    같은 HS코드를 여러 유저가 다른 이름으로 등록했을 수 있는데, LLM 관련도
    검증(top_relevant_regulations의 product_name)에 하나만 필요하니 먼저
    나온 이름을 대표로 쓴다."""
    products = Product.query.filter(
        Product.is_checked == True,  # noqa: E712
        Product.hs_code.isnot(None),
        Product.hs_code != "",
    ).with_entities(Product.hs_code, Product.name).all()

    hs_code_to_name = {}
    for hs_code, name in products:
        hs_code_to_name.setdefault(hs_code, name)
    return hs_code_to_name


def already_cached(reporter, hs_code):
    return (
        NtmMeasure.query.filter_by(reporter=reporter, product=hs_code).first() is not None
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--importers", help="ISO3 코드 콤마구분 (예: USA,CHN,SGP). 미지정시 DB에 등록된 박람회 국가 전부")
    ap.add_argument("--force", action="store_true", help="이미 캐시된 조합도 재수집")
    args = ap.parse_args()

    importer_filter = args.importers.split(",") if args.importers else None

    app = create_app()
    with app.app_context():
        countries = [c.upper() for c in importer_filter] if importer_filter else _countries_from_exhibitions()
        hs_code_to_name = _hs_codes_from_products()
        hs_codes = sorted(hs_code_to_name)
        if not countries or not hs_codes:
            print(f"대상을 찾지 못했습니다 (국가 {len(countries)}개, 제품 HS코드 {len(hs_codes)}개).")
            return

        pairs = [(iso3, hs_code) for iso3 in countries for hs_code in hs_codes]
        if not args.force:
            pairs = [(iso3, hs) for iso3, hs in pairs if not already_cached(iso3, hs)]

        if not pairs:
            print("수집할 대상이 없습니다 (모두 캐시됨). --force로 재수집 가능.")
            return

        print(f"대상: {len(countries)}개국 x {len(hs_codes)}개 HS코드 = {len(pairs)}쌍 (UNCTAD TRAINS Online)")

        total_rows = 0
        failed = 0

        for i, (iso3, hs_code) in enumerate(pairs, 1):
            print(f"[{i}/{len(pairs)}] country={iso3} hs_code={hs_code}")
            try:
                regulations = fetch_regulations_for_country(iso3, hs_code)
                top6 = top_relevant_regulations(
                    regulations, hs_code, product_name=hs_code_to_name.get(hs_code), limit=6
                )
                rows = to_ntm_measure_rows(iso3, hs_code, top6, summarize=True)
                NtmMeasure.query.filter_by(reporter=iso3, product=hs_code).delete()
                if rows:
                    for row in rows:
                        db.session.add(NtmMeasure(**row))
                else:
                    # 진짜 0건이어도 조회는 했다는 걸 표시 (안 그러면 웹앱이
                    # "아직 조회 안 함"으로 착각해서 정적 예시 데이터로 폴백함)
                    db.session.add(NtmMeasure(**no_match_row(iso3, hs_code)))
                db.session.commit()
                total_rows += len(rows)
                print(f"  -> {len(rows)}건 저장")
            except Exception as e:
                print(f"  -> 실패: {e}")
                failed += 1

        print(f"\n완료: 총 {total_rows}건 저장 / 실패 {failed}건 (대상 {len(pairs)}쌍 중)")


if __name__ == "__main__":
    main()

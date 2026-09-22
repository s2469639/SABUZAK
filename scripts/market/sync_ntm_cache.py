#!/usr/bin/env python3
"""
macmap.org NTM(비관세조치) 데이터를 등록된 제품의 HS코드 x 수입국 조합으로
가져와서 NtmMeasure 캐시 테이블에 채워넣는 배치 스크립트.

웹앱(app/services/hscode.py)은 이 캐시 테이블만 읽고, macmap을 직접 호출하지
않는다. macmap이 매너 딜레이(2초)를 요구하고 세션 쿠키 기반이라 실시간 요청
경로에 넣기엔 부적절하기 때문.

국가는 pycountry로 전세계를 다 인식한다 (pip install pycountry 필요).
--importers 없이 실행하면 raw_exhibitions에 실제로 등록된 국가들만 대상으로 한다
(전세계 249개국을 무의미하게 다 돌리지 않기 위함).

실행 (sabuzak 루트에서):
    python scripts/market/sync_ntm_cache.py                       # DB에 있는 박람회 국가 전부
    python scripts/market/sync_ntm_cache.py --importers USA,CHN,ARM  # 특정 국가만 (ISO3)
    python scripts/market/sync_ntm_cache.py --force                # 이미 캐시된 것도 재수집
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Exhibition, NtmMeasure, Product  # noqa: E402
from app.services.hscode import get_m49_code, resolve_country_iso  # noqa: E402
from app.services.macmap_client import KOREA_M49, fetch_ntm_rows, make_session  # noqa: E402


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


def get_target_pairs(importer_filter):
    """(importer_m49, hs_code) 조합 목록. 등록된 제품의 HS코드 x 대상 수입국."""
    hs_codes = sorted({
        p.hs_code.replace(".", "")[:6]
        for p in Product.query.filter(Product.hs_code.isnot(None), Product.hs_code != "").all()
        if p.hs_code
    })
    if not hs_codes:
        print("등록된 제품(HS코드)이 없습니다. 마이페이지에서 제품을 먼저 등록해주세요.")
        return []

    importers = [c.upper() for c in importer_filter] if importer_filter else _countries_from_exhibitions()
    if not importers:
        print("대상 국가를 찾지 못했습니다.")
        return []

    pairs = []
    for iso3 in importers:
        m49 = get_m49_code(iso3)
        if not m49:
            print(f"  M49 코드를 못 찾아 건너뜀: {iso3}")
            continue
        for hs6 in hs_codes:
            pairs.append((m49, hs6))
    return pairs


def already_cached(reporter, product):
    return (
        NtmMeasure.query.filter_by(reporter=reporter, product=product).first() is not None
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--importers", help="ISO3 코드 콤마구분 (예: USA,CHN,ARM). 미지정시 DB에 등록된 박람회 국가 전부")
    ap.add_argument("--force", action="store_true", help="이미 캐시된 (국가,HS코드) 조합도 재수집")
    args = ap.parse_args()

    importer_filter = args.importers.split(",") if args.importers else None

    app = create_app()
    with app.app_context():
        pairs = get_target_pairs(importer_filter)
        if not pairs:
            return

        if not args.force:
            pairs = [(r, p) for r, p in pairs if not already_cached(r, p)]

        if not pairs:
            print("수집할 대상이 없습니다 (모두 캐시됨). --force로 재수집 가능.")
            return

        print(f"대상: {len(pairs)}건 (reporter=수입국 M49, partner=한국 고정 {KOREA_M49})")
        session = make_session()
        total_rows = 0
        failed = 0

        for i, (reporter, product) in enumerate(pairs, 1):
            print(f"[{i}/{len(pairs)}] reporter={reporter} product={product}")
            try:
                rows = fetch_ntm_rows(session, reporter, product)
                # 재수집(--force)인 경우 기존 캐시를 지우고 새로 넣는다
                NtmMeasure.query.filter_by(reporter=reporter, product=product).delete()
                for row in rows:
                    db.session.add(NtmMeasure(fetched_at=datetime.now(timezone.utc), **row))
                db.session.commit()
                total_rows += len(rows)
                print(f"  -> {len(rows)}건 저장")
            except Exception as e:
                print(f"  -> 실패: {e}")
                failed += 1

        print(f"\n완료: 총 {total_rows}건 저장 / 실패 {failed}건 (대상 {len(pairs)}건 중)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
UNCTAD TRAINS Online(trainsonline.unctad.org)에서 국가별 무역 규정을 가져와서
NtmMeasure 캐시 테이블에 채워넣는 배치 스크립트.

macmap.org는 Cloudflare로 막혀서(403 + JS challenge) requests로 접근 불가능해져
포기했고, macmap이 원래 참조하는 원본 데이터 출처인 TRAINS Online으로 교체했다.
로그인/세션쿠키 없이 호출 가능해서 macmap보다 오히려 쉽다.

주의: TRAINS의 현재 API(denormalisedMeasures)는 국가를 UNCTAD 내부 숫자
ID로만 지정할 수 있어서(ISO코드 아님), 나라별로 따로 조회하는 대신
**전세계를 한 번만 조회**하고 응답에 포함된 국가명 문자열로 우리 쪽에서
나라별로 묶는다 (app.services.trains_client.group_measures_by_country).
이후 웹앱(app/services/hscode.py의 get_country_regulations)이 식품/농산물
관련도로 한 번 더 걸러서 보여준다.

웹앱은 이 캐시 테이블만 읽고, TRAINS를 직접 호출하지 않는다 (박람회 상세
페이지의 "지금 실제 데이터 가져오기" 버튼은 국가 1개만 즉시 조회하는 별도
경로 - app/routes/exhibition.py의 sync_ntm).

국가는 pycountry로 전세계를 다 인식한다 (pip install pycountry 필요).
--importers 없이 실행하면 raw_exhibitions에 실제로 등록된 국가들만 대상으로 한다.

실행 (sabuzak 루트에서):
    python scripts/market/sync_ntm_cache.py                          # DB에 있는 박람회 국가 전부
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
from app.models import Exhibition, NtmMeasure  # noqa: E402
from app.services.hscode import resolve_country_iso  # noqa: E402
from app.services.trains_client import (  # noqa: E402
    fetch_all_measures_affecting_korea,
    group_measures_by_country,
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


def already_cached(reporter):
    return (
        NtmMeasure.query.filter_by(reporter=reporter, product="ALL").first() is not None
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--importers", help="ISO3 코드 콤마구분 (예: USA,CHN,SGP). 미지정시 DB에 등록된 박람회 국가 전부")
    ap.add_argument("--force", action="store_true", help="이미 캐시된 국가도 재수집")
    args = ap.parse_args()

    importer_filter = args.importers.split(",") if args.importers else None

    app = create_app()
    with app.app_context():
        countries = [c.upper() for c in importer_filter] if importer_filter else _countries_from_exhibitions()
        if not countries:
            print("대상 국가를 찾지 못했습니다.")
            return

        if not args.force:
            countries = [c for c in countries if not already_cached(c)]

        if not countries:
            print("수집할 대상이 없습니다 (모두 캐시됨). --force로 재수집 가능.")
            return

        print(f"대상: {len(countries)}개국 (UNCTAD TRAINS Online)")

        # 새 API는 국가를 UNCTAD 내부 숫자 ID로만 지정할 수 있어서, 나라별로
        # 따로 조회하는 대신 전세계를 한 번만 조회하고 국가명으로 묶는다.
        print("전세계 데이터 조회 중 (한 번만 호출, 페이지네이션 처리)...")
        try:
            all_rows = fetch_all_measures_affecting_korea()
        except Exception as e:
            print(f"전세계 조회 실패: {e}")
            return
        print(f"전세계 {len(all_rows)}건 수신, 국가별로 분류 중...")
        grouped = group_measures_by_country(all_rows)

        total_rows = 0
        failed = 0

        for i, iso3 in enumerate(countries, 1):
            print(f"[{i}/{len(countries)}] country={iso3}")
            try:
                regulations = grouped.get(iso3, [])
                top6 = top_relevant_regulations(regulations, limit=6)
                rows = to_ntm_measure_rows(iso3, "ALL", top6, summarize=True)
                NtmMeasure.query.filter_by(reporter=iso3, product="ALL").delete()
                for row in rows:
                    db.session.add(NtmMeasure(**row))
                db.session.commit()
                total_rows += len(rows)
                print(f"  -> {len(rows)}건 저장")
            except Exception as e:
                print(f"  -> 실패: {e}")
                failed += 1

        print(f"\n완료: 총 {total_rows}건 저장 / 실패 {failed}건 (대상 {len(countries)}개국 중)")


if __name__ == "__main__":
    main()

"""부스 컨셉 생성 엔진 스모크 테스트.

기본값은 DB 없이 샘플 데이터(고기만두 x 미국 종합식품 박람회)로 돌아간다.
--expo-id / --product-ids를 주면 실제 sabuzak.db/app_data.db 데이터로 테스트한다.
--live-trends를 주면 pytrends로 실제 트렌드 조회를 시도한다 (느리고 자주 실패함).

사용 예:
  python scripts/test_booth_concept.py
  python scripts/test_booth_concept.py --expo-id 123 --product-ids 4 5
  python scripts/test_booth_concept.py --live-trends
"""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.schemas.booth_concept import BoothConcept
from app.services.booth_concept import fetch_trends_data, generate_booth_concept

SAMPLE_EXPO = SimpleNamespace(
    name="Summer Fancy Food Show 2025",
    country="United States",
    country_ko="미국",
    city="New York City",
    start_date=20250629,
    end_date=20250701,
    category="Food Fairs",
    intro_ko="북미 최대 규모의 특수식품(Specialty Food) 박람회. 프리미엄/이색 식품 바이어가 집중 방문.",
    intro=None,
)

SAMPLE_PRODUCTS = [
    SimpleNamespace(
        name="고기만두",
        ingredients="돼지고기, 양배추, 부추, 얇은 만두피",
        certifications="HACCP",
        strengths="얇고 쫄깃한 만두피, 육즙 가득한 소",
        target_price="9.99 USD / 500g (10개입)",
    )
]


def _print_section(title):
    print(f"\n{'=' * 10} {title} {'=' * 10}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expo-id", type=int, default=None, help="실제 Exhibition.id (없으면 샘플 데이터 사용)")
    parser.add_argument("--product-ids", type=int, nargs="*", default=None, help="실제 Product.id 목록")
    parser.add_argument("--live-trends", action="store_true", help="pytrends로 실제 트렌드 조회 시도")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.expo_id is not None:
            from app.models import Exhibition, Product

            expo = Exhibition.query.get(args.expo_id)
            if expo is None:
                print(f"Exhibition id={args.expo_id} 를 찾을 수 없습니다.")
                return
            if args.product_ids:
                products = Product.query.filter(Product.id.in_(args.product_ids)).all()
            else:
                products = Product.query.filter_by(is_checked=True).limit(2).all()
        else:
            expo, products = SAMPLE_EXPO, SAMPLE_PRODUCTS

        _print_section("INPUT")
        print(f"박람회: {expo.name} ({expo.country_ko or expo.country})")
        print(f"제품: {', '.join(p.name for p in products) or '(없음)'}")

        trends_data = fetch_trends_data(expo, products) if args.live_trends else None
        if args.live_trends:
            _print_section("TRENDS (live)")
            print(json.dumps(trends_data, ensure_ascii=False, indent=2))

        _print_section("GENERATED CONCEPT")
        result = generate_booth_concept(expo, products, trends_data=trends_data)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        _print_section("SCHEMA CHECK")
        try:
            concept = BoothConcept.model_validate(result)
            print(f"OK - selling_points={len(concept.selling_points)}, "
                  f"event_plans={len(concept.event_plans)}, "
                  f"target_buyers={len(concept.target_buyers)}")
        except Exception as e:
            print(f"FAIL - {e}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""단독 실행 CLI. 제품명+국가로 시장/트렌드 조사 결과를 터미널에서 확인.

사전 준비:
    pip install -r requirements.txt
    .env 파일에 OPENAI_API_KEY, TAVILY_API_KEY 설정 (없으면 실행 시 물어봄)

실행:
    python cli.py --product 김부각 --country "United States"
    python cli.py --product 김부각 --country Japan --force   # 캐시 무시하고 재조사
"""

import argparse
import sys

from env_setup import ensure_required_keys
from market_research import get_market_research


def main():
    parser = argparse.ArgumentParser(description="제품명+국가 시장/트렌드 조사 (Tavily)")
    parser.add_argument("--product", required=True, help="예: 김부각")
    parser.add_argument("--country", required=True, help="예: United States")
    parser.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조사")
    args = parser.parse_args()

    ensure_required_keys()

    try:
        result = get_market_research(args.product, args.country, force=args.force)
    except Exception as e:
        # 원인(네트워크 오류, API 응답 오류 등)의 전체 traceback은
        # market_research.py가 이미 터미널에 찍어줬으니, 여기서는 한 줄로만 정리
        print(f"오류: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"[{result['country']}] {result['product_name']} 시장/트렌드 조사")
    print(f"캐시 사용: {result['from_cache']} / 조사 시각: {result['fetched_at']}")
    print("=" * 60)

    print(f"\n[추출된 키워드 {len(result['keywords'])}개]: {result['keywords']}\n")

    if result.get("overall_summary_ko"):
        print("📝 종합 요약 (한국어)")
        print(result["overall_summary_ko"])
        print()

    if result["failed_keywords"]:
        if len(result["failed_keywords"]) == len(result["keywords"]):
            print(
                f"⚠️  모든 키워드({len(result['failed_keywords'])}개) 검색에 실패했습니다. "
                "네트워크 상태나 API 키를 확인해주세요.\n"
            )
        else:
            print(f"⚠️  일부 키워드 검색 실패: {result['failed_keywords']}\n")

    if not result["insights"]:
        if not result["failed_keywords"]:
            print("검색 결과가 없습니다.")
        return

    for i, item in enumerate(result["insights"], 1):
        print(f"{i}. {item['title']}  ({item['keyword']})")
        if item.get("summary_ko"):
            print(f"   [한글 요약] {item['summary_ko']}")
        print(f"   [원문] {item['summary']}")
        print(f"   🔗 원문 링크: {item['url']}")
        print("-" * 40)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""평가 세트 3×3 자동 점검 (v6.0)

코드를 고친 뒤 같은 9개 조합(제품 3 × 국가 3)을 돌려, 규칙이 조건별로 제대로 작동하는지 숫자로 확인한다.
식품 정보가 맞는지를 검증하는 도구가 아니라, 프로그램의 거르는 규칙을 점검하는 도구다.

    python eval/run_eval.py                          # 9개 조합 실행 (캐시가 있으면 재사용)
    python eval/run_eval.py --force                  # 캐시 무시하고 새로 조사
    python eval/run_eval.py --only 김부각:Germany     # 일부만
    python eval/run_eval.py --compare eval/results/20260922_1030.csv   # 이전 결과와 비교

결과: eval/results/<시각>.csv (숫자), eval/results/<시각>.md (표 + 사람이 확인할 발췌 샘플)
"""

import argparse
import csv
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env_setup import ensure_required_keys  # noqa: E402
from research import REGIONS, TLD_REGION, _tld, run_research, source_quality  # noqa: E402

# 제품: 틈새(김부각) / 나라마다 이름이 다른 제품(소금빵) / 자료가 많은 인기 제품군(비건 만두)
# 국가: 영어권·북미(미국) / 비영어권·유럽(독일) / 아시아·한국 식품 친숙(일본)
PRODUCTS = ["김부각", "소금빵", "비건 만두"]
COUNTRIES = ["United States", "Germany", "Japan"]
SAMPLES_PER_CASE = 5
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

# 자동 집계 항목: (열 이름, 설명, 좋은 방향)
METRICS = [
    ("sources_found", "검색된 출처 수", "참고"),
    ("quotes_used", "사용된 발췌 수", "높을수록"),
    ("country_quotes", "대상 국가 발췌", "높을수록"),
    ("region_quotes", "권역 참고 발췌", "참고"),
    ("excluded_source", "보고서 사이트·SNS 제외 건수", "참고"),
    ("market_other", "다른 시장으로 제외된 출처", "참고"),
    ("bad_domain_used", "근거로 쓰인 보고서 사이트·SNS (0이어야 함)", "0"),
    ("foreign_tld_country", "다른 나라 도메인인데 '대상 국가'로 판정된 발췌 (확인 필요)", "낮을수록"),
    ("wrong_region_query", "다른 권역 이름이 들어간 쿼리 (0이어야 함)", "0"),
    ("weak_questions", "발췌 2건 미만인 질문", "참고"),
    ("product_quotes_q1q2", "Q1·Q2의 제품 발췌 (대상 국가)", "높을수록"),
    ("stale_quotes", "오래된 자료 발췌", "낮을수록"),
    ("translation_warnings", "번역 숫자 불일치", "낮을수록"),
    ("dropped_sentences", "검사에서 지운 요약 문장", "참고"),
    ("main_quotes", "주요 사이트 발췌 (v6)", "높을수록"),
    ("open_quotes", "일반 웹 발췌 (v6)", "참고"),
    ("fallback_questions", "일반 웹으로 넓힌 질문 (v6)", "참고"),
]


def measure(r):
    sources = {s["id"]: s for s in r["sources"]}
    t, st = r["terms"], r["stats"]
    other_regions = [name.lower() for key, (name, _, _) in REGIONS.items() if key != t.get("region_key")]
    m = {k: st.get(k, 0) for k in ("sources_found", "quotes_used", "country_quotes", "region_quotes",
                                     "excluded_source", "market_other", "stale_quotes", "translation_warnings")}
    m["bad_domain_used"] = sum(1 for q in r["quotes"] for sid in q["source_ids"]
                               if source_quality(sources[sid]["domain"]))
    m["foreign_tld_country"] = sum(
        1 for q in r["quotes"] if q["market"] == "country"
        and (tld := _tld(sources[q["source_ids"][0]]["domain"])) in TLD_REGION and tld != t.get("tld")
        and not sources[q["source_ids"][0]].get("is_public_kr"))
    m["wrong_region_query"] = sum(1 for q in r["queries"] if any(reg in q.lower() for reg in other_regions))
    m["weak_questions"] = ",".join(c["qid"] for c in r["cards"] if len(c["quote_ids"]) < 2) or "-"
    m["product_quotes_q1q2"] = sum(c["product_quotes"] for c in r["cards"] if c["qid"] in ("Q1", "Q2"))
    m["dropped_sentences"] = sum(len(c["dropped"]) for c in r["cards"])
    m["main_quotes"] = st.get("main_quotes", 0)
    m["open_quotes"] = st.get("open_quotes", 0)
    m["fallback_questions"] = ",".join(st.get("fallback_questions") or []) or "-"
    return m


def write_markdown(path, rows, results):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 평가 세트 결과 ({os.path.basename(path)[:-3]})\n\n")
        f.write("## 자동 집계\n\n| 조합 | " + " | ".join(desc for _, desc, _ in METRICS) + " |\n")
        f.write("|---|" + "---|" * len(METRICS) + "\n")
        for row in rows:
            f.write(f"| {row['case']} | " + " | ".join(str(row[k]) for k, _, _ in METRICS) + " |\n")
        f.write("\n'0이어야 함' 항목이 0이 아니면 규칙이 새고 있는 것입니다. 해당 조합을 `python cli.py --debug`로 확인하세요.\n\n")
        f.write("## 사람이 확인할 발췌 샘플\n\n판정: 맞음 / 제품 무관 / 다른 시장 / 번역 오류 / 요약 일반화\n\n")
        for case, r in results.items():
            f.write(f"### {case}\n\n")
            for c in r["cards"]:
                if c["qid"] in ("Q1", "Q2") and c["conclusion"]:
                    f.write(f"- {c['qid']} 결론: {c['conclusion']['text']} (근거 {', '.join(c['conclusion']['quote_ids'])})\n")
            f.write("\n| 발췌 | 배지 | 원문 | 번역 | 링크 | 판정 |\n|---|---|---|---|---|---|\n")
            sources = {s["id"]: s for s in r["sources"]}
            for q in random.sample(r["quotes"], min(SAMPLES_PER_CASE, len(r["quotes"]))):
                quote = q["quote"].replace("|", "/")
                tr = (q["translation_ko"] or "").replace("|", "/")
                f.write(f"| {q['id']} | {q['scope_label']}, {q['market_label']}, {q.get('tier_label', '')} | {quote} | {tr} | "
                        f"{sources[q['source_ids'][0]]['url']} |  |\n")
            f.write("\n")


def compare(prev_path, rows):
    with open(prev_path, encoding="utf-8") as f:
        prev = {row["case"]: row for row in csv.DictReader(f)}
    print(f"\n[이전 결과와 비교] {os.path.basename(prev_path)}")
    keys = ["quotes_used", "country_quotes", "bad_domain_used", "foreign_tld_country",
            "wrong_region_query", "product_quotes_q1q2", "weak_questions"]
    print("조합".ljust(26) + "".join(k[:18].ljust(20) for k in keys))
    for row in rows:
        p = prev.get(row["case"])
        if not p:
            continue
        cells = [f"{p.get(k, '?')} → {row[k]}" for k in keys]
        print(row["case"].ljust(26) + "".join(c.ljust(20) for c in cells))


def main():
    ap = argparse.ArgumentParser(description="평가 세트 3×3 자동 점검")
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 새로 조사")
    ap.add_argument("--only", nargs="*", help="예: 김부각:Germany 소금빵:Japan")
    ap.add_argument("--compare", help="비교할 이전 결과 CSV 경로")
    args = ap.parse_args()

    ensure_required_keys()
    cases = [(p, c) for p in PRODUCTS for c in COUNTRIES]
    if args.only:
        wanted = {tuple(x.split(":", 1)) for x in args.only}
        cases = [x for x in cases if x in wanted]

    rows, results = [], {}
    for product, country in cases:
        case = f"{product} × {country}"
        print(f"실행 중: {case} ...", flush=True)
        try:
            r = run_research(product, country, force=args.force)
        except Exception as e:
            print(f"  실패: {e}")
            continue
        results[case] = r
        rows.append({"case": case, "version": r["version"], **measure(r)})

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(RESULTS_DIR, f"{stamp}.csv")
    md_path = os.path.join(RESULTS_DIR, f"{stamp}.md")
    if rows:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        write_markdown(md_path, rows, results)

    print("\n" + "조합".ljust(26) + "발췌  국가  보고서·SNS사용  타국도메인  타권역쿼리  제품발췌(Q1Q2)  부족질문")
    for row in rows:
        print(row["case"].ljust(26) + f"{row['quotes_used']:<6}{row['country_quotes']:<6}{row['bad_domain_used']:<16}"
              f"{row['foreign_tld_country']:<12}{row['wrong_region_query']:<12}{row['product_quotes_q1q2']:<16}{row['weak_questions']}")
    print(f"\n저장: {csv_path}\n      {md_path}")
    if args.compare:
        compare(args.compare, rows)


if __name__ == "__main__":
    main()

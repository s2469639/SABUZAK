"""Connect v5 evidence to the UI without generating new facts."""
from collections import OrderedDict
from urllib.parse import urlsplit

TITLES = {"Q1": "소비자", "Q2": "경쟁제품", "Q3": "바이어·유통", "Q4": "박람회·부스"}
FIELDS = ("product_name", "country", "ingredients", "target_price", "certifications",
          "strengths", "exhibition_month", "exhibition_name", "exhibition_website")


def safe_url(value):
    try:
        u = urlsplit(value or "")
        return value if u.scheme in ("https", "http") and u.hostname and not u.username else None
    except ValueError:
        return None


def validate_specs(data):
    if not isinstance(data, dict):
        raise ValueError("입력 내용을 확인해주세요.")
    specs = {}
    for name in FIELDS:
        value = data.get(name, "") or ""
        if not isinstance(value, str):
            raise ValueError("입력은 문자여야 합니다.")
        value = value.strip()
        limit = 100 if name in ("product_name", "country", "exhibition_name", "exhibition_website") else 300
        if len(value) > limit:
            raise ValueError(f"{name}: {limit}자 이내로 입력해주세요.")
        specs[name] = value
    if not specs["product_name"] or not specs["country"]:
        raise ValueError("제품명과 국가를 입력해주세요.")
    if specs["exhibition_website"] and not safe_url(specs["exhibition_website"]):
        raise ValueError("박람회 홈페이지는 http 또는 https 주소로 입력해주세요.")
    month = specs["exhibition_month"].replace("월", "").strip()
    if month and (not month.isdigit() or not 1 <= int(month) <= 12):
        raise ValueError("개최 월은 1~12월로 입력해주세요.")
    specs["exhibition_month"] = month + "월" if month else "10월"
    return specs


def adapt_report(report):
    sources = {s["id"]: s for s in report.get("sources", []) if safe_url(s.get("url"))}
    quotes = {}
    for original in report.get("quotes", []):
        q = dict(original)
        q["source_ids"] = [sid for sid in q.get("source_ids", []) if sid in sources]
        if q["source_ids"]:
            if q.get("translation_warning"):
                q["translation_ko"] = ""
            quotes[q["id"]] = q
    originals = {c["qid"]: c for c in report.get("cards", [])}
    cards = []
    for qid, title in TITLES.items():
        card = originals.get(qid, {})
        mine = {qid_: q for qid_, q in quotes.items() if q.get("question") == qid}
        # Only keep a summary when every reference resolves in this category.
        def linked(statement, current=False):
            if not isinstance(statement, dict):
                return None
            ids = statement.get("quote_ids", [])
            if not ids or not all(i in mine for i in ids):
                return None
            if current and not any(mine[i].get("year") and not mine[i].get("date_unverified")
                                   and not mine[i].get("is_stale") for i in ids):
                return None
            return statement
        conclusion = linked(card.get("conclusion"), current=True)
        points = [p for p in card.get("points", []) if linked(p)]
        grouped = OrderedDict()
        for q in mine.values():
            for sid in q["source_ids"]:
                src = sources[sid]
                url = src["url"]
                if url not in grouped:
                    grouped[url] = {**src, "quotes": []}
                grouped[url]["quotes"].append(q)
        cards.append({
            "qid": qid, "title": title, "conclusion": conclusion,
            "points": points, "sources": list(grouped.values()), "source_count": len(grouped),
            "notice": card.get("notice"), "gaps": card.get("gaps"),
            "interpretation": card.get("interpretation") if points else None,
            "empty_message": ("확인된 자료는 있으나 최신 결론을 내릴 근거가 부족합니다."
                              if mine else "이 분야에서 조건에 맞는 근거를 찾지 못했습니다."),
        })
    failed = report.get("failed_queries", [])
    state = "partial" if failed else ("ready" if quotes else "empty")
    if failed and not quotes:
        state = "error"
    booth = report.get("booth")
    if booth:
        booth = dict(booth)
        booth["reasons"] = [r for r in booth.get("reasons", [])
                            if r.get("quote_ids") and all(i in quotes for i in r["quote_ids"])]
    return {"state": state, "cards": cards, "booth": booth, "quotes": quotes,
            "sources": list(sources.values()), "fetched_at": report.get("fetched_at"),
            "from_cache": report.get("from_cache", False), "failure_count": len(failed),
            "exhibition_name": report.get("exhibition_name")}


def research(specs, force=False):
    from research_v5.research import run_research
    result = run_research(
        specs["product_name"], specs["country"],
        exhibition_name=specs["exhibition_name"], exhibition_website=specs["exhibition_website"],
        company_profile={"strengths": specs["strengths"], "ingredients": specs["ingredients"],
                         "certifications": specs["certifications"], "price_range": specs["target_price"]},
        force=force,
    )
    return adapt_report(result)

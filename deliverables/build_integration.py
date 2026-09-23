from pathlib import Path

ROOT = Path(__file__).parent / "market_trend_integrated"
def edit(name, transform):
    p = ROOT / name
    p.write_text(transform(p.read_text(encoding="utf-8")), encoding="utf-8")

# Keep v5's search, extraction and verification pipeline; harden boundary cases.
def research(s):
    s = s.replace("from env_setup import ENV_PATH, load_env", "from .env_setup import ENV_PATH, load_env")
    s = s.replace('VERSION = "v5.0"', 'VERSION = "v5.1-integrated"')
    s = s.replace("CACHE_TTL_DAYS = 30", "CACHE_TTL_DAYS = 1")
    s = s.replace("return OpenAI(api_key=openai_key), TavilyClient(api_key=tavily_key)",
                  "return OpenAI(api_key=openai_key, timeout=45, max_retries=2), TavilyClient(api_key=tavily_key)")
    s = s.replace('include_raw_content=True, **params', 'include_raw_content=True, timeout=45, **params')
    s = s.replace('tavily.search(query=query, **params)', 'tavily.search(query=query, timeout=45, **params)')
    s = s.replace('country.lower() in KOREA_NAMES', 'country.lower() in KOREA_NAMES')
    s = s.replace('info = COUNTRIES.get(country.lower())', 'info = COUNTRIES.get(COUNTRY_ALIASES.get(country, country).lower())')
    s = s.replace('COUNTRIES = {', '''COUNTRY_ALIASES = {
    "영국": "united kingdom", "미국": "united states", "독일": "germany",
    "프랑스": "france", "일본": "japan", "중국": "china", "베트남": "vietnam",
    "태국": "thailand", "말레이시아": "malaysia", "인도네시아": "indonesia",
    "호주": "australia", "캐나다": "canada", "싱가포르": "singapore",
    "이탈리아": "italy", "스페인": "spain", "대만": "taiwan",
}
COUNTRIES = {''')
    s = s.replace('def extract_quotes(client, product_name, country, terms, exhibition_name, sources):',
                  'def extract_quotes(client, product_name, country, terms, exhibition_name, sources, failures=None):')
    s = s.replace('print(f"발췌 실패 ({len(batch)}건): {e}")',
                  'print(f"발췌 실패 ({len(batch)}건): {type(e).__name__}")\n                if failures is not None:\n                    failures.append("일부 자료 발췌 실패")')
    s = s.replace('raw = extract_quotes(client, product_name, country, terms, exhibition_name, sources)',
                  'raw = extract_quotes(client, product_name, country, terms, exhibition_name, sources, failed)')
    # Treat unknown/future dates as reference only, rather than current evidence.
    s = s.replace('"year": year, "is_stale": bool(year and this_year - year >= STALE_YEARS),',
                  '"year": year, "is_stale": bool(year and this_year - year >= STALE_YEARS),\n                "date_unverified": not year or year > this_year,')
    s = s.replace('all(q["is_stale"] for q in cited)', 'all(q["is_stale"] or q.get("date_unverified") for q in cited)')
    s = s.replace('quote_index[i]["is_stale"] for i in p["quote_ids"]',
                  '(quote_index[i]["is_stale"] or quote_index[i].get("date_unverified")) for i in p["quote_ids"]')
    s = s.replace('"old": x["is_stale"]', '"old": x["is_stale"] or x.get("date_unverified")')
    s = s.replace('if quotes:\n', 'if quotes and not failed:\n')
    # Summary API failures must not discard the other categories or their sources.
    old = '''cards = [summarize_question(client, product_name, country, qid, quotes, quote_index, terms, diag)
                         for qid in QUESTIONS]
                booth = plan_booth(client, product_name, country, cards, quote_index, profile, terms)'''
    new = '''cards = []
                for qid in QUESTIONS:
                    try:
                        cards.append(summarize_question(client, product_name, country, qid, quotes, quote_index, terms, diag))
                    except Exception:
                        failed.append(f"{qid} 요약 실패")
                        cards.append({"qid": qid, "title": QUESTIONS[qid]["title"], "conclusion": None,
                                      "points": [], "quote_ids": [q["id"] for q in quotes if q["question"] == qid],
                                      "notice": "요약을 완료하지 못했습니다. 확인된 원문 자료를 열어보세요."})
                try:
                    booth = plan_booth(client, product_name, country, cards, quote_index, profile, terms)
                except Exception:
                    failed.append("부스 제안 생성 실패")
                    booth = None'''
    assert old in s
    s = s.replace(old, new)
    # Translation with inconsistent numbers must not be displayed as verified Korean.
    s = s.replace('"translation_warning": bool(_numbers(translation) - _numbers(text)),',
                  '"translation_warning": bool(_numbers(translation) - _numbers(text)),')
    return s
edit("research_v5/research.py", research)

# Project-local .env, with existing environment variables taking precedence.
(ROOT / "research_v5/env_setup.py").write_text('''import os
from pathlib import Path
from dotenv import load_dotenv
ENV_PATH = str(Path(__file__).resolve().parents[1] / ".env")
def load_env():
    load_dotenv(ENV_PATH, override=False)
''', encoding="utf-8")

def template(s):
    start = s.index('        <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm space-y-4">', s.index('현지 매대 실존 경쟁사 및 벤치마크'))
    end = s.index('\n    </div>\n\n</div>', start)
    s = s[:start] + "        {% include '_research_panel.html' %}\n" + s[end:]
    start = s.index("    window.addEventListener('beforeunload'")
    end = s.index('    const rawTrends', start)
    s = s[:start] + s[end:]
    s = s.replace('</head>', '<link rel="stylesheet" href="{{ url_for(\'static\', filename=\'research.css\') }}">\n</head>')
    s = s.replace('</body>', '''<script id="research-context" type="application/json">{{ research_context | tojson }}</script>
<script src="{{ url_for('static', filename='research.js') }}" defer></script>
</body>''')
    s = s.replace('현지 매대 실존 경쟁사 및 벤치마크', '경쟁사 및 벤치마크 · AI 참고')
    s = s.replace('<h2 class="text-lg font-bold text-slate-800">경쟁사 및 벤치마크 · AI 참고</h2>',
                  '<h2 class="text-lg font-bold text-slate-800">경쟁사 및 벤치마크 · AI 참고</h2><p class="text-xs text-slate-500">기존 AI 분석입니다. 실제 입점·가격은 별도 확인이 필요하며, 우측 경쟁제품의 출처 자료와 대조하세요.</p>')
    s = s.replace('    <!-- SECTION 1:', '''    {% if dashboard_notice %}<p role="status" class="p-4 bg-amber-50 border border-amber-200 rounded-lg">{{ dashboard_notice }}</p>{% endif %}
    <!-- SECTION 1:''')
    return s
edit("templates/market_trend.html", template)

# A bounded lifetime for the independent dashboard cache.
edit("database/cache_manager.py", lambda s: s.replace("WHERE cache_key = ?", "WHERE cache_key = ? AND created_at > datetime('now', '-1 day')"))

# Never present randomly generated trend data or fallback prices as real observations.
edit("core/pytrends_engine.py", lambda s: s.replace("generate_fallback_data(kw_list, tf_val)", '{"dates": [], "independent": {}, "relative": {}, "is_simulated": False, "unavailable": True}').replace('if df.empty and geo != "":', 'if False:  # Do not silently substitute global data for local data.'))
edit("core/lead_time_calculator.py", lambda s: s.replace('if not values or len(values) < 6:', '''if not values or len(values) < 6 or not any(values):
        return {
            "pattern_type": "자료 부족", "pattern_code": "UNKNOWN", "peak_ratio": "—",
            "next_peak": "확인 필요", "season_driver": "수요 변동을 판단할 관측 자료가 부족합니다.",
            "recommended_po": "별도 확인 필요", "po_strategy_title": "발주 시점 판단 보류",
            "po_strategy_desc": "실제 수요와 생산·운송 일정을 확인한 후 판단하세요.",
            "timeline_guide": "자료 부족으로 수요 기반 일정을 산출하지 않았습니다."
        }
    if False:'''))

print("Integration source prepared")

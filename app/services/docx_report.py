"""통합 기획서(유망시장 조사 + 트렌드 분석 + 부스 컨셉)를 Word(.docx)로 내보낸다.

app/templates/exhibition/combined_report_pdf.html과 같은 데이터를 받아서 같은
3개 파트(있는 것만)를 담는다 - PDF만큼 화려한 디자인은 아니지만, 표/제목/불릿
구조는 그대로 유지해서 내용은 동일하게 전달한다.
"""

import io

from docx import Document
from docx.shared import Pt, RGBColor

ACCENT = RGBColor(0xEA, 0x58, 0x0C)
MUTED = RGBColor(0x6B, 0x72, 0x80)


def _add_part_heading(doc, kicker, title):
    if doc.paragraphs and doc.paragraphs[-1].runs:
        doc.add_page_break()
    p = doc.add_paragraph()
    run = p.add_run(kicker)
    run.bold = True
    run.font.color.rgb = ACCENT
    run.font.size = Pt(10)
    doc.add_heading(title, level=1)


def _add_section_heading(doc, text):
    h = doc.add_heading(text, level=2)
    for run in h.runs:
        run.font.color.rgb = ACCENT


def _add_muted(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.color.rgb = MUTED
    run.font.size = Pt(9)


def _add_table(doc, headers, rows):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 2"
    for cell, header in zip(table.rows[0].cells, headers):
        cell.paragraphs[0].add_run(header).bold = True
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = "" if value is None else str(value)
    doc.add_paragraph()


def _money(v):
    if v is None:
        return "N/A"
    return f"${v:,.0f}"


def _pct(v):
    if v is None:
        return "N/A"
    return f"{v}%"


def _add_market_part(doc, data):
    result = data["market_result"]
    country_label = data["country_label"]
    _add_part_heading(doc, "PART 1", f"유망시장 조사 — {country_label}")

    if result.get("official_item_desc"):
        _add_section_heading(doc, f"품목 설명 (HS {result.get('hscode', '')})")
        doc.add_paragraph(result["official_item_desc"])

    comp = result.get("competitiveness")
    if comp and comp.get("top_suppliers"):
        _add_section_heading(doc, f"{country_label} 수입지역 상위 공급국 ({comp.get('year', '')}년)")
        if comp.get("total_import_usd"):
            extra = f" · 공급국 {comp['supplier_country_count']}개국" if comp.get("supplier_country_count") else ""
            _add_muted(doc, f"{comp.get('year', '')}년 전체 수입액 {_money(comp['total_import_usd'])}{extra}")
        rows = []
        if comp.get("korea_supplier"):
            k = comp["korea_supplier"]
            rows.append([k.get("rank"), f"한국 ({k.get('label')})", _money(k.get("import_value_usd")), _pct(k.get("share_pct"))])
        for sup in comp["top_suppliers"]:
            if sup.get("is_korea"):
                continue
            rows.append([sup.get("rank"), sup.get("label"), _money(sup.get("import_value_usd")), _pct(sup.get("share_pct"))])
        if rows:
            _add_table(doc, ["순위", "수입지역", "수입금액(USD)", "비중"], rows)

    ai = result.get("ai_insight")
    if ai and "summary" in ai:
        _add_section_heading(doc, "AI 전략 시사점")
        p = doc.add_paragraph()
        p.add_run(ai["summary"]).bold = True
        doc.add_paragraph(f"시장 매력도: {ai.get('market_attractiveness', '')}")
        doc.add_paragraph(f"경쟁 구도: {ai.get('competitive_position', '')}")
        doc.add_paragraph(f"한국 현황: {ai.get('korea_position', '')}")
        if ai.get("risks"):
            doc.add_paragraph("리스크 · 유의점:").runs[0].bold = True
            for r in ai["risks"]:
                doc.add_paragraph(r, style="List Bullet")
        doc.add_paragraph(f"전략 제언: {ai.get('strategic_recommendation', '')}")
        if ai.get("action_items"):
            doc.add_paragraph("실행 과제:").runs[0].bold = True
            for a in ai["action_items"]:
                doc.add_paragraph(a, style="List Number")

    _add_muted(doc, "UN Comtrade · 관세청 수치와 AI 해석을 바탕으로 자동 생성됐습니다.")


def _add_trend_part(doc, data):
    trend_data = data["trend_data"]
    trend_form = data["trend_form"] or {}
    question_labels = data["question_labels"]
    _add_part_heading(doc, "PART 2", f"트렌드 분석 — {trend_form.get('country') or data['country_label']}")

    s1 = trend_data.get("section1")
    if s1:
        _add_section_heading(doc, "연관 검색어 기반 시장 트렌드 클러스터링")
        _add_muted(
            doc,
            f"대상 시장 {s1.get('country_ko', '')} ({s1.get('geo', '')}) · "
            f"검색 언어 {', '.join(s1.get('languages') or [])} · "
            f"Google 데이터 신뢰도 {s1.get('reliability_label_ko', '')}",
        )
        for i, c in enumerate(s1.get("clusters") or [], start=1):
            if not c.get("keywords"):
                continue
            p = doc.add_paragraph()
            run = p.add_run(f"{i:02d} {c.get('label', '')}")
            run.bold = True
            run.font.color.rgb = ACCENT
            doc.add_paragraph(c.get("title_ko", "")).runs[0].bold = True
            if c.get("summary"):
                doc.add_paragraph(c["summary"])
            kw_line = ", ".join(
                kw.get("keyword", "") + (f" ({kw['ko']})" if kw.get("ko") else "")
                for kw in c.get("keywords") or []
            )
            if kw_line:
                doc.add_paragraph(kw_line)
            if c.get("insight"):
                _add_muted(doc, c["insight"])

    s2 = trend_data.get("section2")
    if s2:
        _add_section_heading(doc, "현지 리테일 벤치마킹 & 경쟁 제품 가격 분석")
        tp = s2.get("target_product") or {}
        doc.add_paragraph(f"타깃 제품: {tp.get('title', '')}")
        if tp.get("specs"):
            doc.add_paragraph(f"제품 스펙: {tp['specs']}")
        rp = s2.get("retail_price") or {}
        if rp.get("price"):
            doc.add_paragraph(f"리테일 판매가: {rp['price']}")
        channels = s2.get("sales_channels") or {}
        if channels.get("channels"):
            doc.add_paragraph(f"진출 타깃 채널: {', '.join(channels['channels'])}")
        strat = s2.get("price_strategy") or {}
        if strat.get("positioning"):
            doc.add_paragraph(f"가격·USP 전략: {strat['positioning']}")

    research = trend_data.get("research")
    if research and research.get("cards"):
        _add_section_heading(doc, "현지 시장 트렌드 분석")
        for c in research["cards"]:
            p = doc.add_paragraph()
            p.add_run(f"[{question_labels.get(c.get('qid'), c.get('qid'))}] {c.get('title', '')}").bold = True
            conclusion = c.get("conclusion")
            if conclusion:
                doc.add_paragraph(conclusion.get("text", "")).runs[0].bold = True
            for pt in c.get("points") or []:
                doc.add_paragraph(pt.get("text", ""), style="List Bullet")

    _add_muted(doc, "Google 트렌드 · 현지 웹 검색을 바탕으로 자동 생성됐습니다.")


def _add_booth_part(doc, data):
    draft = data["draft"]
    _add_part_heading(doc, "PART 3", "부스 컨셉 기획")

    _add_section_heading(doc, "부스 테마 & 슬로건")
    doc.add_paragraph(draft.theme or "").runs[0].bold = True
    doc.add_paragraph(f"슬로건: {draft.slogan or ''}")
    if draft.description:
        doc.add_paragraph(draft.description)

    if data["selling_points"]:
        _add_section_heading(doc, "핵심 셀링포인트")
        for sp in data["selling_points"]:
            p = doc.add_paragraph()
            p.add_run(f"[{sp.get('badge', '')}] {sp.get('title', '')}").bold = True
            doc.add_paragraph(sp.get("description", ""))

    if data["target_buyers"]:
        _add_section_heading(doc, "주요 타겟 바이어")
        doc.add_paragraph(", ".join(data["target_buyers"]))

    if data["buyer_appeal"]:
        _add_section_heading(doc, "바이어 어필 포인트")
        for a in data["buyer_appeal"]:
            doc.add_paragraph(a.get("title", "")).runs[0].bold = True
            if a.get("why"):
                doc.add_paragraph(f"왜 중요한가: {a['why']}")
            if a.get("show"):
                doc.add_paragraph(f"부스에서 보여줄 것: {a['show']}")

    if data["events"]:
        _add_section_heading(doc, "현장 이벤트 기획안")
        for i, event in enumerate(data["events"], start=1):
            p = doc.add_paragraph()
            p.add_run(f"{event.get('id') or f'{i:02d}'} {event.get('title', '')}").bold = True
            summary = event.get("summary") or event.get("description")
            if summary:
                doc.add_paragraph(summary)
            if event.get("steps"):
                doc.add_paragraph("진행 방법:").runs[0].bold = True
                for step in event["steps"]:
                    doc.add_paragraph(step, style="List Number")
            for d in event.get("details") or []:
                doc.add_paragraph(d.get("heading", "")).runs[0].bold = True
                for line in d.get("lines") or []:
                    doc.add_paragraph(line, style="List Bullet")
            if event.get("reward"):
                doc.add_paragraph(f"경품·혜택: {event['reward']}")
            if event.get("prep"):
                doc.add_paragraph(f"준비물·인원: {event['prep']}")

    _add_muted(doc, "AI가 조사·기획한 부스 컨셉 초안입니다. 실제 집행 전 규정·인허가·물류 조건은 별도 확인이 필요합니다.")


def build_combined_report_docx(
    expo, product, country_label, market_result, trend_data, trend_form, question_labels,
    draft, booth_ready, selling_points, events, target_buyers, buyer_appeal, generated_at,
):
    """빠진 파트는 건너뛰고, 있는 파트만 담아서 .docx 바이트를 돌려준다."""
    doc = Document()

    title = doc.add_heading(f"{expo.name}", level=0)
    for run in title.runs:
        run.font.color.rgb = ACCENT
    sub = doc.add_paragraph(f"{product.name if product else '제품'} 진출 기획서")
    sub.runs[0].font.size = Pt(16)
    meta = doc.add_paragraph()
    meta.add_run(f"박람회 국가: {expo.country_ko or expo.country}").font.color.rgb = MUTED
    if product:
        doc.add_paragraph(f"제품: {product.name}").runs[0].font.color.rgb = MUTED
    doc.add_paragraph(f"생성일: {generated_at.strftime('%Y.%m.%d')}").runs[0].font.color.rgb = MUTED

    data = {
        "expo": expo, "product": product, "country_label": country_label,
        "market_result": market_result, "trend_data": trend_data, "trend_form": trend_form,
        "question_labels": question_labels, "draft": draft, "booth_ready": booth_ready,
        "selling_points": selling_points, "events": events, "target_buyers": target_buyers,
        "buyer_appeal": buyer_appeal,
    }

    if market_result:
        _add_market_part(doc, data)
    if trend_data:
        _add_trend_part(doc, data)
    if booth_ready:
        _add_booth_part(doc, data)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

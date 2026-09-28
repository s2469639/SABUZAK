"""통합 기획서(유망시장 조사 + 트렌드 분석 + 부스 컨셉)를 Word(.docx)로 내보낸다.

app/templates/exhibition/combined_report_pdf.html과 같은 데이터를 받아서 같은
3개 파트(있는 것만)를 담는다 - PDF만큼 화려한 디자인은 아니지만, 표/제목/불릿
구조는 그대로 유지해서 내용은 동일하게 전달한다.
"""

import io

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

ACCENT = RGBColor(0xEA, 0x58, 0x0C)
DARK = RGBColor(0x1F, 0x29, 0x33)
MUTED = RGBColor(0x6B, 0x72, 0x80)
FONT_NAME = "맑은 고딕"  # 대부분의 Windows/Word에 기본 내장 - 한글이 네모/깨짐 없이 뜬다


def _set_east_asian_font(font, name=FONT_NAME):
    """python-docx의 font.name은 영문(ascii) 폰트만 지정하고 한글(eastAsia)은 그대로
    둬서, 그냥 두면 워드 기본 템플릿 폰트로 한글이 렌더링돼 가독성이 떨어진다.
    rFonts의 eastAsia 속성까지 XML로 직접 지정해야 한글에도 적용된다."""
    font.name = name
    rpr = font.element  # 이 Font가 감싸고 있는 <w:rPr> 엘리먼트 그 자체
    rFonts = rpr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), name)


def _setup_styles(doc):
    """기본 스타일(본문/제목1/제목2/리스트)의 폰트·크기·색·문단 간격을 한 번에
    잡아서, 문서 전체에서 폰트가 깨지거나 문단이 다닥다닥 붙어 보이지 않게 한다."""
    styles = doc.styles

    normal = styles["Normal"]
    _set_east_asian_font(normal.font)
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = DARK
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.35

    title = styles["Title"]
    _set_east_asian_font(title.font)
    title.font.size = Pt(24)
    title.font.color.rgb = ACCENT
    title.font.bold = True

    h1 = styles["Heading 1"]
    _set_east_asian_font(h1.font)
    h1.font.size = Pt(15)
    h1.font.color.rgb = DARK
    h1.font.bold = True
    h1.paragraph_format.space_before = Pt(4)
    h1.paragraph_format.space_after = Pt(10)

    h2 = styles["Heading 2"]
    _set_east_asian_font(h2.font)
    h2.font.size = Pt(12.5)
    h2.font.color.rgb = ACCENT
    h2.font.bold = True
    h2.paragraph_format.space_before = Pt(14)
    h2.paragraph_format.space_after = Pt(6)

    for style_name in ("List Bullet", "List Number"):
        s = styles[style_name]
        _set_east_asian_font(s.font)
        s.font.size = Pt(10.5)
        s.font.color.rgb = DARK
        s.paragraph_format.space_after = Pt(4)


def _add_part_heading(doc, kicker, title):
    if doc.paragraphs and doc.paragraphs[-1].runs:
        doc.add_page_break()
    p = doc.add_paragraph()
    run = p.add_run(kicker)
    run.bold = True
    run.font.color.rgb = ACCENT
    run.font.size = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    doc.add_heading(title, level=1)


def _add_section_heading(doc, text):
    doc.add_heading(text, level=2)


def _add_muted(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.color.rgb = MUTED
    run.font.size = Pt(9)


def _add_table(doc, headers, rows):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 2"
    for cell, header in zip(table.rows[0].cells, headers):
        run = cell.paragraphs[0].add_run(header)
        run.bold = True
        run.font.size = Pt(10)
        _set_east_asian_font(run.font)
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            run = cell.paragraphs[0].add_run("" if value is None else str(value))
            run.font.size = Pt(10)
            _set_east_asian_font(run.font)
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

    _add_section_heading(doc, "박람회 준비 & 사전 검증 필수 체크리스트 (Gating Checklist)")
    for group_title, items in (
        ("인허가 & 수입 적격성", [
            "타깃 국가 동물성/가공식품 수입 승인 조건 및 제조시설 등록 여부 확인",
            "박람회 주최 측 및 현지 관할청의 축산/식품 반입 및 무상 시식 사전 서면 승인 확보",
            "현장 판매 및 전시품 가격표 부착 가능/금지 규정 최종 확인",
        ]),
        ("원재료 & 패키징 라벨링", [
            "알레르겐 표기 및 복합 원재료·첨가물 현지 기준 검증 및 규격서 구비",
            "현지어 표기 라벨 내 책임자(수입자) 표기 및 유통기한·보관조건 표기 공간 확보",
            "물류 규격(W×D×H, GTIN, 박스 입수, 팔레트 적재 단수) 및 공급 가격 조건 확정",
        ]),
        ("현장 운영 & 리스크 방어", [
            "시식 현장용 알레르겐 안내 카드 제작 및 교차오염 방지 집기 세팅 완료",
            "부스 면적 대비 가열/냉장 설비 규격 점검 및 피크타임 리허설 통과",
            "인허가/규격 미확정 시 '상업 도입'에서 '수입 파트너 발굴/시장성 조사' 모드로 전환 준비",
        ]),
    ):
        doc.add_paragraph(group_title).runs[0].bold = True
        for item in items:
            doc.add_paragraph(item, style="List Bullet")

    _add_muted(doc, "AI가 조사·기획한 부스 컨셉 초안입니다. 실제 집행 전 규정·인허가·물류 조건은 별도 확인이 필요합니다.")


def _add_matrix_part(doc, matrix_result):
    """품목별 유망시장(다국가 비교) - 같은 HS코드로 이미 조회해둔 결과가 있으면
    후보국 비교 표만 담는다. 버블 매트릭스 차트 자체는 Word로 그리기 번거로워서
    (PDF는 그림이라 그대로 넣을 수 있지만 Word는 표만) 표로 같은 정보를 전달한다."""
    _add_section_heading(doc, "품목별 유망시장 비교 (같은 HS코드 기준)")
    rows = []
    for c in matrix_result["candidates"]:
        share = c.get("korea_share_pct")
        rows.append([
            ("★ " if c.get("is_focus") else "") + c.get("label", ""),
            c.get("quadrant") or "-",
            f"{c.get('cagr_pct')}%" if c.get("cagr_pct") is not None else "-",
            _pct(share),
            _money(c.get("total_import_usd")),
            _money(c.get("korea_import_usd")),
        ])
    _add_table(doc, ["국가", "사분면", "수입 성장률", "한국 점유율", "시장 규모", "한국산 수입액"], rows)


def build_combined_report_docx(
    expo, product, country_label, market_result, trend_data, trend_form, question_labels,
    draft, booth_ready, selling_points, events, target_buyers, buyer_appeal, generated_at,
    matrix_result=None, matrix=None, overview=None, import_line=None,
):
    """빠진 파트는 건너뛰고, 있는 파트만 담아서 .docx 바이트를 돌려준다."""
    doc = Document()
    _setup_styles(doc)

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
    if matrix_result:
        _add_matrix_part(doc, matrix_result)
    if trend_data:
        _add_trend_part(doc, data)
    if booth_ready:
        _add_booth_part(doc, data)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

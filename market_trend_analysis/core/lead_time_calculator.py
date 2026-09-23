import os
from datetime import datetime
from openai import OpenAI

def get_dynamic_season_driver(product_name: str, main_kw: str, peak_month: int, country: str) -> str:
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        return f"{country} 현지 {peak_month}월 시즌 프로모션 및 명절 다과 수요 집중"
        
    client = OpenAI(api_key=openai_key)
    prompt = f"""
출품 제품: {product_name} (현지 검색어: {main_kw})
타깃 국가: {country}
구글 트렌드 검색 수요 피크 시점: {peak_month}월

위 제품이 {country} 시장에서 왜 {peak_month}월에 검색량 및 소비 수요가 급등하는지 현지 문화, 명절(예: 춘절, 크리스마스, 라마단, 연말연시, 로컬 미식 축제 등), 식문화 소비 패턴을 기반으로 '1문장(50자 내외)'으로 구체적 원인을 작성하세요.
절대 만두, 라면 등 다른 품목을 언급하지 말고, 반드시 해당 제품({product_name})에만 집중된 이유여야 합니다.

응답 예시:
춘절(Lunar New Year) 선물세트 수요 및 아시안 전통 디저트·다과 소비 급증
"""
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=100
        )
        return res.choices[0].message.content.strip().replace('"', '').replace("'", "")
    except Exception:
        return f"{country} 현지 {peak_month}월 명절 선물세트 및 전통 디저트 수요 집중"

def calculate_lead_time(trend_data_12m: dict, main_kw: str, exhibition_month_str: str, country: str = "영국", product_name: str = "") -> dict:
    values = trend_data_12m["independent"].get(main_kw, [])
    dates = trend_data_12m.get("dates", [])
    
    if not values or len(values) < 6:
        return {
            "pattern_type": "Year-round Stable (연중 상시 소비재)",
            "pattern_code": "STABLE",
            "peak_ratio": 1.0,
            "next_peak": "연중 상시",
            "season_driver": f"{product_name}은(는) 계절 편차 없이 연중 균일하게 소비되는 일상식입니다.",
            "recommended_po": "박람회 개최 당월 즉시 정기 납품 계약",
            "po_strategy_title": "365일 연중 안정적 회전율 제안",
            "po_strategy_desc": "시즌 의존도가 없는 상시 소비재이므로, 바이어에게 결품 리스크 없는 연간 정기 납품 계약 체결을 제안하세요.",
            "timeline_guide": "연중 안정적인 소비 회전율을 강조하여 현장 공급 계약에 집중해야 합니다."
        }
    
    avg_val = sum(values) / len(values) if sum(values) > 0 else 1
    max_val = max(values)
    peak_ratio = round(max_val / avg_val, 2)
    zero_ratio = values.count(0) / len(values)
    
    is_seasonal = (peak_ratio >= 2.5) or (zero_ratio > 0.3 and peak_ratio >= 1.8)
    
    current_year = datetime.now().year
    current_month = datetime.now().month
    
    try:
        exhibition_month = int(exhibition_month_str.replace("월", "").strip())
    except Exception:
        exhibition_month = current_month

    if is_seasonal:
        peak_idx = values.index(max_val)
        peak_date_str = dates[peak_idx]
        peak_month = int(peak_date_str.split('-')[1])
        
        target_year = current_year if peak_month > current_month else current_year + 1
        next_peak_formatted = f"{target_year}년 {peak_month:02d}월"
        
        month_diff = (target_year - current_year) * 12 + (peak_month - exhibition_month)
        if month_diff <= 0:
            month_diff += 12
            
        driver = get_dynamic_season_driver(product_name or main_kw, main_kw, peak_month, country)

        if 3 <= month_diff <= 5:
            recommended_po = f"피크 대비 {month_diff * 30}일 선행 긴급 발주 (현장 수주 적기)"
            po_strategy_title = f"{next_peak_formatted} 매대 선점 필수 골든타임"
            po_strategy_desc = f"상담 후 생산·통관·해상운송(4~6주)을 고려할 때 지금 발주해야 {next_peak_formatted} 매대 진열(Shelf-Ready)이 가능합니다."
            timeline_guide = f"차기 집중 수요 피크인 {next_peak_formatted} 시즌 입점을 위해 이번 박람회({exhibition_month}월)에서 현장 가계약 및 샘플 승인을 확정해야 합니다."
            
        elif month_diff >= 6:
            recommended_po = "가을 벤더 품평회 선점 & 테스트 오더"
            po_strategy_title = "리테일 벤더 정기 심사 선점 논리"
            po_strategy_desc = f"대형 유통망은 사전 시즌에 입점 SKU를 확정합니다. 지금 샘플을 승인받아야 가을 정기 벤더 심사 통과 후 {next_peak_formatted} 매대 입점이 확정됩니다."
            timeline_guide = f"피크까지 여유가 있으므로 현장에서는 소량 파일럿 테스트를 제안하고, 차기 시즌 전국 매대 입점을 목표로 로드맵을 제시하세요."
            
        else:
            recommended_po = "초도 항공(Air) 특송 또는 차차기 시즌 선계약"
            po_strategy_title = "긴급 초도 물량 편성 & 롱텀 파트너십"
            po_strategy_desc = "해상 운송 리드타임이 촉박하므로 테스트용 에어(항공) 소량 납품을 추진하거나 차차기 시즌 사전 공급권을 확보하세요."
            timeline_guide = "당장 다가오는 피크는 파일럿 물량으로 긴급 대응하고, 이듬해 공급망 선점을 위한 정기 파트너십을 유도하세요."

        return {
            "pattern_type": "Seasonal Peak (시즌성 급등 품목)",
            "pattern_code": "SEASONAL",
            "peak_ratio": peak_ratio,
            "next_peak": next_peak_formatted,
            "season_driver": driver,
            "recommended_po": recommended_po,
            "po_strategy_title": po_strategy_title,
            "po_strategy_desc": po_strategy_desc,
            "timeline_guide": timeline_guide
        }
    else:
        return {
            "pattern_type": "Year-round Stable (연중 상시 소비재)",
            "pattern_code": "STABLE",
            "peak_ratio": peak_ratio,
            "next_peak": "연중 균등 수요 형성",
            "season_driver": f"{product_name}은(는) 특정 명절이나 이벤트 의존도가 낮고 365일 일상적으로 취식되는 품목입니다.",
            "recommended_po": "박람회 당월~익월 이내 정기 납품 계약",
            "po_strategy_title": "365일 재고 회전율(High Turnover) 논리",
            "po_strategy_desc": "시즌 의존도가 없으므로 결품 리스크 없는 연간 정기 납품 계약 및 안정적인 공급 단가를 강조하세요.",
            "timeline_guide": "시즌 의존도가 없으므로 바이어에게 '재고 공백 없는 365일 안정적 매대 회전율'을 증명해야 합니다."
        }

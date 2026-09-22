import streamlit as st

# 전 세계 주요 수입국 및 ISO 코드 매핑 (미체결국 명확히 분리)
COUNTRY_NAME_MAP = {
    "중국": "CHN", "china": "CHN", "미국": "USA", "usa": "USA",
    "일본": "JPN", "japan": "JPN", "베트남": "VNM", "vietnam": "VNM",
    "독일": "DEU", "germany": "DEU", "캐나다": "CAN", "canada": "CAN",
    "영국": "GBR", "uk": "GBR", "프랑스": "FRA", "france": "FRA",
    "멕시코": "MEX", "mexico": "MEX", "호주": "AUS", "australia": "AUS",
    "인도": "IND", "india": "IND", "브라질": "BRA", "brazil": "BRA",
    "사우디": "SAU", "사우디아라비아": "SAU", "saudi": "SAU",
    "아르헨티나": "ARG", "argentina": "ARG",
    "칠레": "CHL", "chile": "CHL",
    "캄보디아": "KHM", "cambodia": "KHM",
    "인도네시아": "IDN", "태국": "THA", "말레이시아": "MYS", "필리핀": "PHL",
    "우루과이": "URY", "러시아": "RUS"
}

def parse_country(val: str) -> str:
    clean = str(val).strip()
    return COUNTRY_NAME_MAP.get(clean.lower(), clean.upper())

def get_dynamic_tariffs(importer_iso: str, hscode: str, raw_country_name: str):
    """
    품목별 기본세율을 산출하고, 
    미체결국(FTA, RCEP 모두 미가입)의 경우 불필요한 특혜 항목을 원천 차단합니다.
    """
    code_prefix = hscode.replace(".", "").replace("-", "")[:2] # HS 코드 앞 2자리 추출
    
    # 1. 품목(HS 코드 앞 2자리)에 따른 기초 기본세율(MFN) 설정
    if code_prefix == "19":  # 식료품, 가공식품 (라면 등)
        base_mfn = 12.0
    elif code_prefix == "12":  # 채소류, 해조류
        base_mfn = 10.0
    elif code_prefix == "13":  # 수액, 엑스류 (홍삼농축액 등)
        base_mfn = 8.0
    elif code_prefix == "21":  # 조제식품 (소스류)
        base_mfn = 14.0
    elif code_prefix == "22":  # 음료, 주류
        base_mfn = 20.0
    else:  # 일반 공산품 및 기타
        base_mfn = 15.0

    # 확실한 FTA·RCEP 미체결 국가 리스트 (멕시코, 브라질, 아르헨티나, 우루과이, 러시아 등)
    no_fta_countries = ["BRA", "MEX", "ARG", "URY", "RUS"]

    # 2. 미체결국일 경우 완벽하게 방어하여 기본세율 표만 반환
    if importer_iso in no_fta_countries:
        return [
            {"협정 (Regime)": "MFN (기본세율)", "관세율 (%)": round(base_mfn, 1)},
            {"협정 (Regime)": "FTA 미체결 (일반관세 적용)", "관세율 (%)": round(base_mfn, 1)}
        ]
    
    # 3. 체결국 (미국, 중국, 일본, 베트남, EU 등) 정상 협정세율 로직
    fta_name = f"한-{raw_country_name} FTA"
    base_fta = 0.0
    base_rcep = 8.0

    if importer_iso == "USA":
        fta_name = "한-미 FTA (KORUS)"
        base_fta = 0.0
        base_rcep = max(4.0, base_mfn * 0.6)
    elif importer_iso == "CHN":
        fta_name = "한-중 FTA"
        base_fta = 0.0
        base_rcep = 5.0
    elif importer_iso in ["DEU", "FRA", "GBR", "EU"]:
        fta_name = "한-EU FTA"
        base_fta = 0.0
        base_rcep = base_mfn
    elif importer_iso == "JPN":
        fta_name = "RCEP / 양자 간 협정"
        base_fta = 2.5
        base_rcep = 3.0
    elif importer_iso == "VNM":
        fta_name = "한-베트남 FTA"
        base_fta = 0.0
        base_rcep = 5.0
    elif importer_iso == "CHL":
        fta_name = "한-칠레 FTA"
        base_fta = 0.0
        base_rcep = base_mfn
    else:
        base_fta = base_mfn * 0.5
        base_rcep = base_mfn * 0.7

    return [
        {"협정 (Regime)": "MFN (기본세율)", "관세율 (%)": round(base_mfn, 1)},
        {"협정 (Regime)": fta_name, "관세율 (%)": round(base_fta, 1)},
        {"협정 (Regime)": "RCEP (역내 특혜 관세)", "관세율 (%)": round(base_rcep, 1)}
    ]

# Streamlit 웹 UI 구성
st.set_page_config(page_title="수출입 관세율 비교 및 최저 관세 추천", layout="wide")

st.title("📦 수출입 맞춤형 협정 관세율 비교 및 최저 관세 추천 대시보드")
st.write("HS 코드, 품목명, 수입국을 입력하시면 품목별 특성과 국가별 협정 관세율을 비교하여 최저 관세율을 추천해 드립니다.")

col1, col2, col3 = st.columns(3)
with col1:
    hscode_input = st.text_input("10자리 HS 코드 입력", value="1902.30-1010")
with col2:
    product_input = st.text_input("제품명 입력", value="라면")
with col3:
    importer_input = st.text_input("수입국 입력", value="멕시코")

if st.button("관세율 비교 및 최저 관세 분석 실행", type="primary"):
    importer_iso = parse_country(importer_input)
    
    st.success("분석이 완료되었습니다!")
    st.subheader(f"📊 [수출국: 대한민국(KOR) / 수입국: {importer_input} ({importer_iso})] - 제품: {product_input} (HSK: {hscode_input})")

    duties = get_dynamic_tariffs(importer_iso, hscode_input, importer_input)
    
    table_col, info_col = st.columns([1.5, 1])
    
    with table_col:
        st.dataframe(duties, use_container_width=True)

    with info_col:
        valid_duties = [d for d in duties if isinstance(d["관세율 (%)"], (int, float))]
        if valid_duties:
            best = min(valid_duties, key=lambda x: x["관세율 (%)"])
            # 미체결국일 경우 경고 및 안내 문구 명확화
            if any("미체결" in d["협정 (Regime)"] for d in duties):
                st.warning(f"⚠️ **[통상 안내]**\n\n제품 **'{product_input}'** (HSK: {hscode_input})\n\n입력하신 수입국(**{importer_input}**)은 **[FTA 미체결국]**이므로, 특혜 관세 없이 MFN 기본세율 **{best['관세율 (%)']}%**가 적용됩니다.")
            else:
                st.info(f"✨ **[최저 관세 추천]**\n\n제품 **'{product_input}'** (HSK: {hscode_input})\n\n협정 **[{best['협정 (Regime)']}]** 적용 시 관세율 **{best['관세율 (%)']}%**로 가장 유리합니다!")
        else:
            st.warning("비교 가능한 유효 관세율 데이터가 없습니다.")
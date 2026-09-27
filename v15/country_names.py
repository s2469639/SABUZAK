"""입력 국가명(한국어·영문·약어)을 영문 국가명으로 바꾼다.

tavily_v9 조사는 영문 국가명(United States 등)으로 국가·권역·주요 사이트를 판정하므로,
대시보드 입력칸에 "말레이시아"처럼 한국어로 적어도 동작하게 한다. 표에 없으면 입력값 그대로 넘긴다.
"""

COUNTRY_EN = {
    "미국": "United States", "usa": "United States", "us": "United States", "america": "United States",
    "캐나다": "Canada", "멕시코": "Mexico", "브라질": "Brazil", "칠레": "Chile", "페루": "Peru",
    "영국": "United Kingdom", "uk": "United Kingdom", "프랑스": "France", "독일": "Germany",
    "네덜란드": "Netherlands", "벨기에": "Belgium", "스페인": "Spain", "이탈리아": "Italy",
    "폴란드": "Poland", "스웨덴": "Sweden", "스위스": "Switzerland", "오스트리아": "Austria",
    "튀르키예": "Turkey", "터키": "Turkey", "아랍에미리트": "United Arab Emirates", "uae": "United Arab Emirates",
    "두바이": "United Arab Emirates", "사우디아라비아": "Saudi Arabia", "사우디": "Saudi Arabia",
    "일본": "Japan", "중국": "China", "홍콩": "Hong Kong", "대만": "Taiwan", "싱가포르": "Singapore",
    "말레이시아": "Malaysia", "태국": "Thailand", "베트남": "Vietnam", "필리핀": "Philippines",
    "인도네시아": "Indonesia", "인도": "India", "호주": "Australia", "뉴질랜드": "New Zealand",
    "몽골": "Mongolia", "카자흐스탄": "Kazakhstan", "러시아": "Russia",
}


def to_english(country: str) -> str:
    key = (country or "").strip()
    return COUNTRY_EN.get(key) or COUNTRY_EN.get(key.lower()) or key

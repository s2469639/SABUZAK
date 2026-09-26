"""국가별 검색 프로필 상수.

각 국가마다:
- geo: Google Trends 질의용 ISO 3166-1 alpha-2 코드
- name_ko: 화면 표시용 한국어 국가명
- aliases: 사용자가 입력할 수 있는 표기들 (소문자 비교)
- languages: 현지 소비자가 실제로 검색에 쓰는 언어 목록 (첫 번째가 주 언어)
  → 시드 검색어를 "현지어 + 로마자/영문"으로 만들 때 사용
- hl: pytrends 요청 언어. related_queries 결과를 필터링하지는 않고
  응답 라벨 언어에만 영향을 준다 (언어 대응의 핵심은 시드 검색어 쪽).
- buyer_language: 부스 슬로건/피칭 문구를 쓸 바이어 언어
- reliability: 그 나라에서 Google 검색 점유율 기준 트렌드 데이터 신뢰도
  (high / medium / low). low 국가는 결과 상단에 경고를 고정한다.

여기 없는 국가는 LLM이 같은 구조로 프로필을 추정한다 (trend_usp.resolve_country_profile).
"""

RELIABILITY_LABELS_KO = {
    "high": "높음",
    "medium": "보통",
    "low": "낮음",
}

RELIABILITY_NOTES_KO = {
    "CN": "중국 본토는 Google 접속이 차단되어 있어 바이두(Baidu)가 주력 검색엔진입니다. "
          "Google 트렌드 수치는 현지 수요를 대표하지 못하므로 참고용으로만 보세요.",
    "RU": "러시아는 얀덱스(Yandex)가 주력 검색엔진입니다. Google 트렌드 수치는 일부 수요만 반영합니다.",
    "JP": "일본은 Yahoo! JAPAN 검색 비중이 커서 Google 트렌드가 전체 수요를 일부만 반영합니다.",
    "KZ": "카자흐스탄은 얀덱스(Yandex) 이용 비중이 있어 Google 트렌드가 일부 수요만 반영합니다.",
    "KR": "한국은 네이버 검색 비중이 커서 Google 트렌드가 전체 수요를 일부만 반영합니다.",
}

DEFAULT_LOW_RELIABILITY_NOTE_KO = (
    "이 국가는 Google 검색 점유율이 낮아 Google 트렌드 수치가 현지 수요를 대표하지 못할 수 있습니다."
)


def _p(geo, name_ko, aliases, languages, hl, buyer_language, reliability="high"):
    return {
        "geo": geo,
        "name_ko": name_ko,
        "aliases": [a.lower() for a in aliases] + [name_ko.lower(), geo.lower()],
        "languages": languages,
        "hl": hl,
        "buyer_language": buyer_language,
        "reliability": reliability,
    }


COUNTRY_PROFILES = {
    # 북미 / 중남미
    "US": _p("US", "미국", ["usa", "united states", "america", "미합중국"], ["English", "Spanish"], "en-US", "English"),
    "CA": _p("CA", "캐나다", ["canada"], ["English", "French"], "en-CA", "English"),
    "MX": _p("MX", "멕시코", ["mexico", "méxico"], ["Spanish"], "es-MX", "Spanish"),
    "BR": _p("BR", "브라질", ["brazil", "brasil"], ["Portuguese"], "pt-BR", "Portuguese"),
    "CL": _p("CL", "칠레", ["chile"], ["Spanish"], "es-419", "Spanish"),
    # 유럽
    "GB": _p("GB", "영국", ["uk", "united kingdom", "england", "britain"], ["English"], "en-GB", "English"),
    "FR": _p("FR", "프랑스", ["france"], ["French"], "fr", "French"),
    "DE": _p("DE", "독일", ["germany", "deutschland"], ["German"], "de", "German"),
    "NL": _p("NL", "네덜란드", ["netherlands", "holland"], ["Dutch", "English"], "nl", "English"),
    "BE": _p("BE", "벨기에", ["belgium"], ["French", "Dutch"], "fr", "English"),
    "ES": _p("ES", "스페인", ["spain", "españa"], ["Spanish"], "es", "Spanish"),
    "IT": _p("IT", "이탈리아", ["italy", "italia"], ["Italian"], "it", "Italian"),
    "PL": _p("PL", "폴란드", ["poland", "polska"], ["Polish"], "pl", "English"),
    "SE": _p("SE", "스웨덴", ["sweden"], ["Swedish", "English"], "sv", "English"),
    "CH": _p("CH", "스위스", ["switzerland"], ["German", "French", "Italian"], "de", "English"),
    "AT": _p("AT", "오스트리아", ["austria"], ["German"], "de", "German"),
    "RU": _p("RU", "러시아", ["russia"], ["Russian"], "ru", "Russian", "low"),
    "TR": _p("TR", "튀르키예", ["turkey", "türkiye", "터키"], ["Turkish"], "tr", "English"),
    # 중동
    "AE": _p("AE", "아랍에미리트", ["uae", "united arab emirates", "두바이", "dubai"], ["Arabic", "English"], "en", "English"),
    "SA": _p("SA", "사우디아라비아", ["saudi arabia", "saudi", "사우디"], ["Arabic", "English"], "ar", "English"),
    # 아시아 / 오세아니아
    "JP": _p("JP", "일본", ["japan", "日本"], ["Japanese"], "ja", "Japanese", "medium"),
    "CN": _p("CN", "중국", ["china", "중국 본토", "中国"], ["Chinese (Simplified)"], "zh-CN", "Chinese (Simplified)", "low"),
    "HK": _p("HK", "홍콩", ["hong kong"], ["Chinese (Traditional)", "English"], "zh-HK", "English"),
    "TW": _p("TW", "대만", ["taiwan", "臺灣", "台湾"], ["Chinese (Traditional)"], "zh-TW", "Chinese (Traditional)"),
    "SG": _p("SG", "싱가포르", ["singapore"], ["English", "Chinese (Simplified)", "Malay"], "en-SG", "English"),
    "MY": _p("MY", "말레이시아", ["malaysia"], ["Malay", "English", "Chinese (Simplified)"], "ms", "English"),
    "TH": _p("TH", "태국", ["thailand"], ["Thai"], "th", "English"),
    "VN": _p("VN", "베트남", ["vietnam", "viet nam"], ["Vietnamese"], "vi", "Vietnamese"),
    "PH": _p("PH", "필리핀", ["philippines"], ["English", "Filipino"], "en-PH", "English"),
    "ID": _p("ID", "인도네시아", ["indonesia"], ["Indonesian"], "id", "English"),
    "IN": _p("IN", "인도", ["india"], ["English", "Hindi"], "en-IN", "English"),
    "AU": _p("AU", "호주", ["australia", "오스트레일리아"], ["English"], "en-AU", "English"),
    "NZ": _p("NZ", "뉴질랜드", ["new zealand"], ["English"], "en-NZ", "English"),
    "MN": _p("MN", "몽골", ["mongolia"], ["Mongolian"], "mn", "English"),
    "KZ": _p("KZ", "카자흐스탄", ["kazakhstan"], ["Russian", "Kazakh"], "ru", "Russian", "medium"),
}

# 입력 인증 대비 USP 문구 검증용: 같은 그룹 안의 표기는 같은 인증으로 본다.
KNOWN_CERT_GROUPS = [
    ["haccp"],
    ["비건", "vegan"],
    ["할랄", "halal"],
    ["코셔", "kosher"],
    ["유기농", "organic"],
    ["글루텐프리", "글루텐 프리", "gluten-free", "gluten free"],
    ["non-gmo", "non gmo", "논지엠오"],
    ["fssc"],
    ["brc", "brcgs"],
    ["iso 22000", "iso22000"],
]

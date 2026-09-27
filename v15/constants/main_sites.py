"""국가별 주요 사이트 (1차 검색 범위).

주요 농식품 수출국 10개국 초안입니다. 도메인은 전부 DNS 조회로 실재를 확인했지만,
"그 나라에서 이 용도로 가장 적합한 사이트인가"는 팀 검수가 필요합니다. 검수를 마친 국가는
reviewed를 True로 바꿔 주세요. 화면에는 검수 여부가 표시됩니다.

사이트 묶음(group)과 질문의 연결
- media  (언론·생활 매체)   → Q1 소비자
- trade  (식품 업계지)       → Q2 경쟁 제품, Q3 바이어·유통, Q4 박람회
- retail (대형 유통·온라인몰) → Q2 경쟁 제품(제품·가격)
- public (정부·공공)         → Q3 바이어·유통(라벨·인증·수입 규정)

여기 없는 국가는 AI가 같은 구조로 제안하고, 코드가 검증(형식·품질 필터·DNS)한 뒤 캐시에 저장합니다.
"""

GROUP_LABELS = {
    "media": "언론·생활 매체",
    "trade": "식품 업계지",
    "retail": "유통·온라인몰",
    "public": "정부·공공",
}

# 질문별로 1차 검색에 쓰는 사이트 묶음
QUESTION_GROUPS = {
    "Q1": ["media"],
    "Q2": ["retail", "trade"],
    "Q3": ["trade", "public"],
    "Q4": ["trade"],
}

MAIN_SITES = {
    "united states": {"reviewed": False, "groups": {
        "media": ["nytimes.com", "washingtonpost.com", "foodandwine.com", "eater.com", "bonappetit.com", "seriouseats.com"],
        "trade": ["specialtyfood.com", "fooddive.com", "grocerydive.com", "supermarketnews.com",
                  "foodbusinessnews.net", "snackandbakery.com"],
        "retail": ["walmart.com", "costco.com", "target.com", "amazon.com", "hmart.com", "wholefoodsmarket.com"],
        "public": ["fda.gov", "usda.gov", "trade.gov"]}},
    "china": {"reviewed": False, "groups": {
        "media": ["chinadaily.com.cn", "thepaper.cn", "sina.com.cn", "163.com", "people.com.cn"],
        "trade": ["foodaily.com", "foodtalks.cn", "36kr.com", "cbndata.com"],
        "retail": ["jd.com", "tmall.com", "taobao.com"],
        "public": ["samr.gov.cn", "customs.gov.cn", "nhc.gov.cn"]}},
    "japan": {"reviewed": False, "groups": {
        "media": ["nikkei.com", "asahi.com", "yomiuri.co.jp", "mainichi.jp", "nhk.or.jp"],
        "trade": ["shokuhin.net", "nissyoku.co.jp", "foods-ch.com", "prtimes.jp"],
        "retail": ["amazon.co.jp", "rakuten.co.jp", "kaldi.co.jp"],
        "public": ["mhlw.go.jp", "maff.go.jp", "caa.go.jp", "jetro.go.jp"]}},
    "vietnam": {"reviewed": False, "groups": {
        "media": ["vnexpress.net", "tuoitre.vn", "thanhnien.vn", "dantri.com.vn", "vietnamnews.vn"],
        "trade": ["cafef.vn", "vneconomy.vn", "vietnambiz.vn", "baodautu.vn"],
        "retail": ["shopee.vn", "lazada.vn", "tiki.vn", "bachhoaxanh.com"],
        "public": ["vfa.gov.vn", "moit.gov.vn", "customs.gov.vn"]}},
    "taiwan": {"reviewed": False, "groups": {
        "media": ["udn.com", "ltn.com.tw", "chinatimes.com", "cna.com.tw", "ettoday.net"],
        "trade": ["foodnext.net", "cw.com.tw", "businessweekly.com.tw", "bnext.com.tw"],
        "retail": ["pchome.com.tw", "momoshop.com.tw", "carrefour.com.tw", "pxmart.com.tw"],
        "public": ["fda.gov.tw", "moa.gov.tw", "trade.gov.tw"]}},
    "hong kong": {"reviewed": False, "groups": {
        "media": ["scmp.com", "hk01.com", "mingpao.com", "rthk.hk", "thestandard.com.hk"],
        "trade": ["hktdc.com", "marketing-interactive.com"],
        "retail": ["hktvmall.com", "parknshop.com", "wellcome.com.hk", "aeonstores.com.hk"],
        "public": ["cfs.gov.hk", "fehd.gov.hk", "tid.gov.hk"]}},
    "thailand": {"reviewed": False, "groups": {
        "media": ["bangkokpost.com", "nationthailand.com", "thairath.co.th", "matichon.co.th", "khaosod.co.th"],
        "trade": ["prachachat.net", "thansettakij.com", "marketingoops.com", "brandinside.asia"],
        "retail": ["shopee.co.th", "lazada.co.th", "bigc.co.th", "lotuss.com", "makroclick.com"],
        "public": ["moph.go.th", "moac.go.th", "ditp.go.th"]}},
    "indonesia": {"reviewed": False, "groups": {
        "media": ["kompas.com", "detik.com", "cnnindonesia.com", "tempo.co", "thejakartapost.com", "kumparan.com"],
        "trade": ["kontan.co.id", "bisnis.com", "swa.co.id", "marketeers.com"],
        "retail": ["tokopedia.com", "shopee.co.id", "blibli.com", "klikindomaret.com"],
        "public": ["pom.go.id", "halal.go.id", "kemendag.go.id"]}},
    "australia": {"reviewed": False, "groups": {
        "media": ["abc.net.au", "smh.com.au", "theage.com.au", "news.com.au", "taste.com.au"],
        "trade": ["foodanddrinkbusiness.com.au", "insidefmcg.com.au", "retailworldmagazine.com.au", "ausfoodnews.com.au"],
        "retail": ["woolworths.com.au", "coles.com.au", "aldi.com.au"],
        "public": ["foodstandards.gov.au", "agriculture.gov.au", "austrade.gov.au"]}},
    "germany": {"reviewed": False, "groups": {
        "media": ["spiegel.de", "zeit.de", "faz.net", "sueddeutsche.de", "welt.de", "chefkoch.de"],
        "trade": ["lebensmittelzeitung.net", "lebensmittelpraxis.de", "rundschau.de", "horizont.net"],
        "retail": ["rewe.de", "edeka.de", "amazon.de", "kaufland.de"],
        "public": ["bvl.bund.de", "bmel.de", "verbraucherzentrale.de", "gtai.de"]}},
}

# 입력 표기가 달라도 같은 국가로 찾기 위한 별칭 (tavily_v6는 영문 국가명을 받는다)
COUNTRY_ALIASES = {
    "usa": "united states", "us": "united states", "america": "united states",
    "prc": "china", "mainland china": "china",
    "viet nam": "vietnam",
    "hongkong": "hong kong", "hk": "hong kong",
}

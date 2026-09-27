export type Continent = 'asia' | 'europe' | 'americas' | 'oceania' | 'middleeast';

export const continents: { id: Continent; label: string; labelKr: string; count: number; color: string }[] = [
  { id: 'asia', label: 'Asia Pacific', labelKr: '아시아·태평양', count: 2, color: '#c8a96e' },
  { id: 'europe', label: 'Europe', labelKr: '유럽', count: 2, color: '#7b9fd4' },
  { id: 'americas', label: 'Americas', labelKr: '아메리카', count: 1, color: '#7ec8a0' },
  { id: 'oceania', label: 'Oceania', labelKr: '오세아니아', count: 1, color: '#c87b7b' },
  { id: 'middleeast', label: 'Middle East & Africa', labelKr: '중동·아프리카', count: 1, color: '#b07ec8' },
];

export interface ExchangeRate {
  currency: string;
  symbol: string;
  unit: string;
  formatted: string;
  rate: number;
}

export interface Fair {
  id: string;
  continent: Continent;
  name: string;
  country: string;
  city: string;
  dates: string;
  venue: string;
  scale: string;
  category: string;
  visitors: string;
  exhibitors: string;
  website: string;
  deadline: string;
  photoUrl: string;
  officialDescription: string;
  exchangeRate: ExchangeRate;
  exportNotes: ExportNote[];
}

export interface ExportNote {
  type: 'warning' | 'info' | 'required';
  title: string;
  description: string;
  reference: string;
}

// Mock UN Comtrade: annual Korean food imports by country (million USD)
export const comtradeData: Record<string, { year: number; value: number }[]> = {
  '독일':  [{ year: 2022, value: 12.4 }, { year: 2023, value: 15.8 }, { year: 2024, value: 21.2 }],
  '프랑스':[{ year: 2022, value: 7.2  }, { year: 2023, value: 9.8  }, { year: 2024, value: 14.1 }],
  '일본':  [{ year: 2022, value: 89.3 }, { year: 2023, value: 114.2}, { year: 2024, value: 142.8}],
  '태국':  [{ year: 2022, value: 22.1 }, { year: 2023, value: 29.8 }, { year: 2024, value: 40.2 }],
  '미국':  [{ year: 2022, value: 156.8}, { year: 2023, value: 198.4}, { year: 2024, value: 267.1}],
  'UAE':   [{ year: 2022, value: 8.9  }, { year: 2023, value: 12.4 }, { year: 2024, value: 18.7 }],
  '호주':  [{ year: 2022, value: 18.4 }, { year: 2023, value: 24.1 }, { year: 2024, value: 31.8 }],
};

// Mock Google Trends: 12-month search interest for "Korean snack" / "한국 과자" (0–100)
export const trendsData: Record<string, number[]> = {
  '독일':  [32, 35, 38, 42, 45, 48, 52, 58, 62, 68, 72, 78],
  '프랑스':[22, 25, 28, 32, 35, 38, 42, 45, 48, 52, 55, 60],
  '일본':  [65, 68, 72, 75, 78, 82, 85, 88, 90, 92, 88, 95],
  '태국':  [55, 58, 62, 65, 68, 72, 75, 78, 82, 85, 88, 92],
  '미국':  [45, 48, 52, 58, 62, 68, 72, 78, 82, 85, 88, 92],
  'UAE':   [28, 30, 32, 35, 38, 42, 45, 48, 52, 55, 58, 62],
  '호주':  [35, 38, 42, 45, 48, 52, 55, 58, 62, 65, 68, 72],
};

// Mock competitor landscape per country
export const competitorData: Record<string, { name: string; origin: string; price: string; note: string }[]> = {
  '독일':  [
    { name: 'Lotus Biscoff', origin: '벨기에', price: '€2~6', note: '카라멜 쿠키. 항공사 납품 강세' },
    { name: 'Manner Waffeln', origin: '오스트리아', price: '€1.5~5', note: '독일 대형마트 주류 상품' },
    { name: 'Pocky (글리코)', origin: '일본', price: '€2~4', note: '아시안 과자 카테고리 1위' },
  ],
  '프랑스':[
    { name: 'Lu Petit Beurre', origin: '프랑스', price: '€1.5~4', note: '현지 대형마트 지배적 브랜드' },
    { name: '마카롱 (파티스리)', origin: '프랑스', price: '€15~50', note: '약과의 직접 경쟁 카테고리' },
    { name: 'Meiji 팝콘', origin: '일본', price: '€3~6', note: '아시안 식품점 채널 점유' },
  ],
  '일본':  [
    { name: '밀카라 (森永)', origin: '일본', price: '¥150~400', note: '스낵 카테고리 시장 지배' },
    { name: '韓国伝統菓子 브랜드', origin: '한국 수입품', price: '¥500~1500', note: '이미 한국관 진입 제품들. 직접 경쟁' },
    { name: 'Orion 초코파이', origin: '한국', price: '¥200~600', note: '한국 과자 대표 브랜드. 인지도 높음' },
  ],
  '태국':  [
    { name: 'Lays Thailand', origin: '미국(현지 생산)', price: '฿20~60', note: '스낵 카테고리 압도적 1위' },
    { name: '비비고 스낵', origin: '한국', price: '฿80~200', note: 'CJ 제품. K-스낵 선발 주자' },
    { name: 'Pocky', origin: '일본', price: '฿30~80', note: '아세안 전역 강세' },
  ],
  '미국':  [
    { name: 'Pepperidge Farm Goldfish', origin: '미국', price: '$3~8', note: '스낵 메인스트림. 직접 경쟁 아님' },
    { name: '허니버터칩 (수입품)', origin: '한국', price: '$5~12', note: '코리안 마켓 채널 이미 진입' },
    { name: 'Trader Joe\'s K-스낵', origin: '한국 소싱', price: '$4~10', note: '바이어 직접 소싱. 경쟁 + 협업 가능' },
  ],
  'UAE':   [
    { name: 'Pringles', origin: '미국', price: 'AED 8~20', note: '중동 편의점 압도적 점유' },
    { name: '한국 라면 스낵', origin: '한국', price: 'AED 5~15', note: '이미 인지도 있는 K-스낵' },
    { name: '할랄 인증 터키 쿠키', origin: '터키', price: 'AED 6~18', note: '할랄 스낵 카테고리 경쟁' },
  ],
  '호주':  [
    { name: 'Tim Tam', origin: '호주', price: 'A$3~7', note: '호주 대표 과자. 강한 로컬 충성도' },
    { name: '크라운 한과', origin: '한국', price: 'A$5~15', note: '한인 마트 채널 이미 진입' },
    { name: 'Arnott\'s', origin: '호주', price: 'A$2~6', note: '대형마트 쿠키 카테고리 지배' },
  ],
};

// HS code tariff data per product per country
export const hsTariffData: Record<string, Record<string, { tariff: string; note: string; certification: string[] }>> = {
  '1905.90': { // 약과
    '독일':  { tariff: '9.0%',  note: 'EU 통합관세율. 한-EU FTA 적용 가능',    certification: ['EU-FVO', 'HACCP'] },
    '프랑스':{ tariff: '9.0%',  note: 'EU 통합관세율',                          certification: ['EU-FVO', 'HACCP'] },
    '일본':  { tariff: '6.0%',  note: 'MFN 세율. 한-일 FTA 미체결',             certification: ['HACCP', 'JAS(선택)'] },
    '태국':  { tariff: '5.0%',  note: 'AKFTA 협정세율 (일반세율 30%)',          certification: ['HACCP', 'ACFS'] },
    '미국':  { tariff: '0%',    note: 'KORUS FTA 무관세',                        certification: ['FDA', 'HACCP'] },
    'UAE':   { tariff: '5.0%',  note: 'GCC 통일관세',                            certification: ['HALAL', 'HACCP'] },
    '호주':  { tariff: '0%',    note: 'KAFTA 무관세',                            certification: ['AQIS', 'HACCP'] },
  },
  '1904.10': { // 유과·누룽지칩
    '독일':  { tariff: '7.7%',  note: 'EU 통합관세율',                           certification: ['EU-FVO', 'HACCP'] },
    '프랑스':{ tariff: '7.7%',  note: 'EU 통합관세율',                           certification: ['EU-FVO', 'HACCP'] },
    '일본':  { tariff: '6.0%',  note: 'MFN 세율',                               certification: ['HACCP'] },
    '태국':  { tariff: '5.0%',  note: 'AKFTA 협정세율',                          certification: ['HACCP'] },
    '미국':  { tariff: '0%',    note: 'KORUS FTA 무관세',                        certification: ['FDA', 'HACCP'] },
    'UAE':   { tariff: '5.0%',  note: 'GCC 통일관세',                            certification: ['HALAL', 'HACCP'] },
    '호주':  { tariff: '0%',    note: 'KAFTA 무관세',                            certification: ['AQIS', 'HACCP'] },
  },
  '2106.90': { // 김부각
    '독일':  { tariff: '6.4%',  note: '원산지 증명 필수',                        certification: ['EU-FVO', 'HACCP'] },
    '프랑스':{ tariff: '6.4%',  note: '원산지 증명 필수',                        certification: ['EU-FVO', 'HACCP'] },
    '일본':  { tariff: '6.4%',  note: '후생노동성 신고 필수',                    certification: ['HACCP'] },
    '태국':  { tariff: '5.0%',  note: 'AKFTA 협정세율',                          certification: ['HACCP', 'HALAL(선택)'] },
    '미국':  { tariff: '0%',    note: 'KORUS FTA 무관세',                        certification: ['FDA', 'HACCP'] },
    'UAE':   { tariff: '5.0%',  note: '할랄 인증 없으면 수입 불가',              certification: ['HALAL', 'HACCP'] },
    '호주':  { tariff: '0%',    note: 'KAFTA 무관세. 해조류 검역 확인',          certification: ['AQIS', 'HACCP'] },
  },
  '2005.99': { // 고구마스틱
    '독일':  { tariff: '14.4%', note: '고세율 주의. FTA 적용 시 절감 가능',     certification: ['EU-FVO', 'HACCP'] },
    '프랑스':{ tariff: '14.4%', note: '고세율 주의',                             certification: ['EU-FVO', 'HACCP'] },
    '일본':  { tariff: '9.6%',  note: '검역 주의 품목',                          certification: ['HACCP', 'MAFF'] },
    '태국':  { tariff: '5.0%',  note: 'AKFTA 협정세율',                          certification: ['HACCP', 'ACFS'] },
    '미국':  { tariff: '0%',    note: 'KORUS FTA 무관세',                        certification: ['FDA', 'HACCP'] },
    'UAE':   { tariff: '5.0%',  note: 'GCC 통일관세',                            certification: ['HALAL', 'HACCP'] },
    '호주':  { tariff: '0%',    note: 'KAFTA 무관세',                            certification: ['AQIS', 'HACCP'] },
  },
};

export const fairs: Fair[] = [
  {
    id: 'sial-paris-2026',
    continent: 'europe',
    name: 'SIAL Paris 2026',
    country: '프랑스',
    city: '파리 (빌팽트)',
    dates: '2026.10.18 – 10.22',
    venue: 'Paris Nord Villepinte',
    scale: '초대형',
    category: '식품 혁신·미식',
    visitors: '320,000명',
    exhibitors: '7,200개사',
    website: 'sialparis.com',
    deadline: '2026.06.30',
    photoUrl: 'https://images.unsplash.com/photo-1574939854694-8f34cf7a2867?w=900&h=400&fit=crop&auto=format',
    officialDescription: "SIAL, the world's number one food innovation exhibition, takes place in Paris every two years. An unparalleled platform bringing together 7,200 exhibitors from 127 countries, SIAL Paris is a one-of-a-kind global professional event connecting all food sector players. It is THE global agri-food meeting place where professionals come to get inspired, discover innovations, develop their markets, and build new partnerships. The SIAL Innovation competition, the most prestigious food prize in the world, spotlights the best new products launched on the global market.",
    exchangeRate: { currency: 'EUR', symbol: '€', unit: '1 EUR', formatted: '1 EUR = 약 1,490원', rate: 1490 },
    exportNotes: [
      { type: 'required', title: 'EU 식품라벨링 규정 (FIC 1169/2011)', description: '알레르기 유발 물질 14종 굵은 글씨 표기 의무. 프랑스어 라벨 필수. 영양성분표 포함.', reference: 'EU Regulation No 1169/2011' },
      { type: 'required', title: 'EU Novel Food 규정 확인', description: '기존 EU 시장 미판매 성분 포함 시 Novel Food 신청 필요.', reference: 'EU Regulation 2015/2283' },
      { type: 'warning', title: '식품첨가물 허용 기준 차이', description: '한국 허용 첨가물 중 EU 미승인 성분 존재. 색소·방부제 성분 사전 확인 필수.', reference: 'EU Regulation No 1333/2008' },
      { type: 'info', title: '한-EU FTA 원산지 증명', description: 'KOTRA 또는 대한상공회의소 C/O 발급 시 협정세율 적용 가능.', reference: 'EU-Korea FTA Protocol' },
    ],
  },
  {
    id: 'anuga-2025',
    continent: 'europe',
    name: 'Anuga 2025',
    country: '독일',
    city: '쾰른',
    dates: '2025.10.04 – 10.08',
    venue: 'Koelnmesse',
    scale: '초대형',
    category: '식품·음료 종합',
    visitors: '165,000명',
    exhibitors: '7,400개사',
    website: 'anuga.com',
    deadline: '2025.07.31',
    photoUrl: 'https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=900&h=400&fit=crop&auto=format',
    officialDescription: "Anuga is the world's leading trade fair for the global food and beverage industry. In Cologne, the world's biggest supermarket opens its doors every two years with over 7,400 exhibitors from 110 countries and around 165,000 trade visitors from more than 200 countries, making it the most important global platform for all segments of the food and beverage industry. The ten Anuga trade shows are held simultaneously — Anuga Fine Food, for premium specialties and delicatessen products, is the optimal setting for Korean traditional snacks.",
    exchangeRate: { currency: 'EUR', symbol: '€', unit: '1 EUR', formatted: '1 EUR = 약 1,490원', rate: 1490 },
    exportNotes: [
      { type: 'required', title: 'EU 식품라벨링 규정 (FIC 1169/2011)', description: '알레르기 유발 물질 14종 굵은 글씨 표기 의무. 독일어 라벨 필수.', reference: 'EU Regulation No 1169/2011' },
      { type: 'warning', title: '식품첨가물 허용 기준 차이', description: '한국 허용 첨가물 중 EU 미승인 성분 존재. 사전 확인 필수.', reference: 'EU Regulation No 1333/2008' },
      { type: 'required', title: '원산지 증명서 (C/O)', description: '한-EU FTA 적용 시 세율 혜택. KOTRA 또는 대한상공회의소 발급.', reference: 'EU-Korea FTA Protocol' },
    ],
  },
  {
    id: 'foodex-2025',
    continent: 'asia',
    name: 'FOODEX JAPAN 2025',
    country: '일본',
    city: '치바 (도쿄 인근)',
    dates: '2025.03.04 – 03.07',
    venue: 'Makuhari Messe',
    scale: '대형',
    category: '식품·음료 종합',
    visitors: '80,000명',
    exhibitors: '3,000개사',
    website: 'foodex.jp',
    deadline: '2024.11.30',
    photoUrl: 'https://images.unsplash.com/photo-1526040652367-ac003a0475fe?w=900&h=400&fit=crop&auto=format',
    officialDescription: "FOODEX JAPAN is the largest international food and beverage exhibition in Asia, held annually at Makuhari Messe, Japan. As Asia's biggest trade show for the food industry, FOODEX provides an unparalleled business platform where global buyers discover the latest food and beverage products, trends and technologies. With over 80,000 trade visitors and 3,000 exhibiting companies from around the world, it is the definitive gateway to the Asian — and specifically Japanese — food market. A dedicated Korea Pavilion is operated each year, providing strong visibility for Korean food exporters.",
    exchangeRate: { currency: 'JPY', symbol: '¥', unit: '100 JPY', formatted: '100 JPY = 약 935원', rate: 9.35 },
    exportNotes: [
      { type: 'required', title: '일본 식품위생법 준수', description: '식품첨가물 기준이 한국보다 엄격. 후생노동성 등록 수입업자 필요.', reference: '食品衛生法 第11条' },
      { type: 'warning', title: '한국산 농산물 추가 검사', description: '일부 품목 추가 방사선·잔류농약 검사 시행. 원산지 표기 철저 관리.', reference: '厚生労働省 告示' },
      { type: 'info', title: '일본어 라벨링 의무', description: '모든 식품 일본어 표기 의무. 알레르기 7종 + 20종 권장 표기.', reference: '食品表示法' },
    ],
  },
  {
    id: 'thaifex-2025',
    continent: 'asia',
    name: 'THAIFEX – Anuga Asia 2025',
    country: '태국',
    city: '방콕',
    dates: '2025.05.27 – 05.31',
    venue: 'IMPACT Challenger Hall',
    scale: '대형',
    category: '아시아·태평양 식품 종합',
    visitors: '95,000명',
    exhibitors: '3,500개사',
    website: 'thaifex-anuga.com',
    deadline: '2025.02.28',
    photoUrl: 'https://images.unsplash.com/photo-1567521464027-f127ff144326?w=900&h=400&fit=crop&auto=format',
    officialDescription: "THAIFEX – Anuga Asia is Asia's premier food and beverage trade event, co-organised by Koelnmesse and the Thai Chamber of Commerce. Bringing together over 3,500 exhibitors from 60+ countries and 95,000 trade visitors from across the Asia-Pacific region, it is the most comprehensive food trade platform in Southeast Asia. The event covers the full spectrum of food and beverages — from primary produce to processed foods, packaging, equipment, and innovative F&B concepts. K-food has consistently been one of the most visited national pavilions.",
    exchangeRate: { currency: 'THB', symbol: '฿', unit: '100 THB', formatted: '100 THB = 약 3,870원', rate: 38.7 },
    exportNotes: [
      { type: 'required', title: '태국 FDA 수입 허가', description: '태국 수출 전 Thai FDA 식품 수입 허가 취득 필요. 현지 수입업자를 통한 등록.', reference: 'Thailand FDA Act B.E. 2522' },
      { type: 'info', title: 'ASEAN-Korea FTA 활용', description: 'AKFTA 협정세율 활용 시 관세 대폭 절감. 원산지 기준(40% 부가가치) 충족 필수.', reference: 'AKFTA Schedule' },
      { type: 'warning', title: '태국어 라벨 의무', description: '태국 판매 제품 태국어 라벨 필수.', reference: 'Thai FDA Notification No. 367' },
    ],
  },
  {
    id: 'summer-fancy-food-2025',
    continent: 'americas',
    name: 'Summer Fancy Food Show 2025',
    country: '미국',
    city: '뉴욕',
    dates: '2025.06.29 – 07.01',
    venue: 'Javits Center',
    scale: '대형',
    category: '특수·고급 식품',
    visitors: '30,000명',
    exhibitors: '2,400개사',
    website: 'specialtyfood.com',
    deadline: '2025.03.31',
    photoUrl: 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=900&h=400&fit=crop&auto=format',
    officialDescription: "The Summer Fancy Food Show is the largest specialty food industry event in North America, produced by the Specialty Food Association. For over six decades, the Show has been the essential marketplace where specialty food makers, buyers, brokers, distributors, restaurateurs, media and influencers meet to taste, discover, and do business. More than 2,400 exhibitors from across the U.S. and around the globe showcase specialty foods and beverages to more than 30,000 industry professionals, spotlighting emerging trends and connecting the specialty food community.",
    exchangeRate: { currency: 'USD', symbol: '$', unit: '1 USD', formatted: '1 USD = 약 1,385원', rate: 1385 },
    exportNotes: [
      { type: 'required', title: 'FDA 식품 시설 등록', description: '미국 수출 전 FDA 시설 등록 필수. 2년마다 갱신.', reference: 'FDA 21 CFR 1.225' },
      { type: 'required', title: 'FSMA 준수 (식품안전현대화법)', description: '공급망 위해요소 관리 계획(HARPC) 수립 의무.', reference: 'FSMA 2011' },
      { type: 'info', title: 'KORUS FTA 무관세 혜택', description: '한-미 FTA로 대부분 식품류 무관세. 원산지 증명 필수.', reference: 'KORUS FTA Schedule' },
    ],
  },
  {
    id: 'gulf-food-2025',
    continent: 'middleeast',
    name: 'Gulfood 2025',
    country: 'UAE',
    city: '두바이',
    dates: '2025.02.17 – 02.21',
    venue: 'Dubai World Trade Centre',
    scale: '초대형',
    category: '식품·음료·호스피탈리티',
    visitors: '100,000명',
    exhibitors: '5,000개사',
    website: 'gulfood.com',
    deadline: '2024.11.15',
    photoUrl: 'https://images.unsplash.com/photo-1512632578888-169bbbc64f33?w=900&h=400&fit=crop&auto=format',
    officialDescription: "Gulfood is the world's single largest annual food and hospitality show. Held each February in Dubai, UAE, Gulfood brings together 5,000+ exhibitors from 120+ countries with more than 100,000 trade buyers over five days. As the leading food and beverage gateway to the Middle East, Africa and South Asia, Gulfood creates unrivalled opportunities for global food business growth. Spanning eight halls across the Dubai World Trade Centre, the show covers the entire supply chain — from ingredients and primary produce to finished consumer goods and hospitality solutions.",
    exchangeRate: { currency: 'AED', symbol: 'د.إ', unit: '1 AED', formatted: '1 AED = 약 377원', rate: 377 },
    exportNotes: [
      { type: 'required', title: '할랄 인증 필수', description: '중동 전역 할랄 인증 없이 식품 수입 불가. KMF, IFANCA 등 UAE 승인 기관 인증.', reference: 'UAE Federal Law No. 15/2009' },
      { type: 'warning', title: '아랍어 라벨 의무', description: 'UAE 판매 제품 아랍어 라벨 필수.', reference: 'GSO 9:2013' },
      { type: 'info', title: 'ESMA 식품 안전 기준', description: 'UAE 식품 안전청(ESMA) 기준 준수. 제품별 사전 등록 필요.', reference: 'UAE Cabinet Resolution No. 5/2017' },
    ],
  },
  {
    id: 'fine-food-australia-2025',
    continent: 'oceania',
    name: 'Fine Food Australia 2025',
    country: '호주',
    city: '시드니',
    dates: '2025.09.08 – 09.11',
    venue: 'ICC Sydney',
    scale: '중형',
    category: '고급 식품·음료·호스피탈리티',
    visitors: '25,000명',
    exhibitors: '1,200개사',
    website: 'finefoodaustralia.com.au',
    deadline: '2025.06.30',
    photoUrl: 'https://images.unsplash.com/photo-1482049016688-2d3e1b311543?w=900&h=400&fit=crop&auto=format',
    officialDescription: "Fine Food Australia is the Asia-Pacific's premier food service, food retail and hospitality trade event. It connects thousands of buyers and sellers from around the world in a business environment dedicated to food professionals — chefs, foodservice operators, retailers, distributors and manufacturers. Fine Food Australia showcases the finest and freshest in specialty foods, ingredients, equipment and hospitality products, held annually at ICC Sydney with growing interest in authentic Korean food products.",
    exchangeRate: { currency: 'AUD', symbol: 'A$', unit: '1 AUD', formatted: '1 AUD = 약 890원', rate: 890 },
    exportNotes: [
      { type: 'required', title: '호주 검역·생물안전법 준수', description: '농산물 유래 성분 포함 식품 AQIS 검역 필수.', reference: 'Biosecurity Act 2015' },
      { type: 'info', title: 'KAFTA 무관세 혜택', description: '한-호주 FTA로 대부분 가공식품 무관세.', reference: 'KAFTA Schedule' },
      { type: 'warning', title: 'FSANZ 식품 기준 준수', description: '호주·뉴질랜드 식품 기준 영어 표기 의무.', reference: 'FSANZ Food Standards Code' },
    ],
  },
];

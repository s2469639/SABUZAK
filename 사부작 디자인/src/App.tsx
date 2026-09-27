import { useState } from 'react';
import { ComposableMap, Geographies, Geography } from 'react-simple-maps';
import { geoMiller } from 'd3-geo-projection';
import { feature } from 'topojson-client';
import topoJson from './assets/countries-110m.json';
import {
  continents, fairs, comtradeData, trendsData, competitorData, hsTariffData,
  type Continent, type Fair,
} from './data';

type View = 'login' | 'dashboard' | 'in-progress' | 'fair-detail' | 'my-products' | 'booth-concept' | 'country-market' | 'country-fairs';
type FairTab = 'overview' | 'market' | 'trends' | 'hs-export';

interface Product {
  id: string;
  name: string;
  hsCode: string;
  ingredients: string;
}

interface GeneratedConcept {
  theme: string;
  slogan: string;
  visualDirection: string;
  sellingPoints: { title: string; description: string; priority: 'core' | 'support' }[];
  events: { name: string; type: string; description: string; duration: string }[];
  targetBuyers: string[];
  imageUrl: string;
}

// ─── Concept generator (product + fair aware) ──────────────────────────────
function generateConcept(fair: Fair, products: Product[]): GeneratedConcept {
  const pNames = products.map(p => p.name);
  const pStr = pNames.join(', ');

  const isFancy = fair.category.includes('고급') || fair.category.includes('Fine') || fair.category.includes('특수');
  const isAsia  = fair.continent === 'asia';
  const isME    = fair.continent === 'middleeast';

  const countryCtx: Record<string, { pairing: string; tagline: string; buyer: string; imgUrl: string }> = {
    '독일':  { pairing: '독일 크래프트 맥주', tagline: 'Crafted in 5,000 Years of Korean Tradition', buyer: '독일·유럽 프리미엄 유통사', imgUrl: 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&h=480&fit=crop' },
    '프랑스':{ pairing: '프랑스 와인', tagline: 'La Pâtisserie Coréenne — L\'Art Ancestral', buyer: '프랑스 미식 유통사·파리 파티스리', imgUrl: 'https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&h=480&fit=crop' },
    '일본':  { pairing: '일본 녹차·호지차', tagline: '韓国の伝統菓子 — 心を結ぶ味', buyer: '일본 백화점·편의점 MD', imgUrl: 'https://images.unsplash.com/photo-1567521464027-f127ff144326?w=800&h=480&fit=crop' },
    '태국':  { pairing: '태국 밀크티', tagline: 'Korean Street Snack Culture Goes Global', buyer: '동남아 리테일 바이어·온라인 플랫폼', imgUrl: 'https://images.unsplash.com/photo-1567521464027-f127ff144326?w=800&h=480&fit=crop' },
    '미국':  { pairing: '스페셜티 커피', tagline: "Korea's Royal Snack, Reimagined for America", buyer: '홀푸즈·트레이더조 MD·프리미엄 유통사', imgUrl: 'https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=800&h=480&fit=crop' },
    'UAE':   { pairing: '아랍 전통차 (카와)', tagline: 'Halal Korean Heritage — Pure & Traditional', buyer: '중동 할랄 유통사·호텔 F&B 바이어', imgUrl: 'https://images.unsplash.com/photo-1574939854694-8f34cf7a2867?w=800&h=480&fit=crop' },
    '호주':  { pairing: '호주 플랫화이트', tagline: 'Korean Craft Snacks — Naturally Yours', buyer: '호주 카페·리테일 바이어', imgUrl: 'https://images.unsplash.com/photo-1559136555-9303baea8ebd?w=800&h=480&fit=crop' },
  };

  const ctx = countryCtx[fair.country] ?? { pairing: '현지 음료', tagline: 'K-Snack Heritage', buyer: '현지 유통사', imgUrl: 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=800&h=480&fit=crop' };

  let theme: string;
  let sellingPoints: GeneratedConcept['sellingPoints'];
  let events: GeneratedConcept['events'];

  if (isME) {
    theme = `${pStr} — 할랄 인증 K-전통 스낵의 중동 시장 진출`;
    sellingPoints = [
      { title: '할랄 인증 완비', description: `${pStr} 전 제품 KMF·IFANCA 인증 취득. 중동 바이어 최우선 검토 항목.`, priority: 'core' },
      { title: '천연·무첨가 성분', description: '합성 첨가물 ZERO, 전통 발효·천연 재료만 사용. 이슬람 식품 기준 완전 부합.', priority: 'core' },
      { title: `${ctx.pairing} 페어링`, description: `${ctx.pairing}와 어울리는 맛 조합으로 현지 일상 소비 접점 형성.`, priority: 'support' },
      { title: '아랍어 패키지', description: '현지어 라벨 완비, 아랍 문화권 선물 시즌(라마단 등) 겨냥 기프트 라인 전시.', priority: 'support' },
    ];
    events = [
      { name: '할랄 K-스낵 테이스팅', type: '시식 이벤트', description: `${pNames[0] ?? 'K-스낵'} 할랄 인증서 부스 전시 + 시식. 인증 현황 QR코드 확인 제공.`, duration: '전일 운영' },
      { name: '라마단 기프트 박스 전시', type: '시즌 마케팅', description: '라마단·이드 시즌 기프트 패키지 쇼케이스. B2B 대량 오더 유도.', duration: '상시' },
      { name: '포토존 "서울 × 두바이"', type: 'SNS 마케팅', description: '한국 전통 이미지와 두바이 골드 컬러 조합 포토존. 태그 시 미니 기프트 증정.', duration: '상시' },
      { name: '할랄 바이어 VIP 상담', type: 'B2B 상담', description: '중동 할랄 유통사 대상 전용 미팅룸. MOQ·납기·인증 서류 집중 상담.', duration: '예약제' },
    ];
  } else if (isAsia) {
    theme = `${pStr} × K-컬처 — 아시아를 사로잡는 일상 간식`;
    sellingPoints = [
      { title: 'K-드라마·K-팝 연계', description: `${pStr}가 등장하는 K-드라마 장면·SNS 클립을 부스 디스플레이로 활용. 현지 팬덤 소비 유도.`, priority: 'core' },
      { title: '인스타그래머블 패키지', description: '현지 SNS 트렌드에 맞는 비주얼 포장. 자발적 포토 마케팅 유도.', priority: 'core' },
      { title: `${ctx.pairing} 페어링`, description: `현지 일상 음료 ${ctx.pairing}와의 페어링 제안으로 소비 접점 확대.`, priority: 'support' },
      { title: '버라이어티 팩 라인업', description: `${pStr} 전 제품을 한 번에 경험하는 샘플러 팩. 현지 온라인몰 진입 SKU로 최적.`, priority: 'support' },
    ];
    events = [
      { name: '시식 + 사부작 키링 증정', type: '시식·경품 이벤트', description: `${pNames[0] ?? 'K-스낵'} 시식 후 사부작 브랜드 키링 증정. 부스 방문 동선 유도에 가장 효과적.`, duration: '전일 운영' },
      { name: 'K-스낵 챌린지 포토존', type: 'SNS 마케팅', description: '릴스·틱톡 포맷에 맞는 배경 설치. 해시태그 이벤트 병행. 현지 인플루언서 사전 섭외 권장.', duration: '상시' },
      { name: '현지 인플루언서 초청', type: '인플루언서 마케팅', description: '현지 푸드 인플루언서 부스 초청. 실시간 라이브 방송 협의로 SNS 바이럴 극대화.', duration: '1~2회' },
      { name: '도매 바이어 상담', type: 'B2B 상담', description: '현지 도매상 대상 MOQ 250박스~, 납기·가격 협의 집중 상담.', duration: '예약제' },
    ];
  } else if (isFancy) {
    theme = `${pStr} — 조선 왕실 다과, 현대 프리미엄으로`;
    sellingPoints = [
      { title: '장인 생산 스토리', description: `${pStr} 장인 이름·생산지·공정 명기. 프리미엄 소비자 신뢰와 스토리텔링 가치 형성.`, priority: 'core' },
      { title: `${ctx.pairing} 페어링`, description: `${ctx.pairing}와의 조화 제안. 현지 프리미엄 소비 문화와 자연스럽게 연결.`, priority: 'core' },
      { title: '기프트 한지 박스', description: '전통 한지 포장 선물세트 전시. 시즌 기프트 바이어 수요 자극.', priority: 'support' },
      { title: '성분 QR 투명성', description: '전 성분·원산지 QR 추적. 프리미엄 소비자 신뢰 확보.', priority: 'support' },
    ];
    events = [
      { name: `${pStr} × ${ctx.pairing} 페어링 테이스팅`, type: '시식 이벤트', description: `소믈리에·바리스타와 협업, ${pNames[0] ?? 'K-스낵'}와 ${ctx.pairing}의 최적 페어링 제안. 10인 이하 소규모 그룹 운영.`, duration: '20분 × 4회' },
      { name: '포토존 "조선의 찬합"', type: 'SNS 마케팅', description: '전통 찬합 모티프 포토존. 방문객 인증샷 유도. 태그 시 기프트박스 증정.', duration: '상시' },
      { name: '장인 스토리텔링 세미나', type: '세미나', description: '제조 공정 영상 + 생산자 이야기 프레젠테이션. 바이어 심층 신뢰 구축.', duration: '25분 × 2회' },
      { name: 'VIP 바이어 1:1 상담', type: 'B2B 상담', description: '시즌 기프트 오더 집중 상담. 맞춤형 샘플 패키지 + 단가표 제공.', duration: '예약제' },
    ];
  } else {
    theme = `${pStr} — 5,000년 전통의 K-웰니스 스낵`;
    sellingPoints = [
      { title: '천연·무첨가 성분', description: `${pStr} 전 제품 합성 첨가물 ZERO. 성분표 전면 공개.`, priority: 'core' },
      { title: 'K-컬처 스토리텔링', description: '한국 전통 문화 배경 영상·그래픽으로 제품의 역사적 맥락 전달.', priority: 'core' },
      { title: `${ctx.pairing} 페어링`, description: `현지 일상 음료 ${ctx.pairing}와의 페어링 제안으로 소비 접점 확대.`, priority: 'support' },
      { title: '지속가능 패키지', description: '재활용 소재 포장, 탄소 발자국 정보 공개. ESG 소비 트렌드 대응.', priority: 'support' },
    ];
    events = [
      { name: '궁중 다과 테이스팅', type: '시식 이벤트', description: `한복 착용 스태프가 전통 다기 세트로 ${pStr} 시식 제공. 문화 몰입형 경험.`, duration: '15분 × 4회' },
      { name: '전통 문양 포토존', type: 'SNS 마케팅', description: '단청·청화백자 패턴 배경 포토존. 태그 시 미니 기프트 증정.', duration: '상시' },
      { name: '웰니스 세미나', type: '세미나', description: '한국 전통 발효식품의 건강 효능 영어 프레젠테이션. 영양사·셰프 바이어 타겟.', duration: '30분 × 2회' },
      { name: 'VIP 바이어 상담', type: 'B2B 상담', description: '맞춤 샘플 + 단가표. MOQ·납기 집중 협의.', duration: '예약제' },
    ];
  }

  return {
    theme,
    slogan: ctx.tagline,
    visualDirection: `${fair.country} 현지 감성 + 한국 전통 미감의 조화. ${ctx.pairing}와 어울리는 따뜻한 색감 부스 인테리어. 단청 패턴 그래픽 요소 포인트 활용.`,
    sellingPoints,
    events,
    targetBuyers: [ctx.buyer, `${fair.country} 프리미엄 식품 수입업체`, '아시아 식품 전문 에이전트', '온라인 식품 플랫폼 MD'],
    imageUrl: ctx.imgUrl,
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function sortFairsByDate(list: Fair[]) {
  return [...list].sort((a, b) => b.dates.localeCompare(a.dates));
}

// Simple SVG sparkline
function Sparkline({ data, color = '#F06A1A' }: { data: number[]; color?: string }) {
  const w = 360; const h = 64; const pad = 6;
  const max = Math.max(...data); const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });
  const polyPts = pts.join(' ');
  const fillPts = `${pad},${h} ${polyPts} ${w - pad},${h}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ height: h, display: 'block' }}>
      <polygon points={fillPts} fill={color} fillOpacity="0.12" />
      <polyline points={polyPts} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {data.map((v, i) => {
        const x = pad + (i / (data.length - 1)) * (w - pad * 2);
        const y = h - pad - ((v - min) / range) * (h - pad * 2);
        return i === data.length - 1
          ? <circle key={i} cx={x} cy={y} r="3.5" fill={color} />
          : null;
      })}
    </svg>
  );
}

// ─── Logo ─────────────────────────────────────────────────────────────────────
function SabuzakLogo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
      <rect x="1" y="1" width="26" height="26" rx="6" fill="#F06A1A" />
      <rect x="12.5" y="4" width="3" height="20" rx="1.5" fill="rgba(255,255,255,0.3)" />
      <rect x="4" y="12.5" width="20" height="3" rx="1.5" fill="rgba(255,255,255,0.3)" />
      <circle cx="14" cy="14" r="3.5" fill="rgba(255,255,255,0.45)" />
      <circle cx="14" cy="14" r="1.5" fill="#F06A1A" />
    </svg>
  );
}

// ─── No Products Prompt ───────────────────────────────────────────────────────
function NoProductsPrompt({ onGo }: { onGo: () => void }) {
  return (
    <div className="text-center py-16">
      <div className="inline-flex flex-col items-center gap-3">
        <div className="w-11 h-11 flex items-center justify-center text-xl" style={{ background: '#f5f3ee', border: '1px solid #ebe8e2', borderRadius: 4 }}>📦</div>
        <p className="text-sm font-medium" style={{ color: '#1a1a1a' }}>등록된 제품이 없습니다</p>
        <p className="text-xs" style={{ color: '#aaa' }}>내 제품에서 제품을 추가하면<br />해당 국가 맞춤 정보를 확인할 수 있습니다</p>
        <button onClick={onGo} className="text-xs px-4 py-2 transition-opacity hover:opacity-80" style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}>
          내 제품 추가하러 가기 →
        </button>
      </div>
    </div>
  );
}

// ─── Login ────────────────────────────────────────────────────────────────────
function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [id, setId] = useState(''); const [pw, setPw] = useState(''); const [loading, setLoading] = useState(false);
  const handle = (e: React.FormEvent) => { e.preventDefault(); setLoading(true); setTimeout(() => { setLoading(false); onLogin(); }, 800); };
  return (
    <div className="min-h-screen flex flex-col items-center justify-center" style={{ background: '#f7f6f3' }}>
      <div className="w-full max-w-sm px-4">
        <div className="mb-10 text-center">
          <div className="inline-flex flex-col items-center gap-3">
            <SabuzakLogo size={44} />
            <div><p className="text-lg font-bold" style={{ color: '#1a1a1a' }}>사부작</p><p className="text-xs mt-0.5" style={{ color: '#999' }}>박람회 운영 자동화 대시보드</p></div>
          </div>
        </div>
        <form onSubmit={handle} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1"><label className="text-xs" style={{ color: '#666' }}>아이디</label>
            <input value={id} onChange={e => setId(e.target.value)} placeholder="아이디" className="w-full px-3 py-2.5 text-sm outline-none" style={{ background: '#fff', border: '1px solid #e0ddd8', color: '#1a1a1a', borderRadius: 4 }} onFocus={e => e.target.style.borderColor = '#F06A1A'} onBlur={e => e.target.style.borderColor = '#e0ddd8'} /></div>
          <div className="flex flex-col gap-1"><label className="text-xs" style={{ color: '#666' }}>비밀번호</label>
            <input type="password" value={pw} onChange={e => setPw(e.target.value)} placeholder="••••••••" className="w-full px-3 py-2.5 text-sm outline-none" style={{ background: '#fff', border: '1px solid #e0ddd8', color: '#1a1a1a', borderRadius: 4 }} onFocus={e => e.target.style.borderColor = '#F06A1A'} onBlur={e => e.target.style.borderColor = '#e0ddd8'} /></div>
          <button type="submit" disabled={loading} className="mt-1 py-2.5 text-sm font-medium" style={{ background: '#F06A1A', color: '#fff', borderRadius: 4, opacity: loading ? 0.7 : 1 }}>{loading ? '로그인 중...' : '로그인'}</button>
        </form>
        <p className="text-center text-xs mt-5" style={{ color: '#ccc' }}>사부작 내부 시스템 — 임직원 전용</p>
      </div>
    </div>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ view, onNav }: { view: View; onNav: (v: View) => void }) {
  return (
    <aside className="flex flex-col h-full" style={{ width: 200, background: '#fff', borderRight: '1px solid #ebe8e2' }}>
      <button onClick={() => onNav('dashboard')} className="px-5 py-4 flex items-center gap-2.5 w-full text-left hover:bg-orange-50 transition-colors" style={{ borderBottom: '1px solid #ebe8e2' }}>
        <SabuzakLogo size={28} />
        <div><p className="text-sm font-bold" style={{ color: '#1a1a1a' }}>사부작</p><p className="text-[10px]" style={{ color: '#bbb' }}>박람회 운영 대시보드</p></div>
      </button>

      <nav className="flex-1 py-3 overflow-y-auto">
        <p className="px-5 text-[10px] tracking-widest uppercase mb-1.5" style={{ color: '#ccc' }}>메뉴</p>
        {([['dashboard', '대시보드'], ['in-progress', '작성 중인 박람회'], ['my-products', '내 제품 관리']] as [View, string][]).map(([id, label]) => (
          <button key={id} onClick={() => onNav(id)} className="w-full flex items-center px-5 py-2.5 text-sm text-left transition-all"
            style={{ color: view === id ? '#F06A1A' : '#888', background: view === id ? '#fff5f0' : 'transparent', fontWeight: view === id ? 500 : 400, borderLeft: view === id ? '2px solid #F06A1A' : '2px solid transparent' }}>
            {label}
          </button>
        ))}

        <div className="mx-5 my-3" style={{ borderTop: '1px solid #ebe8e2' }} />
        <p className="px-5 text-[10px] tracking-widest uppercase mb-1.5" style={{ color: '#ccc' }}>바로가기</p>

        <a href="https://www.kotra.or.kr/kh/main/KHMIIO010M.html" target="_blank" rel="noopener noreferrer"
          className="w-full flex items-center gap-2 px-5 py-2 text-xs text-left transition-colors hover:text-orange-500"
          style={{ color: '#888', display: 'flex' }}>
          <span style={{ color: '#F06A1A', fontSize: 11 }}>↗</span> KOTRA 한국관 단체 참가
        </a>
        <a href="https://www.exportvoucher.com" target="_blank" rel="noopener noreferrer"
          className="w-full flex items-center gap-2 px-5 py-2 text-xs text-left transition-colors hover:text-orange-500"
          style={{ color: '#888', display: 'flex' }}>
          <span style={{ color: '#F06A1A', fontSize: 11 }}>↗</span> 정부 수출 지원 사업
        </a>
        <a href="https://www.sbc.or.kr" target="_blank" rel="noopener noreferrer"
          className="w-full flex items-center gap-2 px-5 py-2 text-xs text-left transition-colors hover:text-orange-500"
          style={{ color: '#888', display: 'flex' }}>
          <span style={{ color: '#F06A1A', fontSize: 11 }}>↗</span> 중기부 수출바우처
        </a>
      </nav>

      <div className="px-5 py-4" style={{ borderTop: '1px solid #ebe8e2' }}>
        <p className="text-[10px]" style={{ color: '#ddd' }}>© 2025 SABUZAK Co.</p>
      </div>
    </aside>
  );
}

// ─── World Map (react-simple-maps + world-atlas topojson) ─────────────────────

// Comprehensive ISO numeric → continent group.
// Covers all ~177 features in countries-110m.json.
const CC: Record<number, Continent> = {
  // ── Americas ────────────────────────────────────────────────────────────────
  28:'americas', 32:'americas', 44:'americas', 52:'americas', 60:'americas',
  68:'americas', 76:'americas', 84:'americas', 92:'americas', 124:'americas',
  136:'americas', 152:'americas', 170:'americas', 188:'americas', 192:'americas',
  212:'americas', 214:'americas', 218:'americas', 222:'americas', 238:'americas',
  254:'americas', 304:'americas', 308:'americas', 312:'americas', 320:'americas',
  328:'americas', 332:'americas', 340:'americas', 388:'americas', 474:'americas',
  484:'americas', 500:'americas', 531:'americas', 533:'americas', 534:'americas',
  535:'americas', 558:'americas', 591:'americas', 600:'americas', 604:'americas',
  630:'americas', 659:'americas', 660:'americas', 662:'americas', 663:'americas',
  666:'americas', 670:'americas', 740:'americas', 780:'americas', 796:'americas',
  840:'americas', 850:'americas', 858:'americas', 862:'americas',
  // ── Europe ──────────────────────────────────────────────────────────────────
  8:'europe',   20:'europe',  40:'europe',  56:'europe',  70:'europe',
  100:'europe', 112:'europe', 191:'europe', 196:'europe', 203:'europe',
  208:'europe', 233:'europe', 234:'europe', 246:'europe', 248:'europe',
  250:'europe', 276:'europe', 292:'europe', 300:'europe', 336:'europe',
  348:'europe', 352:'europe', 372:'europe', 380:'europe', 428:'europe',
  438:'europe', 440:'europe', 442:'europe', 470:'europe', 492:'europe',
  498:'europe', 499:'europe', 528:'europe', 578:'europe', 616:'europe',
  620:'europe', 642:'europe', 674:'europe', 688:'europe', 703:'europe',
  705:'europe', 724:'europe', 752:'europe', 756:'europe', 804:'europe',
  807:'europe', 826:'europe', 833:'europe',
  // ── Africa + Middle East ────────────────────────────────────────────────────
  // Middle East
  48:'middleeast', 275:'middleeast', 364:'middleeast', 368:'middleeast',
  376:'middleeast', 400:'middleeast', 414:'middleeast', 422:'middleeast',
  512:'middleeast', 634:'middleeast', 682:'middleeast', 760:'middleeast',
  784:'middleeast', 792:'middleeast', 818:'middleeast', 887:'middleeast',
  // Africa
  12:'middleeast',  24:'middleeast',  72:'middleeast',  86:'middleeast',
  108:'middleeast', 120:'middleeast', 132:'middleeast', 140:'middleeast',
  148:'middleeast', 174:'middleeast', 175:'middleeast', 178:'middleeast',
  180:'middleeast', 204:'middleeast', 226:'middleeast', 231:'middleeast',
  232:'middleeast', 262:'middleeast', 266:'middleeast', 270:'middleeast',
  288:'middleeast', 324:'middleeast', 384:'middleeast', 404:'middleeast',
  426:'middleeast', 430:'middleeast', 434:'middleeast', 450:'middleeast',
  454:'middleeast', 466:'middleeast', 478:'middleeast', 480:'middleeast',
  504:'middleeast', 508:'middleeast', 516:'middleeast', 562:'middleeast',
  566:'middleeast', 638:'middleeast', 646:'middleeast', 654:'middleeast',
  678:'middleeast', 686:'middleeast', 690:'middleeast', 694:'middleeast',
  706:'middleeast', 710:'middleeast', 716:'middleeast', 728:'middleeast',
  729:'middleeast', 732:'middleeast', 748:'middleeast', 768:'middleeast',
  788:'middleeast', 800:'middleeast', 834:'middleeast', 854:'middleeast',
  894:'middleeast',
  // ── Asia ────────────────────────────────────────────────────────────────────
  4:'asia',   31:'asia',  50:'asia',  51:'asia',  64:'asia',  96:'asia',
  104:'asia', 116:'asia', 144:'asia', 156:'asia', 158:'asia', 268:'asia',
  344:'asia', 356:'asia', 360:'asia', 392:'asia', 398:'asia', 408:'asia',
  410:'asia', 417:'asia', 418:'asia', 446:'asia', 458:'asia', 462:'asia',
  496:'asia', 524:'asia', 586:'asia', 608:'asia', 626:'asia', 643:'asia',
  702:'asia', 704:'asia', 762:'asia', 764:'asia', 795:'asia', 860:'asia',
  // ── Oceania ─────────────────────────────────────────────────────────────────
  16:'oceania',  36:'oceania',  90:'oceania', 162:'oceania', 166:'oceania',
  184:'oceania', 242:'oceania', 258:'oceania', 296:'oceania', 316:'oceania',
  334:'oceania', 520:'oceania', 540:'oceania', 548:'oceania', 554:'oceania',
  570:'oceania', 574:'oceania', 580:'oceania', 583:'oceania', 584:'oceania',
  585:'oceania', 598:'oceania', 612:'oceania', 776:'oceania', 798:'oceania',
  876:'oceania', 882:'oceania',
};

function getCountryContinent(numericId: number): Continent | null {
  return CC[numericId] ?? null;
}

const CONTINENT_META: { id: Continent; labelKr: string; color: string }[] = [
  { id: 'americas',   labelKr: '아메리카',     color: '#5cb88b' },
  { id: 'europe',     labelKr: '유럽',         color: '#6b8ec4' },
  { id: 'middleeast', labelKr: '아프리카·중동', color: '#9b6ec2' },
  { id: 'asia',       labelKr: '아시아',       color: '#c4a05a' },
  { id: 'oceania',    labelKr: '오세아니아',   color: '#c07878' },
];

const CONTINENT_COLOR: Record<Continent, string> = Object.fromEntries(
  CONTINENT_META.map(m => [m.id, m.color])
) as Record<Continent, string>;

// ── antimeridian unwrap ────────────────────────────────────────────────────────
// For rings that cross 180°, "unwrap" the outlier side so the whole ring
// stays on one side and projects cleanly (out-of-range coords are SVG-clipped).
//
// Key fix: use the FEATURE's centroid longitude (not per-ring majority) to decide
// which hemisphere is "home". This prevents Aleutian Islands (Americas/western)
// from being unwrapped eastward (+182°E) where they render as a detached green fragment.
//   - Centroid < 0  → western-hemisphere feature → move positive outliers to < -180
//   - Centroid >= 0 → eastern-hemisphere feature  → move negative outliers to > +180
type Pos = GeoJSON.Position;
type Ring = Pos[];

function featureCentroidLon(f: GeoJSON.Feature): number {
  const geom = f.geometry as GeoJSON.Geometry;
  const lons: number[] = [];
  if (geom.type === 'Polygon') {
    geom.coordinates[0].forEach(p => lons.push(p[0]));
  } else if (geom.type === 'MultiPolygon') {
    // Use only the largest polygon's outer ring for centroid estimation
    const largest = geom.coordinates.reduce((a, b) => a[0].length > b[0].length ? a : b);
    largest[0].forEach(p => lons.push(p[0]));
  }
  return lons.length ? lons.reduce((a, b) => a + b, 0) / lons.length : 0;
}

function unwrapRing(ring: Ring, homeIsWest: boolean): Ring {
  const hasCross = ring.some((pt, i) =>
    i > 0 && Math.abs(pt[0] - ring[i - 1][0]) > 180
  );
  if (!hasCross) return ring;
  if (homeIsWest) {
    // Americas etc: any coord > 90° is an antimeridian outlier → pull to negative side
    return ring.map(p => (p[0] > 90 ? [p[0] - 360, p[1]] : p));
  } else {
    // Asia/Russia etc: any coord < -90° is an antimeridian outlier → push to positive side
    return ring.map(p => (p[0] < -90 ? [p[0] + 360, p[1]] : p));
  }
}

function unwrapGeometry(geom: GeoJSON.Geometry, homeIsWest: boolean): GeoJSON.Geometry {
  if (geom.type === 'Polygon') {
    return { type: 'Polygon', coordinates: geom.coordinates.map(r => unwrapRing(r, homeIsWest)) };
  }
  if (geom.type === 'MultiPolygon') {
    return {
      type: 'MultiPolygon',
      coordinates: geom.coordinates.map(poly => poly.map(r => unwrapRing(r, homeIsWest))),
    };
  }
  return geom;
}

// ── 데이터 준비 ───────────────────────────────────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _topo = topoJson as any;
const _allFeatures = feature(_topo, _topo.objects.countries) as unknown as GeoJSON.FeatureCollection;

// 1) 남극 제거
const _noAntarctica = _allFeatures.features.filter(f => f.id !== '010');

// 2) antimeridian을 넘는 좌표를 언랩
//    feature 중심 경도로 서반구(아메리카)/동반구(아시아 등)를 판단해 방향 결정
const _stitched = _noAntarctica.map(f => {
  const centLon = featureCentroidLon(f as GeoJSON.Feature);
  return {
    ...f,
    geometry: unwrapGeometry(f.geometry as GeoJSON.Geometry, centLon < 0),
  };
});

const _filteredFC: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: _stitched,
};

const MAP_W = 800;
const MAP_H = 460;

// ── 투영법 ────────────────────────────────────────────────────────────────────
// unwrapGeometry 덕분에 Russia bbox가 올바르게 동반구에만 위치하므로
// _filteredFC(남극 제거된 실제 대륙)로 fitSize 가능.
// 남극 없는 대륙 범위에 딱 맞게 scale/translate 자동 계산 → 하단 빈 공간 없음.
const millerProjection = geoMiller()
  .rotate([-12, 0, 0])
  .fitSize([MAP_W, MAP_H], _filteredFC);

function WorldMap({ onSelect }: { onSelect: (c: Continent) => void }) {
  const [hoveredGroup, setHoveredGroup] = useState<Continent | null>(null);
  const [active, setActive] = useState<Continent | null>(null);

  const handleGeoClick = (geo: { id?: string | number }) => {
    const continent = getCountryContinent(Number(geo.id));
    if (!continent) return;
    const next = active === continent ? null : continent;
    setActive(next);
    onSelect(continent);
  };

  const fairCount = (c: Continent) => fairs.filter(f => f.continent === c).length;

  return (
    <div style={{ borderRadius: 8, overflow: 'hidden', background: 'transparent', padding: '4px 8px' }}>
      <ComposableMap
        projection={millerProjection}
        width={MAP_W}
        height={MAP_H}
        style={{ width: '100%', height: 'auto', display: 'block', background: 'transparent' }}
      >
        <Geographies geography={_filteredFC}>
          {({ geographies }) =>
            geographies.map(geo => {
                const continent = getCountryContinent(Number(geo.id));
                const isGroupHov = continent !== null && hoveredGroup === continent;
                const isAct = continent !== null && active === continent;
                let fill = 'transparent';
                if (continent) {
                  const base = CONTINENT_COLOR[continent];
                  fill = isAct ? base : isGroupHov ? base + 'ee' : base + '88';
                }

                return (
                  <Geography
                    key={geo.rsmKey}
                    geography={geo}
                    fill={fill}
                    stroke="none"
                    strokeWidth={0}
                    onMouseEnter={() => { if (continent) setHoveredGroup(continent); }}
                    onMouseLeave={() => setHoveredGroup(null)}
                    onClick={() => handleGeoClick(geo)}
                    style={{ cursor: continent ? 'pointer' : 'default', outline: 'none', transition: 'fill 0.12s' }}
                  />
                );
              })
          }
        </Geographies>
      </ComposableMap>

      {/* Legend with fair counts */}
      <div className="flex items-center justify-center gap-5 px-5 py-2.5 flex-wrap" style={{ background: '#fff', borderTop: '1px solid #ebe8e2' }}>
        {CONTINENT_META.map(m => (
          <button key={m.id}
            onClick={() => {
              const next = active === m.id ? null : m.id;
              setActive(next);
              onSelect(m.id);
            }}
            className="flex items-center gap-1.5 text-xs transition-all hover:opacity-70"
            style={{ color: active === m.id ? m.color : '#666', fontWeight: active === m.id ? 700 : 400 }}>
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: m.color }} />
            {m.labelKr}
            <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, background: active === m.id ? m.color : '#eee', color: active === m.id ? '#fff' : '#888', borderRadius: 10, padding: '0 5px', lineHeight: '14px' }}>
              {fairCount(m.id)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
const COUNTRY_LIST: { name: string; flag: string; continent: Continent }[] = [
  { name: '일본',   flag: '🇯🇵', continent: 'asia' },
  { name: '태국',   flag: '🇹🇭', continent: 'asia' },
  { name: '독일',   flag: '🇩🇪', continent: 'europe' },
  { name: '프랑스', flag: '🇫🇷', continent: 'europe' },
  { name: '미국',   flag: '🇺🇸', continent: 'americas' },
  { name: 'UAE',    flag: '🇦🇪', continent: 'middleeast' },
  { name: '호주',   flag: '🇦🇺', continent: 'oceania' },
];


const QUICK_HS = [
  { label: '약과', code: '1905.90' },
  { label: '유과', code: '1904.10' },
  { label: '누룽지칩', code: '1904.10' },
  { label: '김부각', code: '2106.90' },
  { label: '고구마스틱', code: '2005.99' },
];

function Dashboard({ onSelectFair, onSelectCountry, onAddProduct }: {
  onSelectFair: (f: Fair) => void;
  onSelectCountry: (country: string) => void;
  onAddProduct: (p: { name: string; hsCode: string; ingredients: string }) => void;
}) {
  const [filteredContinent, setFilteredContinent] = useState<Continent | null>(null);
  const [showDropdown, setShowDropdown] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [form, setForm] = useState({ name: '', hsCode: '', ingredients: '' });

  const saveProduct = () => {
    if (!form.name.trim() || !form.hsCode.trim()) return;
    onAddProduct(form);
    setForm({ name: '', hsCode: '', ingredients: '' });
    setShowAddModal(false);
  };

  const mapList = filteredContinent
    ? sortFairsByDate(fairs.filter(f => f.continent === filteredContinent))
    : sortFairsByDate(fairs);

  return (
    <div className="flex-1 overflow-y-auto" onClick={() => showDropdown && setShowDropdown(false)}>
      {/* Header */}
      <div className="px-8 py-5 flex items-start justify-between" style={{ borderBottom: '1px solid #ebe8e2' }}>
        <div>
          <h1 className="text-lg font-semibold" style={{ color: '#1a1a1a' }}>박람회 운영 대시보드</h1>
          <p className="text-xs mt-0.5" style={{ color: '#999' }}>지도에서 핀을 클릭하거나 국가를 선택해 시장 정보를 확인하세요</p>
        </div>
        {/* Header buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium hover:opacity-85 transition-opacity"
            style={{ background: '#fff', color: '#555', border: '1px solid #e0ddd8', borderRadius: 3 }}
          >
            + 제품 추가하기
          </button>
          {/* Country select dropdown */}
          <div className="relative" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => setShowDropdown(p => !p)}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium hover:opacity-85 transition-opacity"
            style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}
          >
            국가 선택
            <span className="text-[10px] opacity-70">{showDropdown ? '▲' : '▼'}</span>
          </button>
          {showDropdown && (
            <div
              className="absolute right-0 top-full mt-1 z-50"
              style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4, width: 176, maxHeight: 280, overflowY: 'auto', boxShadow: '0 4px 20px rgba(0,0,0,0.12)' }}
            >
              <div className="px-3 py-2" style={{ borderBottom: '1px solid #f5f3ee' }}>
                <p className="text-[10px] tracking-wider uppercase" style={{ color: '#bbb' }}>국가 선택</p>
              </div>
              {COUNTRY_LIST.map((c, i) => (
                <button
                  key={c.name}
                  onClick={() => { setShowDropdown(false); onSelectCountry(c.name); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors hover:bg-orange-50"
                  style={{ borderBottom: i < COUNTRY_LIST.length - 1 ? '1px solid #f9f7f5' : 'none' }}
                >
                  <span className="text-base">{c.flag}</span>
                  <span style={{ color: '#1a1a1a' }}>{c.name}</span>
                  <span className="ml-auto text-[10px]" style={{ color: CONTINENT_COLOR[c.continent] }}>●</span>
                </button>
              ))}
            </div>
          )}
          </div>
        </div>
      </div>

      {/* World map + fair list */}
      <div className="pt-10 px-8 pb-8 grid gap-6">
        <WorldMap onSelect={c => setFilteredContinent(prev => prev === c ? null : c)} />
        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs" style={{ color: '#999' }}>
              {filteredContinent ? `${continents.find(c => c.id === filteredContinent)?.labelKr} 박람회` : '전체 박람회'}
              <span className="ml-1.5" style={{ fontFamily: 'JetBrains Mono, monospace' }}>({mapList.length}건)</span>
              <span className="ml-2" style={{ color: '#ccc' }}>최신순</span>
            </p>
            {filteredContinent && (
              <button onClick={() => setFilteredContinent(null)} className="text-xs" style={{ color: '#aaa' }}>전체 보기</button>
            )}
          </div>
          <div className="flex flex-col gap-2">
            {mapList.map(f => <FairCard key={f.id} fair={f} onClick={() => onSelectFair(f)} />)}
          </div>
        </div>
      </div>

      {/* ── Add Product Modal ── */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.35)' }}
          onClick={() => setShowAddModal(false)}
        >
          <div
            className="w-full max-w-md p-6"
            style={{ background: '#fff', borderRadius: 6, boxShadow: '0 8px 40px rgba(0,0,0,0.18)' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold" style={{ color: '#1a1a1a' }}>제품 추가하기</h2>
              <button onClick={() => setShowAddModal(false)} className="text-lg leading-none hover:opacity-60" style={{ color: '#aaa' }}>×</button>
            </div>

            <div className="grid gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium" style={{ color: '#555' }}>제품명 <span style={{ color: '#F06A1A' }}>*</span></label>
                <input
                  value={form.name}
                  onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
                  placeholder="예: 사부작 약과"
                  className="px-3 py-2.5 text-sm outline-none"
                  style={{ background: '#fafaf8', border: '1px solid #e0ddd8', borderRadius: 3 }}
                  onFocus={e => (e.target.style.borderColor = '#F06A1A')}
                  onBlur={e => (e.target.style.borderColor = '#e0ddd8')}
                  autoFocus
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium" style={{ color: '#555' }}>HS 코드 <span style={{ color: '#F06A1A' }}>*</span></label>
                <input
                  value={form.hsCode}
                  onChange={e => setForm(p => ({ ...p, hsCode: e.target.value }))}
                  placeholder="예: 1905.90"
                  className="px-3 py-2.5 text-sm outline-none"
                  style={{ background: '#fafaf8', border: '1px solid #e0ddd8', borderRadius: 3, fontFamily: 'JetBrains Mono, monospace' }}
                  onFocus={e => (e.target.style.borderColor = '#F06A1A')}
                  onBlur={e => (e.target.style.borderColor = '#e0ddd8')}
                />
                <div className="flex flex-wrap gap-1.5 mt-0.5">
                  {QUICK_HS.map(q => (
                    <button
                      key={q.label + q.code}
                      onClick={() => setForm(p => ({ ...p, name: p.name || q.label, hsCode: q.code }))}
                      className="text-[11px] px-2 py-0.5 hover:border-orange-400 transition-colors"
                      style={{ border: '1px solid #e0ddd8', borderRadius: 2, color: '#888' }}
                    >
                      {q.label} <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#bbb' }}>{q.code}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium" style={{ color: '#555' }}>성분표</label>
                <textarea
                  value={form.ingredients}
                  onChange={e => setForm(p => ({ ...p, ingredients: e.target.value }))}
                  placeholder="예: 밀가루, 참기름, 꿀, 설탕..."
                  rows={3}
                  className="px-3 py-2.5 text-sm outline-none resize-none"
                  style={{ background: '#fafaf8', border: '1px solid #e0ddd8', borderRadius: 3 }}
                  onFocus={e => (e.target.style.borderColor = '#F06A1A')}
                  onBlur={e => (e.target.style.borderColor = '#e0ddd8')}
                />
              </div>
            </div>

            <div className="flex gap-2 mt-6">
              <button
                onClick={() => setShowAddModal(false)}
                className="flex-1 py-2.5 text-sm hover:opacity-80"
                style={{ background: '#f5f3ee', color: '#666', borderRadius: 3 }}
              >
                취소
              </button>
              <button
                onClick={saveProduct}
                disabled={!form.name.trim() || !form.hsCode.trim()}
                className="flex-1 py-2.5 text-sm font-medium hover:opacity-85 transition-opacity"
                style={{ background: '#F06A1A', color: '#fff', borderRadius: 3, opacity: (!form.name.trim() || !form.hsCode.trim()) ? 0.4 : 1 }}
              >
                추가하기
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Country Market View ───────────────────────────────────────────────────────
function CountryMarketView({ country, products, onBack, onSelectFair, onGoToFairs, onGoToProducts }: {
  country: string;
  products: Product[];
  onBack: () => void;
  onSelectFair: (f: Fair) => void;
  onGoToFairs: () => void;
  onGoToProducts: () => void;
}) {
  const [tab, setTab] = useState<'market' | 'trends' | 'hs-export'>('market');

  const info = COUNTRY_LIST.find(c => c.name === country);
  const refFair = fairs.find(f => f.country === country);
  const ctData  = comtradeData[country] ?? [];
  const trData  = trendsData[country]   ?? [];
  const compData= competitorData[country] ?? [];
  const months = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'];
  const accentColor = info ? CONTINENT_COLOR[info.continent] : '#F06A1A';

  const tabs = [
    { id: 'market'    as const, label: '시장 개요' },
    { id: 'trends'    as const, label: '트렌드 조사' },
    { id: 'hs-export' as const, label: 'HS코드 & 수출 주의사항' },
  ];

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Header */}
      <div className="px-8 py-5" style={{ background: '#fff', borderBottom: '1px solid #ebe8e2' }}>
        <button onClick={onBack} className="text-xs mb-2 block hover:text-black transition-colors" style={{ color: '#aaa' }}>← 뒤로</button>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold" style={{ color: '#1a1a1a' }}>{info?.flag} {country} 시장 분석</h1>
            <div className="flex items-center gap-2 mt-2">
              {products.map(p => (
                <span key={p.id} className="text-[11px] px-2 py-0.5" style={{ background: '#f5f3ee', color: '#666', borderRadius: 2 }}>{p.name}</span>
              ))}
              {products.length === 0 && (
                <span className="text-[11px]" style={{ color: '#bbb' }}>제품 미등록</span>
              )}
            </div>
          </div>
          <button
            onClick={onGoToFairs}
            className="shrink-0 flex items-center gap-2 px-5 py-2.5 text-sm font-medium hover:opacity-85 transition-opacity"
            style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}
          >
            {country} 박람회 찾기 →
          </button>
        </div>

      </div>

      {/* Tabs */}
      <div className="flex" style={{ background: '#fff', borderBottom: '1px solid #ebe8e2' }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} className="px-5 py-3 text-xs transition-colors whitespace-nowrap"
            style={{ color: tab === t.id ? '#F06A1A' : '#999', borderBottom: tab === t.id ? '2px solid #F06A1A' : '2px solid transparent', fontWeight: tab === t.id ? 500 : 400 }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-8" style={{ background: '#f7f6f3' }}>
        {/* ── 시장 개요 ── */}
        {tab === 'market' && (
          products.length === 0 ? <NoProductsPrompt onGo={onGoToProducts} /> :
          <div className="grid gap-4">
            {refFair && (
              <div className="flex items-center gap-4 px-5 py-4" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                <div className="w-10 h-10 flex items-center justify-center text-lg shrink-0" style={{ background: '#fdf5ec', borderRadius: 4 }}>{refFair.exchangeRate.symbol}</div>
                <div className="flex-1">
                  <p className="text-[10px]" style={{ color: '#aaa' }}>현재 환율 ({refFair.exchangeRate.currency} → KRW)</p>
                  <p className="text-sm font-semibold mt-0.5" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{refFair.exchangeRate.formatted}</p>
                </div>
                <p className="text-[10px]" style={{ color: '#ccc' }}>참고용 · 실시간 아님</p>
              </div>
            )}
            {ctData.length > 0 && (
              <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                <div className="flex items-center gap-2 mb-3">
                  <p className="text-xs font-medium" style={{ color: '#1a1a1a' }}>한국 식품 수입액 — {country}</p>
                  <span className="text-[10px] px-2 py-0.5" style={{ background: '#f0f5ff', color: '#5577aa', borderRadius: 2 }}>UN Comtrade API (목업)</span>
                </div>
                <div className="grid grid-cols-3 gap-3 mb-2">
                  {ctData.map((d, i) => {
                    const prev = ctData[i - 1];
                    const growth = prev ? (((d.value - prev.value) / prev.value) * 100).toFixed(1) : null;
                    return (
                      <div key={d.year} className="px-3 py-2.5" style={{ background: '#fafaf8', border: '1px solid #ebe8e2', borderRadius: 3 }}>
                        <p className="text-[10px]" style={{ color: '#aaa' }}>{d.year}년</p>
                        <p className="text-xl font-semibold" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>${d.value}M</p>
                        {growth && <p className="text-[11px] mt-0.5" style={{ color: '#3a9a5c' }}>▲ {growth}%</p>}
                      </div>
                    );
                  })}
                </div>
                <p className="text-[11px]" style={{ color: '#ccc' }}>HS 1904·1905·2106 카테고리 합산 · 실제 서비스에서 자동 갱신 예정</p>
              </div>
            )}
            {compData.length > 0 && (
              <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                <p className="text-xs font-medium mb-3" style={{ color: '#1a1a1a' }}>경쟁 제품 및 가격 분석 — {country}</p>
                <div className="grid gap-2">
                  {compData.map((c, i) => (
                    <div key={i} className="flex items-center gap-3 px-3 py-2" style={{ background: '#fafaf8', border: '1px solid #ebe8e2', borderRadius: 3 }}>
                      <span className="text-[10px] font-mono w-4 shrink-0" style={{ color: '#ccc' }}>{i + 1}</span>
                      <div className="flex-1">
                        <span className="text-xs font-medium" style={{ color: '#1a1a1a' }}>{c.name}</span>
                        <span className="text-[11px] ml-2" style={{ color: '#aaa' }}>{c.origin}</span>
                      </div>
                      <span className="text-xs font-mono shrink-0" style={{ color: '#555', fontFamily: 'JetBrains Mono, monospace' }}>{c.price}</span>
                      <span className="text-[11px] shrink-0" style={{ color: '#aaa', maxWidth: 200, textAlign: 'right' }}>{c.note}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 트렌드 조사 ── */}
        {tab === 'trends' && (
          products.length === 0 ? <NoProductsPrompt onGo={onGoToProducts} /> :
          <div className="grid gap-4">
            {trData.length > 0 && (
              <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-medium" style={{ color: '#1a1a1a' }}>검색 관심도 — "Korean snack" ({country})</p>
                    <span className="text-[10px] px-2 py-0.5" style={{ background: '#fff0eb', color: '#F06A1A', borderRadius: 2 }}>Google Trends / pytrends (목업)</span>
                  </div>
                  <span className="text-xs font-mono" style={{ color: '#3a9a5c', fontFamily: 'JetBrains Mono, monospace' }}>
                    {trData[trData.length - 1]} / 100 ▲{trData[trData.length - 1] - trData[0]}pts
                  </span>
                </div>
                <Sparkline data={trData} color={accentColor} />
                <div className="flex justify-between mt-1">
                  {[0,2,4,6,8,10].map(i => <span key={i} className="text-[10px]" style={{ color: '#ccc' }}>{months[i]}</span>)}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── HS코드 & 수출 주의사항 ── */}
        {tab === 'hs-export' && (
          products.length === 0 ? <NoProductsPrompt onGo={onGoToProducts} /> :
          <div className="grid gap-4">
            <p className="text-xs" style={{ color: '#999' }}>등록 제품의 {country} 수출 HS코드 및 관세율</p>
            {products.map(p => {
              const tariffInfo = hsTariffData[p.hsCode]?.[country];
              return (
                <div key={p.id} className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <div className="flex items-start justify-between gap-4 mb-2">
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-semibold px-2.5 py-1" style={{ background: '#f5f3ee', color: '#555', borderRadius: 3 }}>{p.name}</span>
                      <p className="text-sm font-semibold" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{p.hsCode}</p>
                    </div>
                    {tariffInfo && (
                      <div className="text-right">
                        <p className="text-[10px]" style={{ color: '#aaa' }}>관세율</p>
                        <p className="text-lg font-semibold" style={{ color: tariffInfo.tariff === '0%' ? '#3a9a5c' : tariffInfo.tariff.startsWith('1') ? '#cc5555' : '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{tariffInfo.tariff}</p>
                      </div>
                    )}
                  </div>
                  {tariffInfo
                    ? <>
                        <p className="text-xs mb-2" style={{ color: '#aaa' }}>{tariffInfo.note}</p>
                        <div className="flex flex-wrap gap-1.5">
                          <span className="text-[10px]" style={{ color: '#aaa' }}>필요 인증:</span>
                          {tariffInfo.certification.map(c => <span key={c} className="text-[10px] px-2 py-0.5" style={{ background: '#f5f5f5', color: '#666', border: '1px solid #e8e8e8', borderRadius: 2 }}>{c}</span>)}
                        </div>
                      </>
                    : <p className="text-xs" style={{ color: '#aaa' }}>{country}에 대한 이 HS코드의 관세 정보가 없습니다. 관세청에서 직접 확인해 주세요.</p>
                  }
                  {p.ingredients && <p className="text-xs mt-2 pt-2" style={{ color: '#bbb', borderTop: '1px solid #f0ede8' }}>등록 성분: {p.ingredients}</p>}
                </div>
              );
            })}
            {refFair && (
              <>
                <p className="text-xs mt-2" style={{ color: '#999' }}>수출 주의사항</p>
                {refFair.exportNotes.map((n, i) => {
                  const cfg = { warning: { bg: '#fff8f8', border: '#f5d5d5', badge: '#cc5555', label: '주의' }, required: { bg: '#fffaf7', border: '#f5d8c0', badge: '#F06A1A', label: '필수' }, info: { bg: '#f5f8ff', border: '#d5e0f5', badge: '#5577aa', label: '정보' } }[n.type];
                  return (
                    <div key={i} className="p-5" style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: 4 }}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-[10px] px-1.5 py-0.5" style={{ background: `${cfg.badge}18`, color: cfg.badge, border: `1px solid ${cfg.badge}40`, borderRadius: 2 }}>{cfg.label}</span>
                        <h3 className="text-sm font-semibold" style={{ color: '#1a1a1a' }}>{n.title}</h3>
                      </div>
                      <p className="text-sm mb-2" style={{ color: '#555' }}>{n.description}</p>
                      <p className="text-[11px] font-mono" style={{ color: '#bbb', fontFamily: 'JetBrains Mono, monospace' }}>ref: {n.reference}</p>
                    </div>
                  );
                })}
              </>
            )}
          </div>
        )}

      </div>
    </div>
  );
}

// ─── Country Fairs View ───────────────────────────────────────────────────────
function CountryFairsView({ country, onBack, onSelectFair }: {
  country: string;
  onBack: () => void;
  onSelectFair: (f: Fair) => void;
}) {
  const info = COUNTRY_LIST.find(c => c.name === country);
  const countryFairs = sortFairsByDate(fairs.filter(f => f.country === country));

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-8 py-5" style={{ background: '#fff', borderBottom: '1px solid #ebe8e2' }}>
        <button onClick={onBack} className="text-xs mb-2 block hover:text-black transition-colors" style={{ color: '#aaa' }}>← 시장 분석으로</button>
        <h1 className="text-lg font-semibold" style={{ color: '#1a1a1a' }}>{info?.flag} {country} 박람회</h1>
        <p className="text-xs mt-0.5" style={{ color: '#999' }}>
          {countryFairs.length}건 · 최신순
        </p>
      </div>
      <div className="p-8">
        {countryFairs.length === 0
          ? <p className="text-sm text-center py-16" style={{ color: '#bbb' }}>등록된 박람회가 없습니다.</p>
          : <div className="flex flex-col gap-2">
              {countryFairs.map(f => <FairCard key={f.id} fair={f} onClick={() => onSelectFair(f)} />)}
            </div>
        }
      </div>
    </div>
  );
}

// ─── Fair Card ────────────────────────────────────────────────────────────────
function FairCard({ fair, onClick }: { fair: Fair; onClick: () => void }) {
  const [hov, setHov] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      className="w-full text-left transition-all overflow-hidden"
      style={{ background: hov ? '#fffaf7' : '#fff', border: '1px solid', borderColor: hov ? '#F06A1A60' : '#ebe8e2', borderRadius: 4 }}>
      <div className="flex items-stretch">
        {/* Thumbnail */}
        <div className="shrink-0 w-24 relative" style={{ minHeight: 76 }}>
          <img
            src={`${fair.photoUrl.split('?')[0]}?w=192&h=160&fit=crop&auto=format`}
            alt={fair.name}
            className="absolute inset-0 w-full h-full object-cover"
            style={{ borderRadius: '3px 0 0 3px' }}
          />
        </div>
        {/* Content */}
        <div className="flex flex-1 items-start justify-between gap-4 px-4 py-3 min-w-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] px-1.5 py-0.5" style={{ background: '#f5f3ee', color: '#888', borderRadius: 2 }}>{fair.category}</span>
              <span className="text-[10px]" style={{ color: '#ccc' }}>{continents.find(c => c.id === fair.continent)?.labelKr}</span>
            </div>
            <h3 className="text-sm font-semibold" style={{ color: '#1a1a1a' }}>{fair.name}</h3>
            <p className="text-xs mt-0.5" style={{ color: '#888' }}>{fair.country} · {fair.city} · {fair.venue}</p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-xs font-mono font-medium" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{fair.dates}</p>
            <p className="text-[11px] mt-1" style={{ color: '#aaa' }}>마감: {fair.deadline}</p>
          </div>
        </div>
      </div>
    </button>
  );
}

// ─── In-Progress ──────────────────────────────────────────────────────────────
function InProgressView({ trackedFairs, generatedConcepts, onSelectFair }: {
  trackedFairs: string[]; generatedConcepts: Record<string, GeneratedConcept>; onSelectFair: (f: Fair) => void;
}) {
  const tracked = sortFairsByDate(fairs.filter(f => trackedFairs.includes(f.id)));
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-8 py-6" style={{ borderBottom: '1px solid #ebe8e2' }}>
        <h1 className="text-lg font-semibold" style={{ color: '#1a1a1a' }}>작성 중인 박람회</h1>
        <p className="text-xs mt-0.5" style={{ color: '#999' }}>컨셉 기획이 진행 중인 박람회</p>
      </div>
      <div className="p-8">
        {tracked.length === 0
          ? <div className="text-center py-20"><p className="text-sm" style={{ color: '#bbb' }}>박람회 상세에서 부스 컨셉 기획을 시작하면 여기에 표시됩니다.</p></div>
          : <div className="flex flex-col gap-2">
              {tracked.map(f => (
                <div key={f.id} className="flex items-center gap-4 px-5 py-4" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <div className="flex-1">
                    <h3 className="text-sm font-semibold" style={{ color: '#1a1a1a' }}>{f.name}</h3>
                    <p className="text-xs mt-0.5" style={{ color: '#888' }}>{f.country} · {f.dates}</p>
                  </div>
                  <span className="text-[11px] px-2 py-0.5" style={{ background: generatedConcepts[f.id] ? '#edf7f0' : '#f5f5f5', color: generatedConcepts[f.id] ? '#3a9a5c' : '#aaa', border: `1px solid ${generatedConcepts[f.id] ? '#b8e4c8' : '#e8e8e8'}`, borderRadius: 2 }}>
                    {generatedConcepts[f.id] ? '✓ 컨셉 완료' : '컨셉 작성 중'}
                  </span>
                  <button onClick={() => onSelectFair(f)} className="text-xs px-3 py-1.5 hover:opacity-80" style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}>계속 작성</button>
                </div>
              ))}
            </div>
        }
      </div>
    </div>
  );
}

// ─── My Products ──────────────────────────────────────────────────────────────
function MyProductsView({ products, checkedIds, onAdd, onDelete, onToggleCheck }: {
  products: Product[];
  checkedIds: string[];
  onAdd: (p: Omit<Product, 'id'>) => void;
  onDelete: (id: string) => void;
  onToggleCheck: (id: string) => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', hsCode: '', ingredients: '' });

  const save = () => {
    if (!form.name.trim() || !form.hsCode.trim()) return;
    onAdd(form);
    setForm({ name: '', hsCode: '', ingredients: '' });
    setShowForm(false);
  };

  const quickHS = [
    { label: '약과', code: '1905.90' },
    { label: '유과', code: '1904.10' },
    { label: '누룽지칩', code: '1904.10' },
    { label: '김부각', code: '2106.90' },
    { label: '고구마스틱', code: '2005.99' },
  ];

  const checkedCount = products.filter(p => checkedIds.includes(p.id)).length;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-8 py-6 flex items-start justify-between" style={{ borderBottom: '1px solid #ebe8e2' }}>
        <div>
          <h1 className="text-lg font-semibold" style={{ color: '#1a1a1a' }}>내 제품 관리</h1>
          <p className="text-xs mt-0.5" style={{ color: '#999' }}>체크된 제품만 시장 분석·부스 컨셉에 반영됩니다</p>
        </div>
        <div className="flex items-center gap-2">
          {products.length > 0 && (
            <span className="text-xs px-2.5 py-1" style={{ background: '#fff5f0', color: '#F06A1A', border: '1px solid #f5d8c0', borderRadius: 20 }}>
              {checkedCount}/{products.length}개 선택됨
            </span>
          )}
          <button onClick={() => setShowForm(true)} className="text-xs px-4 py-2 hover:opacity-80" style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}>+ 제품 추가</button>
        </div>
      </div>

      <div className="p-8 grid gap-3">
        {showForm && (
          <div className="p-5" style={{ background: '#fff', border: '1px solid #F06A1A40', borderRadius: 4 }}>
            <p className="text-xs font-medium mb-4" style={{ color: '#1a1a1a' }}>새 제품 등록</p>
            <div className="grid gap-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-[11px]" style={{ color: '#888' }}>제품명 *</label>
                  <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} placeholder="예: 사부작 약과" className="px-3 py-2 text-sm outline-none" style={{ background: '#fafaf8', border: '1px solid #e0ddd8', borderRadius: 3 }} onFocus={e => e.target.style.borderColor = '#F06A1A'} onBlur={e => e.target.style.borderColor = '#e0ddd8'} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[11px]" style={{ color: '#888' }}>HS코드 *</label>
                  <input value={form.hsCode} onChange={e => setForm(p => ({ ...p, hsCode: e.target.value }))} placeholder="예: 1905.90" className="px-3 py-2 text-sm outline-none" style={{ background: '#fafaf8', border: '1px solid #e0ddd8', borderRadius: 3, fontFamily: 'JetBrains Mono, monospace' }} onFocus={e => e.target.style.borderColor = '#F06A1A'} onBlur={e => e.target.style.borderColor = '#e0ddd8'} />
                  <div className="flex gap-1 mt-1 flex-wrap">
                    {quickHS.map(q => (
                      <button key={q.label + q.code} onClick={() => setForm(p => ({ ...p, name: p.name || q.label, hsCode: q.code }))}
                        className="text-[10px] px-1.5 py-0.5 transition-all hover:border-orange-400" style={{ border: '1px solid #e0ddd8', borderRadius: 2, color: '#888' }}>
                        {q.label} {q.code}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[11px]" style={{ color: '#888' }}>성분표</label>
                <textarea value={form.ingredients} onChange={e => setForm(p => ({ ...p, ingredients: e.target.value }))} placeholder="예: 밀가루, 꿀, 참기름, 계피..." rows={3} className="px-3 py-2 text-sm outline-none resize-none" style={{ background: '#fafaf8', border: '1px solid #e0ddd8', borderRadius: 3 }} onFocus={e => e.target.style.borderColor = '#F06A1A'} onBlur={e => e.target.style.borderColor = '#e0ddd8'} />
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowForm(false)} className="text-xs px-3 py-1.5" style={{ border: '1px solid #e0ddd8', color: '#888', borderRadius: 3 }}>취소</button>
                <button onClick={save} className="text-xs px-4 py-1.5 hover:opacity-80" style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}>저장</button>
              </div>
            </div>
          </div>
        )}

        {products.length === 0 && !showForm && (
          <div className="text-center py-16">
            <p className="text-sm" style={{ color: '#bbb' }}>등록된 제품이 없습니다. 제품을 추가해 주세요.</p>
          </div>
        )}

        {products.map(p => {
          const checked = checkedIds.includes(p.id);
          return (
            <div key={p.id} className="px-5 py-4 flex items-center gap-4 transition-all"
              style={{ background: '#fff', border: `1px solid ${checked ? '#F06A1A30' : '#ebe8e2'}`, borderRadius: 4 }}>
              {/* Checkbox */}
              <button
                onClick={() => onToggleCheck(p.id)}
                className="shrink-0 w-5 h-5 rounded flex items-center justify-center transition-all"
                style={{ background: checked ? '#F06A1A' : '#fff', border: `2px solid ${checked ? '#F06A1A' : '#d0ccc8'}` }}
              >
                {checked && <span className="text-white text-[11px] leading-none font-bold">✓</span>}
              </button>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <h3 className="text-sm font-semibold" style={{ color: checked ? '#1a1a1a' : '#999' }}>{p.name}</h3>
                  <span className="text-xs px-2 py-0.5" style={{ background: '#f5f3ee', color: '#666', borderRadius: 2, fontFamily: 'JetBrains Mono, monospace' }}>{p.hsCode}</span>
                  {!checked && <span className="text-[10px] px-1.5 py-0.5" style={{ background: '#f5f5f5', color: '#bbb', borderRadius: 2 }}>미선택</span>}
                </div>
                {p.ingredients && <p className="text-xs" style={{ color: '#bbb' }}>성분: {p.ingredients}</p>}
              </div>
              <button onClick={() => onDelete(p.id)} className="text-xs transition-colors hover:text-red-500 shrink-0" style={{ color: '#ddd' }}>삭제</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Fair Detail ──────────────────────────────────────────────────────────────
function FairDetail({ fair, products, onBack, onGoToConcept, onTrack, onGoToProducts, fromCountry }: {
  fair: Fair; products: Product[]; onBack: () => void; onGoToConcept: () => void;
  onTrack: (id: string) => void; onGoToProducts: () => void; fromCountry?: string | null;
}) {
  const [tab, setTab] = useState<FairTab>('overview');

  // When arriving from country market page, show only overview tab
  const tabs: { id: FairTab; label: string }[] = fromCountry
    ? [{ id: 'overview', label: '박람회 개요' }]
    : [
        { id: 'overview',  label: '박람회 개요' },
        { id: 'market',    label: '시장 개요' },
        { id: 'trends',    label: '트렌드 조사' },
        { id: 'hs-export', label: 'HS코드 & 수출 주의사항' },
      ];

  const ctData = comtradeData[fair.country] ?? [];
  const trData = trendsData[fair.country] ?? Array(12).fill(50);
  const compData = competitorData[fair.country] ?? [];
  const months = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'];

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Hero */}
      <div className="relative" style={{ height: 190, background: '#e8e4dc', overflow: 'hidden' }}>
        <img src={fair.photoUrl} alt={fair.name} className="w-full h-full object-cover" />
        <div className="absolute inset-0" style={{ background: 'linear-gradient(to bottom, transparent 35%, rgba(0,0,0,0.6))' }} />
        <div className="absolute bottom-0 left-0 right-0 px-8 pb-4">
          <p className="text-white text-lg font-semibold">{fair.name}</p>
          <p className="text-white text-xs mt-0.5 opacity-75">{fair.country} · {fair.city} · {fair.venue}</p>
        </div>
        <button onClick={onBack} className="absolute top-4 left-6 text-xs px-2.5 py-1 hover:opacity-80" style={{ background: 'rgba(0,0,0,0.45)', color: '#fff', borderRadius: 3 }}>← 뒤로</button>
      </div>

      {/* Tab bar */}
      <div className="flex items-center justify-between pr-6" style={{ background: '#fff', borderBottom: '1px solid #ebe8e2' }}>
        <div className="flex">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} className="px-4 py-3 text-xs transition-colors whitespace-nowrap"
              style={{ color: tab === t.id ? '#F06A1A' : '#999', borderBottom: tab === t.id ? '2px solid #F06A1A' : '2px solid transparent', fontWeight: tab === t.id ? 500 : 400 }}>
              {t.label}
            </button>
          ))}
        </div>
        <button onClick={() => { onTrack(fair.id); onGoToConcept(); }} className="text-xs px-3 py-1.5 hover:opacity-80 whitespace-nowrap" style={{ background: '#F06A1A', color: '#fff', borderRadius: 3 }}>부스 컨셉 기획 →</button>
      </div>

      <div className="p-8" style={{ background: '#f7f6f3' }}>
        {/* OVERVIEW */}
        {tab === 'overview' && (
          <div className="grid gap-4">
            <div className="grid grid-cols-3 gap-3">
              {[['개최지', `${fair.country} · ${fair.city}`], ['개최장소', fair.venue], ['규모', fair.scale], ['카테고리', fair.category], ['연간 방문객', fair.visitors], ['참가 기업', fair.exhibitors]].map(([label, value]) => (
                <div key={label} className="px-4 py-3" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <p className="text-[10px] mb-1" style={{ color: '#aaa' }}>{label}</p>
                  <p className="text-sm font-medium" style={{ color: '#1a1a1a' }}>{value}</p>
                </div>
              ))}
            </div>
            <div className="px-5 py-4" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
              <p className="text-[10px] mb-2" style={{ color: '#aaa' }}>공식 소개</p>
              <p className="text-sm leading-relaxed" style={{ color: '#555' }}>{fair.officialDescription}</p>
            </div>
            <div className="flex gap-3">
              <div className="flex-1 px-4 py-3" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                <p className="text-[10px] mb-1" style={{ color: '#aaa' }}>신청 마감일</p>
                <p className="text-sm font-mono font-medium" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{fair.deadline}</p>
              </div>
              <div className="flex-1 px-4 py-3" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                <p className="text-[10px] mb-1" style={{ color: '#aaa' }}>공식 웹사이트</p>
                <p className="text-sm font-mono" style={{ color: '#5577aa' }}>{fair.website}</p>
              </div>
            </div>
          </div>
        )}

        {/* MARKET OVERVIEW */}
        {tab === 'market' && (
          products.length === 0
            ? <NoProductsPrompt onGo={onGoToProducts} />
            : <div className="grid gap-4">
                {/* Exchange rate */}
                <div className="flex items-center gap-4 px-5 py-4" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <div className="w-10 h-10 flex items-center justify-center text-lg shrink-0" style={{ background: '#fdf5ec', borderRadius: 4 }}>{fair.exchangeRate.symbol}</div>
                  <div className="flex-1">
                    <p className="text-[10px]" style={{ color: '#aaa' }}>현재 환율 ({fair.exchangeRate.currency} → KRW)</p>
                    <p className="text-sm font-semibold mt-0.5" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{fair.exchangeRate.formatted}</p>
                  </div>
                  <p className="text-[10px]" style={{ color: '#ccc' }}>참고용 · 실시간 아님</p>
                </div>

                {/* UN Comtrade */}
                <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <div className="flex items-center gap-2 mb-3">
                    <p className="text-xs font-medium" style={{ color: '#1a1a1a' }}>한국 식품 수입액 — {fair.country}</p>
                    <span className="text-[10px] px-2 py-0.5" style={{ background: '#f0f5ff', color: '#5577aa', borderRadius: 2 }}>UN Comtrade API (목업)</span>
                  </div>
                  <div className="grid grid-cols-3 gap-3 mb-3">
                    {ctData.map((d, i) => {
                      const prev = ctData[i - 1];
                      const growth = prev ? (((d.value - prev.value) / prev.value) * 100).toFixed(1) : null;
                      return (
                        <div key={d.year} className="px-3 py-2.5" style={{ background: '#fafaf8', border: '1px solid #ebe8e2', borderRadius: 3 }}>
                          <p className="text-[10px]" style={{ color: '#aaa' }}>{d.year}년</p>
                          <p className="text-base font-mono font-semibold" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>${d.value}M</p>
                          {growth && <p className="text-[11px] mt-0.5" style={{ color: '#3a9a5c' }}>▲ {growth}%</p>}
                        </div>
                      );
                    })}
                  </div>
                  <p className="text-[11px]" style={{ color: '#ccc' }}>출처: UN Comtrade API · HS 1904, 1905, 2106 카테고리 합산 · 실제 서비스에서 자동 갱신 예정</p>
                </div>

                {/* Products registered */}
                <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <p className="text-xs font-medium mb-3" style={{ color: '#1a1a1a' }}>등록 제품 ({products.length}개)</p>
                  <div className="flex flex-wrap gap-2">
                    {products.map(p => (
                      <span key={p.id} className="text-xs px-2.5 py-1.5 flex items-center gap-1.5" style={{ background: '#f5f3ee', border: '1px solid #ebe8e2', borderRadius: 3, color: '#555' }}>
                        {p.name} <span style={{ color: '#aaa', fontFamily: 'JetBrains Mono, monospace', fontSize: 10 }}>{p.hsCode}</span>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
        )}

        {/* TRENDS */}
        {tab === 'trends' && (
          products.length === 0
            ? <NoProductsPrompt onGo={onGoToProducts} />
            : <div className="grid gap-4">
                {/* Google Trends sparkline */}
                <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-medium" style={{ color: '#1a1a1a' }}>검색 관심도 — "Korean snack" ({fair.country})</p>
                      <span className="text-[10px] px-2 py-0.5" style={{ background: '#fff0eb', color: '#F06A1A', borderRadius: 2 }}>Google Trends / pytrends (목업)</span>
                    </div>
                    <span className="text-xs font-mono" style={{ color: '#3a9a5c', fontFamily: 'JetBrains Mono, monospace' }}>
                      {trData[trData.length - 1]} / 100 ▲{(trData[trData.length - 1] - trData[0])} pts
                    </span>
                  </div>
                  <Sparkline data={trData} color="#F06A1A" />
                  <div className="flex justify-between mt-1">
                    {[0,2,4,6,8,10].map(i => <span key={i} className="text-[10px]" style={{ color: '#ccc' }}>{months[i]}</span>)}
                  </div>
                  <div className="mt-3 flex gap-3 flex-wrap">
                    {['약과', 'yakgwa', 'Korean snack', 'K-food', '한과'].map(kw => (
                      <span key={kw} className="text-[10px] px-2 py-0.5" style={{ background: '#f5f3ee', color: '#666', border: '1px solid #ebe8e2', borderRadius: 2 }}>🔍 {kw}</span>
                    ))}
                  </div>
                  <p className="text-[11px] mt-2" style={{ color: '#ccc' }}>출처: pytrends(비공식 Google Trends 라이브러리) · 실제 서비스에서 자동 갱신 예정</p>
                </div>

                {/* Competitor analysis */}
                <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                  <p className="text-xs font-medium mb-3" style={{ color: '#1a1a1a' }}>경쟁 제품 및 가격 분석 — {fair.country}</p>
                  <div className="grid gap-2">
                    {compData.map((c, i) => (
                      <div key={i} className="flex items-center gap-3 px-3 py-2.5" style={{ background: '#fafaf8', border: '1px solid #ebe8e2', borderRadius: 3 }}>
                        <span className="text-[10px] font-mono w-4 shrink-0" style={{ color: '#ccc' }}>{i + 1}</span>
                        <div className="flex-1">
                          <span className="text-xs font-medium" style={{ color: '#1a1a1a' }}>{c.name}</span>
                          <span className="text-[11px] ml-2" style={{ color: '#aaa' }}>{c.origin}</span>
                        </div>
                        <span className="text-xs font-mono" style={{ color: '#555', fontFamily: 'JetBrains Mono, monospace' }}>{c.price}</span>
                        <span className="text-[11px]" style={{ color: '#aaa', maxWidth: 180, textAlign: 'right' }}>{c.note}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
        )}

        {/* HS CODE & EXPORT NOTES (merged) */}
        {tab === 'hs-export' && (
          products.length === 0
            ? <NoProductsPrompt onGo={onGoToProducts} />
            : <div className="grid gap-4">
                <p className="text-xs" style={{ color: '#999' }}>등록 제품의 {fair.country} 수출 HS코드 및 관세율</p>
                {products.map(p => {
                  const tariffInfo = hsTariffData[p.hsCode]?.[fair.country];
                  return (
                    <div key={p.id} className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                      <div className="flex items-start justify-between gap-4 mb-2">
                        <div className="flex items-center gap-3">
                          <span className="text-xs font-semibold px-2.5 py-1" style={{ background: '#f5f3ee', color: '#555', borderRadius: 3 }}>{p.name}</span>
                          <p className="text-sm font-mono font-semibold" style={{ color: '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{p.hsCode}</p>
                        </div>
                        {tariffInfo && (
                          <div className="text-right">
                            <p className="text-[10px]" style={{ color: '#aaa' }}>관세율</p>
                            <p className="text-lg font-mono font-semibold" style={{ color: tariffInfo.tariff === '0%' ? '#3a9a5c' : tariffInfo.tariff.startsWith('1') ? '#cc5555' : '#1a1a1a', fontFamily: 'JetBrains Mono, monospace' }}>{tariffInfo.tariff}</p>
                          </div>
                        )}
                      </div>
                      {tariffInfo
                        ? <>
                            <p className="text-xs mb-2" style={{ color: '#aaa' }}>{tariffInfo.note}</p>
                            <div className="flex flex-wrap gap-1.5">
                              <span className="text-[10px]" style={{ color: '#aaa' }}>필요 인증:</span>
                              {tariffInfo.certification.map(c => <span key={c} className="text-[10px] px-2 py-0.5" style={{ background: '#f5f5f5', color: '#666', border: '1px solid #e8e8e8', borderRadius: 2 }}>{c}</span>)}
                            </div>
                          </>
                        : <p className="text-xs" style={{ color: '#aaa' }}>{fair.country}에 대한 이 HS코드의 관세 정보가 없습니다. 관세청에서 직접 확인해 주세요.</p>
                      }
                      {p.ingredients && <p className="text-xs mt-2 pt-2" style={{ color: '#bbb', borderTop: '1px solid #f0ede8' }}>등록 성분: {p.ingredients}</p>}
                    </div>
                  );
                })}

                {/* Export notes */}
                <p className="text-xs mt-2" style={{ color: '#999' }}>수출 주의사항</p>
                {fair.exportNotes.map((n, i) => {
                  const cfg = { warning: { bg: '#fff8f8', border: '#f5d5d5', badge: '#cc5555', label: '주의' }, required: { bg: '#fffaf7', border: '#f5d8c0', badge: '#F06A1A', label: '필수' }, info: { bg: '#f5f8ff', border: '#d5e0f5', badge: '#5577aa', label: '정보' } }[n.type];
                  return (
                    <div key={i} className="p-5" style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: 4 }}>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-[10px] px-1.5 py-0.5" style={{ background: `${cfg.badge}18`, color: cfg.badge, border: `1px solid ${cfg.badge}40`, borderRadius: 2 }}>{cfg.label}</span>
                        <h3 className="text-sm font-semibold" style={{ color: '#1a1a1a' }}>{n.title}</h3>
                      </div>
                      <p className="text-sm mb-2" style={{ color: '#555' }}>{n.description}</p>
                      <p className="text-[11px] font-mono" style={{ color: '#bbb', fontFamily: 'JetBrains Mono, monospace' }}>ref: {n.reference}</p>
                    </div>
                  );
                })}
              </div>
        )}
      </div>
    </div>
  );
}

// ─── Booth Concept ────────────────────────────────────────────────────────────
function BoothConceptView({ fair, products, concept, onGenerate, onBack, onGoToProducts }: {
  fair: Fair; products: Product[]; concept: GeneratedConcept | null;
  onGenerate: () => void; onBack: () => void; onGoToProducts: () => void;
}) {
  const [generating, setGenerating] = useState(false);
  const [imgLoading, setImgLoading] = useState(false);
  const [showImage, setShowImage] = useState(false);

  const handleGenerate = () => {
    setGenerating(true);
    setTimeout(() => { setGenerating(false); onGenerate(); }, 1800);
  };

  const handleImageGen = () => {
    setImgLoading(true);
    setTimeout(() => { setImgLoading(false); setShowImage(true); }, 2200);
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-8 py-5 flex items-center justify-between" style={{ background: '#fff', borderBottom: '1px solid #ebe8e2' }}>
        <div>
          <button onClick={onBack} className="text-xs mb-1.5 block hover:text-black" style={{ color: '#aaa' }}>← 박람회 상세</button>
          <h1 className="text-lg font-semibold" style={{ color: '#1a1a1a' }}>부스 컨셉 기획</h1>
          <p className="text-xs mt-0.5" style={{ color: '#999' }}>{fair.name} · {fair.country}</p>
        </div>
        {products.length > 0 && (
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {products.slice(0, 3).map(p => <span key={p.id} className="text-[10px] px-2 py-0.5" style={{ background: '#f5f3ee', color: '#666', borderRadius: 2 }}>{p.name}</span>)}
              {products.length > 3 && <span className="text-[10px] px-2 py-0.5" style={{ background: '#f5f3ee', color: '#aaa', borderRadius: 2 }}>+{products.length - 3}</span>}
            </div>
          </div>
        )}
      </div>

      <div className="p-8" style={{ background: '#f7f6f3' }}>
        {products.length === 0 ? (
          <NoProductsPrompt onGo={onGoToProducts} />
        ) : !concept ? (
          <div className="text-center py-20">
            <div className="inline-flex flex-col items-center gap-4">
              <SabuzakLogo size={44} />
              <div>
                <p className="text-sm font-medium" style={{ color: '#1a1a1a' }}>AI 부스 컨셉 자동 생성</p>
                <p className="text-xs mt-1" style={{ color: '#999' }}>
                  등록 제품 <strong>{products.map(p => p.name).join(', ')}</strong><br />
                  + {fair.name} ({fair.category}) 특성을 분석해 최적의 컨셉을 생성합니다
                </p>
              </div>
              <button onClick={handleGenerate} disabled={generating} className="px-6 py-2.5 text-sm font-medium hover:opacity-80"
                style={{ background: '#F06A1A', color: '#fff', borderRadius: 3, opacity: generating ? 0.6 : 1 }}>
                {generating ? '분석 중...' : '컨셉 자동 생성하기'}
              </button>
            </div>
          </div>
        ) : (
          <div className="grid gap-5">
            {/* Theme */}
            <div className="p-5" style={{ background: '#fffaf7', border: '1px solid #f5d8c0', borderRadius: 4 }}>
              <p className="text-[10px] mb-1 font-medium" style={{ color: '#F06A1A' }}>부스 테마</p>
              <p className="text-base font-semibold" style={{ color: '#1a1a1a' }}>{concept.theme}</p>
              <p className="text-sm mt-2" style={{ color: '#b85a10' }}>슬로건: {concept.slogan}</p>
              <p className="text-xs mt-2" style={{ color: '#666' }}>{concept.visualDirection}</p>
            </div>

            {/* Selling points */}
            <div>
              <p className="text-xs mb-3" style={{ color: '#999' }}>핵심 셀링포인트</p>
              <div className="grid grid-cols-2 gap-3">
                {concept.sellingPoints.map((sp, i) => (
                  <div key={i} className="p-4" style={{ background: '#fff', border: `1px solid ${sp.priority === 'core' ? '#f5d8c0' : '#ebe8e2'}`, borderRadius: 4 }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[10px] px-1.5 py-0.5" style={{ background: sp.priority === 'core' ? '#fffaf7' : '#f5f5f5', color: sp.priority === 'core' ? '#F06A1A' : '#999', border: `1px solid ${sp.priority === 'core' ? '#f5d8c0' : '#e8e8e8'}`, borderRadius: 2 }}>{sp.priority === 'core' ? '핵심' : '보조'}</span>
                      <h3 className="text-sm font-medium" style={{ color: '#1a1a1a' }}>{sp.title}</h3>
                    </div>
                    <p className="text-xs" style={{ color: '#666' }}>{sp.description}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Events */}
            <div>
              <p className="text-xs mb-3" style={{ color: '#999' }}>이벤트 기획안</p>
              <div className="grid gap-2">
                {concept.events.map((ev, i) => (
                  <div key={i} className="flex gap-4 p-4" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
                    <div className="w-7 h-7 flex items-center justify-center shrink-0 text-xs" style={{ background: '#f5f3ee', color: '#aaa', borderRadius: 2, fontFamily: 'JetBrains Mono, monospace' }}>{String(i + 1).padStart(2, '0')}</div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="text-sm font-medium" style={{ color: '#1a1a1a' }}>{ev.name}</h3>
                        <span className="text-[10px] px-1.5 py-0.5" style={{ background: '#f0f5ff', color: '#5577aa', borderRadius: 2 }}>{ev.type}</span>
                      </div>
                      <p className="text-xs" style={{ color: '#666' }}>{ev.description}</p>
                    </div>
                    <span className="text-[11px] shrink-0 font-mono" style={{ color: '#aaa', fontFamily: 'JetBrains Mono, monospace' }}>{ev.duration}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Target buyers */}
            <div className="p-4" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
              <p className="text-[10px] mb-2" style={{ color: '#aaa' }}>주요 타겟 바이어</p>
              <div className="flex flex-wrap gap-2">
                {concept.targetBuyers.map(b => <span key={b} className="text-xs px-2.5 py-1" style={{ background: '#f5f3ee', color: '#666', border: '1px solid #ebe8e2', borderRadius: 3 }}>{b}</span>)}
              </div>
            </div>

            {/* AI booth image */}
            <div className="p-5" style={{ background: '#fff', border: '1px solid #ebe8e2', borderRadius: 4 }}>
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium" style={{ color: '#1a1a1a' }}>부스 컨셉 예상 이미지</p>
                {!showImage && !imgLoading && (
                  <button onClick={handleImageGen} className="text-xs px-3 py-1.5 hover:opacity-80" style={{ background: '#1a1a1a', color: '#fff', borderRadius: 3 }}>
                    AI 이미지 생성
                  </button>
                )}
              </div>
              {imgLoading && (
                <div className="flex flex-col items-center justify-center gap-3 py-10" style={{ background: '#f7f6f3', borderRadius: 4 }}>
                  <div className="w-8 h-8 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: '#F06A1A', borderTopColor: 'transparent' }} />
                  <p className="text-xs" style={{ color: '#aaa' }}>이미지 생성 중... (DALL-E 3 연동 예정)</p>
                </div>
              )}
              {showImage && (
                <div className="relative" style={{ borderRadius: 4, overflow: 'hidden' }}>
                  <img src={`${concept.imageUrl}&q=85`} alt="부스 컨셉" className="w-full object-cover" style={{ height: 280 }} />
                  <div className="absolute inset-0" style={{ background: 'linear-gradient(to bottom, transparent 50%, rgba(0,0,0,0.45))' }} />
                  <div className="absolute top-3 right-3 text-[10px] px-2 py-1" style={{ background: 'rgba(0,0,0,0.6)', color: '#fff', borderRadius: 3 }}>AI 컨셉 렌더링 (시뮬레이션)</div>
                  <div className="absolute bottom-0 left-0 right-0 px-4 pb-4">
                    <p className="text-white text-xs font-medium">{concept.slogan}</p>
                    <p className="text-white text-[11px] opacity-70 mt-0.5">{fair.name} · {fair.country}</p>
                  </div>
                </div>
              )}
              {!showImage && !imgLoading && (
                <div className="flex items-center justify-center py-8" style={{ background: '#f7f6f3', borderRadius: 4 }}>
                  <p className="text-xs" style={{ color: '#bbb' }}>버튼을 눌러 AI 부스 이미지를 생성하세요<br /><span style={{ fontSize: 10 }}>실제 서비스에서는 DALL-E 3 또는 Stable Diffusion API와 연동됩니다</span></p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState<View>('login');
  const [selectedFair, setSelectedFair] = useState<Fair | null>(null);
  const [fromView, setFromView] = useState<View>('dashboard');
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [fromCountry, setFromCountry] = useState<string | null>(null);
  const [trackedFairs, setTrackedFairs] = useState<string[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [checkedProductIds, setCheckedProductIds] = useState<string[]>([]);
  const [generatedConcepts, setGeneratedConcepts] = useState<Record<string, GeneratedConcept>>({});

  if (view === 'login') return <LoginPage onLogin={() => setView('dashboard')} />;

  // Fair selected from dashboard (all tabs)
  const handleSelectFairFromDashboard = (f: Fair) => {
    setSelectedFair(f);
    setFromView('dashboard');
    setFromCountry(null);
    setView('fair-detail');
  };

  // Fair selected from country market page (overview-only tab)
  const handleSelectFairFromCountry = (f: Fair) => {
    setSelectedFair(f);
    setFromView('country-market');
    setFromCountry(selectedCountry);
    setView('fair-detail');
  };

  const handleSelectCountry = (country: string) => {
    setSelectedCountry(country);
    setView('country-market');
  };

  const handleTrack = (id: string) => setTrackedFairs(prev => prev.includes(id) ? prev : [...prev, id]);
  const handleAddProduct = (p: Omit<Product, 'id'>) => {
    const id = Date.now().toString();
    setProducts(prev => [...prev, { ...p, id }]);
    setCheckedProductIds(prev => [...prev, id]); // checked by default
  };
  const handleDeleteProduct = (id: string) => {
    setProducts(prev => prev.filter(p => p.id !== id));
    setCheckedProductIds(prev => prev.filter(cid => cid !== id));
  };
  const handleToggleCheck = (id: string) => setCheckedProductIds(prev => prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]);

  const activeProducts = products.filter(p => checkedProductIds.includes(p.id));

  const handleGenerateConcept = () => {
    if (!selectedFair) return;
    const concept = generateConcept(selectedFair, activeProducts);
    setGeneratedConcepts(prev => ({ ...prev, [selectedFair.id]: concept }));
    handleTrack(selectedFair.id);
  };

  const navView = ['fair-detail', 'booth-concept', 'country-market', 'country-fairs'].includes(view) ? 'dashboard' : view;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#f7f6f3' }}>
      <Sidebar view={navView as View} onNav={v => setView(v)} />
      <main className="flex-1 flex flex-col overflow-hidden">
        {view === 'dashboard' && (
          <Dashboard onSelectFair={handleSelectFairFromDashboard} onSelectCountry={handleSelectCountry} onAddProduct={handleAddProduct} />
        )}
        {view === 'country-market' && selectedCountry && (
          <CountryMarketView
            country={selectedCountry}
            products={activeProducts}
            onBack={() => setView('dashboard')}
            onSelectFair={handleSelectFairFromCountry}
            onGoToFairs={() => setView('country-fairs')}
            onGoToProducts={() => setView('my-products')}
          />
        )}
        {view === 'country-fairs' && selectedCountry && (
          <CountryFairsView
            country={selectedCountry}
            onBack={() => setView('country-market')}
            onSelectFair={handleSelectFairFromCountry}
          />
        )}
        {view === 'in-progress' && <InProgressView trackedFairs={trackedFairs} generatedConcepts={generatedConcepts} onSelectFair={handleSelectFairFromDashboard} />}
        {view === 'my-products' && (
          <MyProductsView products={products} checkedIds={checkedProductIds}
            onAdd={handleAddProduct} onDelete={handleDeleteProduct} onToggleCheck={handleToggleCheck} />
        )}
        {view === 'fair-detail' && selectedFair && (
          <FairDetail fair={selectedFair} products={activeProducts}
            onBack={() => setView(fromView)}
            onGoToConcept={() => setView('booth-concept')}
            onTrack={handleTrack}
            onGoToProducts={() => setView('my-products')}
            fromCountry={fromCountry}
          />
        )}
        {view === 'booth-concept' && selectedFair && (
          <BoothConceptView fair={selectedFair} products={activeProducts}
            concept={generatedConcepts[selectedFair.id] ?? null}
            onGenerate={handleGenerateConcept}
            onBack={() => setView('fair-detail')}
            onGoToProducts={() => setView('my-products')} />
        )}
      </main>
    </div>
  );
}

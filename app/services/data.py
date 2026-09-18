"""raw_exhibitions 테이블 조회/가공. legacy/streamlit_prototype.py 의
mock 데이터 로직을 실제 DB 조회로 대체하는 자리."""

from ..models import Exhibition

# scripts/crawl/tradefairdates_scraper.UNKNOWN_DATE와 반드시 같은 값이어야 함.
# 날짜 전체가 미상인 경우의 sentinel (임박순 정렬 시 항상 맨 뒤로 가도록 실존하는
# 모든 YYYYMMDD 값보다 크게 잡음). 0을 쓰면 오름차순 정렬에서 맨 앞으로 와버리는
# 버그가 생기므로 쓰지 않는다.
UNKNOWN_DATE = 99999999


def format_date(ymd):
    """시작일/종료일(YYYYMMDD 정수)을 표시용 문자열로.
    UNKNOWN_DATE=날짜 전체 미상, 일=32=그 달 안에서 일자만 미상."""
    if not ymd or ymd == UNKNOWN_DATE:
        return "날짜 미정"
    year, month, day = ymd // 10000, (ymd // 100) % 100, ymd % 100
    if day == 32:
        return f"{year}년 {month}월 (일자 미정)"
    return f"{year:04d}-{month:02d}-{day:02d}"


def format_period(start_date, end_date):
    if not start_date or start_date == UNKNOWN_DATE:
        return "날짜 미정"
    if start_date == end_date:
        return format_date(start_date)
    return f"{format_date(start_date)} ~ {format_date(end_date)}"


def count_exhibitions_by_continent():
    rows = (
        Exhibition.query.filter_by(is_active=1)
        .with_entities(Exhibition.continent, Exhibition.id)
        .all()
    )
    counts = {}
    for continent, _ in rows:
        if not continent:
            continue
        counts[continent] = counts.get(continent, 0) + 1
    return counts


def list_exhibitions_by_continent(continent):
    """임박한 날짜 순으로 정렬. start_date가 UNKNOWN_DATE(실존 날짜보다 큰 sentinel)라서
    별도 CASE 없이 그냥 오름차순 정렬만 해도 날짜 미상 항목이 자동으로 맨 뒤에 온다."""
    return (
        Exhibition.query.filter_by(is_active=1, continent=continent)
        .order_by(Exhibition.start_date.asc())
        .all()
    )


def get_exhibition(exhibition_id):
    return Exhibition.query.get_or_404(exhibition_id)


def get_market_insight(exhibition):
    """TODO: YoY 성장률 등 시장 인사이트 카드용 데이터 계산 (pandas)."""
    return {}


def get_hs_codes(exhibition):
    """TODO: data/hs_codes.csv 등 정적 참조 데이터에서 조회."""
    return []


def get_regulations(exhibition):
    """TODO: data/regulations.csv 등에서 국가·품목 기준 규제 카드 조회."""
    return []

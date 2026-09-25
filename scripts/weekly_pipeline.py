#!/usr/bin/env python3
"""
박람회 목록 주간 자동 갱신 파이프라인 - 아래 4단계를 순서대로 실행한다.

    1) scripts/crawl/sync_to_db.py       크롤링(신규/변경 박람회 + 로고/대표이미지 URL) -> DB 반영
    2) scripts/classify/preprocess.py    신규/변경분만 대륙·식품여부·규모·키워드·한글소개 분류
    3) scripts/classify/fill_scale.py    1)+2) 이후에도 규모='미상'으로 남은 것만 재시도
    4) scripts/classify/fill_audience_type.py   참관대상(B2B/B2C) 비어있는 것만 채움

각 단계는 독립 스크립트를 그대로 서브프로세스로 호출한다(이미 각자 "이미 처리된
건 재호출 안 함" 로직이 있어서, 이 오케스트레이터는 순서만 보장하면 됨). 한 단계가
실패해도 다음 단계는 계속 진행하고, 마지막에 실패한 단계를 모아서 보여준다 (크롤링이
막혀도 이미 있는 데이터의 분류 보정은 계속 돌아가는 게 나아서).

실행 방법:
    python scripts/weekly_pipeline.py                # 전체 4단계
    python scripts/weekly_pipeline.py --skip-crawl    # 크롤링 빼고 분류만 재실행 (디버깅용)

스케줄링 (서버에서 주 1회 자동 실행하려면):
    - Linux/macOS cron 예시 (매주 월요일 새벽 3시):
        0 3 * * 1 cd /path/to/SABUZAK && .venv/bin/python scripts/weekly_pipeline.py >> instance/logs/cron.log 2>&1
    - Windows 작업 스케줄러: 프로그램에 python.exe, 인수에 이 파일 절대경로, 시작 위치에 저장소 루트를 지정

실행 로그는 instance/logs/weekly_pipeline_YYYYMMDD_HHMMSS.log 에도 그대로 저장된다
(웹 화면의 "지금 실행" 버튼으로 돌렸을 때 콘솔을 못 보므로, 결과를 나중에 파일로 확인 가능).
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "instance" / "sabuzak.db"  # 실제로 앱이 읽는 DB (scripts/crawl/sync_to_db.py의 기본 경로와 다르니 항상 명시)
LOG_DIR = BASE_DIR / "instance" / "logs"

STEPS = [
    ("크롤링 (신규/변경 박람회 + 이미지)", [sys.executable, str(BASE_DIR / "scripts/crawl/sync_to_db.py"), "--db", str(DB_PATH)]),
    ("분류 (대륙/식품여부/규모/키워드/한글소개)", [sys.executable, str(BASE_DIR / "scripts/classify/preprocess.py"), "--db", str(DB_PATH)]),
    ("규모 보정 (미상만 재시도)", [sys.executable, str(BASE_DIR / "scripts/classify/fill_scale.py"), "--db", str(DB_PATH)]),
    ("참관대상 보정 (B2B/B2C 미확정만)", [sys.executable, str(BASE_DIR / "scripts/classify/fill_audience_type.py"), "--db", str(DB_PATH)]),
]


def _log(f, line=""):
    print(line)
    f.write(line + "\n")
    f.flush()


def run_pipeline(skip_crawl=False):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"weekly_pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    steps = STEPS[1:] if skip_crawl else STEPS
    failed_steps = []

    with open(log_path, "w", encoding="utf-8") as f:
        _log(f, f"=== 주간 박람회 갱신 파이프라인 시작: {datetime.now().isoformat()} ===")
        _log(f, f"DB: {DB_PATH}")

        for i, (label, cmd) in enumerate(steps, 1):
            _log(f, f"\n[{i}/{len(steps)}] {label}")
            _log(f, f"$ {' '.join(cmd)}")
            try:
                result = subprocess.run(
                    cmd, cwd=str(BASE_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                if result.stdout:
                    f.write(result.stdout)
                    print(result.stdout, end="")
                if result.returncode != 0:
                    _log(f, f"  -> 실패 (종료코드 {result.returncode})")
                    if result.stderr:
                        f.write(result.stderr)
                        print(result.stderr, end="", file=sys.stderr)
                    failed_steps.append(label)
                else:
                    _log(f, f"  -> 완료")
            except Exception as e:
                _log(f, f"  -> 실패 (예외): {e}")
                failed_steps.append(label)

        _log(f, f"\n=== 종료: {datetime.now().isoformat()} ===")
        if failed_steps:
            _log(f, f"실패한 단계 {len(failed_steps)}개: {', '.join(failed_steps)}")
        else:
            _log(f, "전체 단계 정상 완료")

    return log_path, failed_steps


def main():
    parser = argparse.ArgumentParser(description="박람회 목록 주간 자동 갱신 파이프라인")
    parser.add_argument("--skip-crawl", action="store_true", help="크롤링은 건너뛰고 분류/보정만 재실행")
    args = parser.parse_args()

    log_path, failed_steps = run_pipeline(skip_crawl=args.skip_crawl)
    print(f"\n로그 파일: {log_path}")
    sys.exit(1 if failed_steps else 0)


if __name__ == "__main__":
    main()

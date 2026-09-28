"""보고서 PDF(WeasyPrint) 공용 헬퍼.

배포 서버(OS)에 한글 폰트가 깔려 있는지와 무관하게 항상 같은 폰트로
렌더링되도록, app/static/fonts에 직접 넣어둔 폰트 파일을 file:// 절대
경로로 가리킨다 (자세한 배경은 exhibition.py market_report_pdf 커밋
메시지 참고 - 시스템 폰트에 기대면 서버마다 다른 대체 폰트가 섞여서
글자가 깨지거나 줄이 밀려 보이는 문제가 있었다)."""

import os

from flask import current_app

FONT_REGULAR = "NotoSansKR-Regular.woff2"
FONT_BOLD = "NotoSansKR-Bold.woff2"


def pdf_font_uri(filename):
    path = os.path.join(current_app.static_folder, "fonts", filename)
    return "file://" + path


def pdf_font_context():
    """리포트 템플릿에 그대로 **로 풀어 넘기는 폰트 경로 딕셔너리."""
    return {
        "font_regular_uri": pdf_font_uri(FONT_REGULAR),
        "font_bold_uri": pdf_font_uri(FONT_BOLD),
    }

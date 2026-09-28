"""보고서 PDF(WeasyPrint) 공용 헬퍼.

배포 서버(OS)에 한글 폰트가 깔려 있는지와 무관하게 항상 같은 폰트로
렌더링되도록, app/static/fonts에 직접 넣어둔 폰트 파일을 file:// 절대
경로로 가리킨다 (자세한 배경은 exhibition.py market_report_pdf 커밋
메시지 참고 - 시스템 폰트에 기대면 서버마다 다른 대체 폰트가 섞여서
글자가 깨지거나 줄이 밀려 보이는 문제가 있었다).

Noto Sans KR은 한글 완성형 11,172자를 전부 담고 있어서(파일 자체는
~650KB로 작지만) WeasyPrint가 PDF에 폰트를 임베딩하려고 압축을 풀고
글리프 테이블을 통째로 메모리에 올려 재압축하는 과정에서 메모리를 크게
먹는다. Render 무료 플랜처럼 메모리가 적은 환경에서는 이 단계에서
워커가 OOM으로 SIGKILL 당해 PDF 다운로드가 500 에러로 끝나는 문제가
있었다 -> 그래서 WeasyPrint에 넘기기 전에 fontTools로 "이 보고서에
실제로 쓰인 글자만" 담은 훨씬 작은 서브셋 폰트를 먼저 만들어서(보통
수백 글자 수준), WeasyPrint가 그 작은 폰트만 처리하게 한다."""

import gc
import hashlib
import io
import os
import re
import tempfile

from flask import current_app

FONT_REGULAR = "NotoSansKR-Regular.woff2"
FONT_BOLD = "NotoSansKR-Bold.woff2"

# 실제 본문 글자와 무관하게 항상 포함해두는 기본 문자셋(숫자/영문/기본
# 문장부호) - 서브셋 캐시 키가 달라도 최소한 이 정도는 항상 들어있게 해서
# 혹시 놓친 글자가 있어도 흔한 기호는 깨지지 않게 한다.
_BASE_CHARS = (
    "0123456789"
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    " .,·:;!?()[]{}%$₩@#&*+-=/\\'\"<>_~^|\n"
)

_SUBSET_CACHE_DIR = os.path.join(tempfile.gettempdir(), "sabuzak_pdf_font_subsets")
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def pdf_font_uri(filename):
    path = os.path.join(current_app.static_folder, "fonts", filename)
    return "file://" + path


def pdf_font_context():
    """리포트 템플릿에 그대로 **로 풀어 넘기는 폰트 경로 딕셔너리(기본
    전체 폰트 경로). render_pdf_bytes()가 실제 렌더링 시 이 경로를 더
    작은 서브셋 폰트 경로로 바꿔치기한다."""
    return {
        "font_regular_uri": pdf_font_uri(FONT_REGULAR),
        "font_bold_uri": pdf_font_uri(FONT_BOLD),
    }


def _extract_text(html):
    """HTML에서 태그를 걷어내고 눈에 보이는 텍스트만 남긴다(정확할
    필요는 없음 - 서브셋에 넣을 글자를 조금 넉넉하게 뽑는 용도)."""
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    return _TAG_RE.sub(" ", html)


def _subset_one(src_path, chars, cache_key):
    os.makedirs(_SUBSET_CACHE_DIR, exist_ok=True)
    out_path = os.path.join(_SUBSET_CACHE_DIR, cache_key + ".woff2")
    if os.path.exists(out_path):
        return out_path

    from fontTools import subset as ft_subset
    from fontTools.ttLib import TTFont

    font = TTFont(src_path)
    options = ft_subset.Options()
    options.flavor = "woff2"
    options.desubroutinize = False
    options.recalc_bounds = True
    options.ignore_missing_glyphs = True
    options.ignore_missing_unicodes = True
    subsetter = ft_subset.Subsetter(options=options)
    subsetter.populate(text="".join(chars))
    subsetter.subset(font)

    tmp_path = out_path + f".{os.getpid()}.tmp"
    font.save(tmp_path)
    os.replace(tmp_path, out_path)  # 원자적 교체라 동시 요청끼리 부분 쓰기를 안 봄
    return out_path


def render_pdf_bytes(html):
    """render_template()이 만든 HTML 문자열을 받아, 실제 쓰인 글자만
    담은 서브셋 폰트로 @font-face 경로를 바꿔치기한 뒤 PDF bytes로
    렌더링한다. 서브셋 생성이 어떤 이유로든 실패하면 원래 전체 폰트로
    그대로 렌더링한다(느리고 메모리를 더 쓰지만 최소한 깨지진 않게)."""
    from weasyprint import HTML

    try:
        chars = set(_BASE_CHARS) | set(_extract_text(html))
        cache_key_src = "".join(sorted(chars))
        regular_src = os.path.join(current_app.static_folder, "fonts", FONT_REGULAR)
        bold_src = os.path.join(current_app.static_folder, "fonts", FONT_BOLD)

        regular_key = "reg-" + hashlib.sha1(cache_key_src.encode("utf-8")).hexdigest()[:20]
        bold_key = "bold-" + hashlib.sha1(cache_key_src.encode("utf-8")).hexdigest()[:20]

        regular_subset = _subset_one(regular_src, chars, regular_key)
        bold_subset = _subset_one(bold_src, chars, bold_key)

        html = html.replace(pdf_font_uri(FONT_REGULAR), "file://" + regular_subset)
        html = html.replace(pdf_font_uri(FONT_BOLD), "file://" + bold_subset)
    except Exception as e:
        print(f"[PDF 폰트 서브셋 실패 - 전체 폰트로 렌더링] {e}")

    pdf_bytes = HTML(string=html).write_pdf()
    # WeasyPrint가 렌더링 트리에 물고 있던 메모리를 다음 파트를 그리기 전에
    # 확실히 반납하게 한다 - 통합보고서처럼 여러 파트를 이어서 렌더링할 때
    # (combined_report_pdf) 파트별로 메모리를 안 놓아주면 계속 쌓여서 Render
    # 무료 플랜(메모리 적음)에서 OOM(SIGKILL)으로 죽는 문제가 있었다.
    gc.collect()
    return pdf_bytes


def merge_pdfs(pdf_bytes_list):
    """PDF bytes 여러 개를 순서대로 이어붙인 PDF bytes 하나로 합친다.
    combined_report_pdf처럼 파트별로 따로 렌더링한 뒤 하나로 합칠 때 쓴다 -
    한 번의 WeasyPrint 호출에 표·그래프·여러 페이지를 다 몰아넣는 것보다,
    파트마다 작게 나눠 렌더링한 뒤 여기서 합치는 쪽이 메모리 사용량 피크가
    훨씬 낮다."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for pdf_bytes in pdf_bytes_list:
        writer.append(io.BytesIO(pdf_bytes))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()

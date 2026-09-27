"""오래된 brotli 패키지 호환 처리.

최신 OpenAI SDK와 urllib3(2.6+)는 brotli(br) 압축 응답을 풀 때
`decompress(..., output_buffer_limit=...)`를 호출하는데, 이 인자는 Brotli 1.2.0
이상에서만 지원된다. PC에 예전 brotli/brotlicffi가 깔려 있으면
"Decompressor.decompress() got an unexpected keyword argument 'output_buffer_limit'"
오류로 OpenAI·Google Trends 호출이 전부 실패한다.

해결: 서버에 br 압축을 아예 요청하지 않는다(Accept-Encoding: gzip, deflate).
그러면 brotli 코드가 호출될 일이 없어 설치된 버전과 상관없이 동작한다.
"""

import logging

logger = logging.getLogger("sabuzak.trend_usp.http_compat")

SAFE_ACCEPT_ENCODING = "gzip, deflate"
SAFE_HEADERS = {"Accept-Encoding": SAFE_ACCEPT_ENCODING}
MIN_BROTLI_VERSION = (1, 2, 0)


def _parse_version(text: str) -> tuple:
    parts = []
    for piece in str(text).split(".")[:3]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


def find_outdated_brotli():
    """설치된 brotli/brotlicffi 중 1.2.0 미만인 것의 "이름 버전"을 돌려준다. 없으면 None."""
    for module_name in ("brotli", "brotlicffi"):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        version = getattr(module, "__version__", "0")
        if _parse_version(version) < MIN_BROTLI_VERSION:
            return f"{module_name} {version}"
    return None


def apply_brotli_workaround() -> None:
    """requests(pytrends가 사용)의 기본 Accept-Encoding에서 br을 뺀다.

    pytrends는 첫 쿠키 요청을 우리가 넘긴 헤더 없이 requests 기본값으로 보내기 때문에
    requests 전역 기본값을 바꿔야 한다. 예전 brotli가 깔린 경우에만 적용한다."""
    outdated = find_outdated_brotli()
    if not outdated:
        return
    try:
        import requests.utils
        requests.utils.DEFAULT_ACCEPT_ENCODING = SAFE_ACCEPT_ENCODING
    except Exception:
        pass
    logger.warning("%s 버전이 낮아 br 압축 요청을 끕니다. "
                   "`python -m pip install -U \"brotli>=1.2.0\"`로 업그레이드하면 이 경고가 사라집니다.",
                   outdated)

"""v10b: v10의 OpenAI 모델을 상위 모델로 바꿔 쓰는 연결부.

각 폴더(trend_usp_v1, j_test, tavily_v9)의 코드는 고치지 않고, 이 모듈이
  1) 모델 이름을 바꾸고 (부스 기획 = 최상위 모델, 나머지 작업 = 중간 등급 모델)
  2) 추론형 모델(gpt-5·gpt-6·o 시리즈)이 받지 않는 temperature를 빼고 추론 깊이(reasoning effort)를 넣고
  3) 모델 ID가 없거나 계정에서 막혀 있으면 대체 모델로 자동 전환한다.

환경변수(.env)로 바꿀 수 있다:
  V10B_BOOTH_MODEL   (기본 gpt-6-astra)    부스 기획·부스용 자체 조사
  V10B_BOOTH_EFFORT  (기본 medium)         low | medium | high | xhigh | max
  V10B_TASK_MODEL    (기본 gpt-5.6-terra)  섹션 1 분류, 섹션 2 리테일, 섹션 3 발췌·요약
  V10B_TASK_EFFORT   (기본 low)
"""

import logging
import os
import threading

import openai
from dotenv import load_dotenv


def _load_dotenv():
    """V10B_* 설정이 .env에 있어도 적용되도록, 가장 가까운 상위 폴더의 .env를 먼저 읽는다."""
    folder = os.path.dirname(os.path.abspath(__file__))
    while True:
        path = os.path.join(folder, ".env")
        if os.path.isfile(path):
            load_dotenv(path, override=True)
            return
        parent = os.path.dirname(folder)
        if parent == folder:
            return
        folder = parent


_load_dotenv()

logger = logging.getLogger("sabuzak.dashboard_v10b.models")

BOOTH_MODEL = os.getenv("V10B_BOOTH_MODEL") or "gpt-6-astra"
BOOTH_EFFORT = os.getenv("V10B_BOOTH_EFFORT") or "medium"
TASK_MODEL = os.getenv("V10B_TASK_MODEL") or "gpt-5.6-terra"
TASK_EFFORT = os.getenv("V10B_TASK_EFFORT") or "low"

# 모델 ID가 없거나 권한이 없을 때 차례로 시도할 대체 모델
FALLBACKS = {
    "booth": ["gpt-5.6-sol", "gpt-5.5", "gpt-4.1", "gpt-4o"],
    "task": ["gpt-5.6-luna", "gpt-4.1-mini", "gpt-4o-mini"],
}
# 각 폴더 코드에 적힌 옛 모델 이름 → 역할
LEGACY_ROLES = {"gpt-4o": "booth", "gpt-4o-mini": "task"}
REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")
SAMPLING_PARAMS = ("temperature", "top_p", "logprobs", "top_logprobs")

_resolved = {}          # 요청 모델 → 실제로 성공한 모델
_dropped = {}           # 모델 → 거절당해 빼고 보내는 파라미터
_lock = threading.Lock()


def is_reasoning(model):
    return str(model or "").lower().startswith(REASONING_PREFIXES)


def role_of(model):
    if model in LEGACY_ROLES:
        return LEGACY_ROLES[model]
    if model == BOOTH_MODEL or model in FALLBACKS["booth"]:
        return "booth"
    return "task"


def _target(model):
    """옛 모델 이름이면 새 모델로 바꾼다. 이미 대체된 적 있으면 그 모델을 쓴다."""
    role = role_of(model)
    wanted = {"booth": BOOTH_MODEL, "task": TASK_MODEL}[role] if model in LEGACY_ROLES else model
    with _lock:
        return _resolved.get(wanted, wanted), wanted, role


def _candidates(first, role):
    chain = [first] + [m for m in FALLBACKS[role] if m != first]
    return list(dict.fromkeys(chain))


def _prepare(kind, kwargs, model, role):
    kw = dict(kwargs, model=model)
    effort = BOOTH_EFFORT if role == "booth" else TASK_EFFORT
    if is_reasoning(model):
        for p in SAMPLING_PARAMS:
            kw.pop(p, None)
        if kind == "chat":
            kw.setdefault("reasoning_effort", effort)
        else:
            kw.setdefault("reasoning", {"effort": effort})
    for p in _dropped.get(model, ()):
        kw.pop(p, None)
    return kw


def _is_missing_model(e):
    if isinstance(e, (openai.NotFoundError, openai.PermissionDeniedError)):
        return True
    code = str(getattr(e, "code", "") or "")
    return isinstance(e, openai.BadRequestError) and (code == "model_not_found" or "model" == getattr(e, "param", None))


def _rejected_param(e):
    """지원하지 않는 파라미터(예: 이 모델이 받지 않는 추론 깊이) 때문에 400이 났으면 그 이름을 돌려준다."""
    if not isinstance(e, openai.BadRequestError):
        return None
    param = str(getattr(e, "param", "") or "")
    for p in ("reasoning_effort", "reasoning", "reasoning.effort") + SAMPLING_PARAMS:
        if param == p:
            return p.split(".")[0]
    return None


def _call(kind, create, kwargs):
    first, wanted, role = _target(kwargs.get("model"))
    last_error = None
    for model in _candidates(first, role):
        for _ in range(3):   # 파라미터 거절 시 빼고 재시도
            try:
                result = create(**_prepare(kind, kwargs, model, role))
                if model != wanted:
                    with _lock:
                        if _resolved.get(wanted) != model:
                            logger.warning("모델 %s을(를) 쓸 수 없어 %s(으)로 대체합니다.", wanted, model)
                        _resolved[wanted] = model
                return result
            except openai.APIStatusError as e:
                param = _rejected_param(e)
                if param and param not in _dropped.get(model, ()):
                    logger.warning("%s이(가) %s 파라미터를 받지 않아 빼고 다시 보냅니다.", model, param)
                    with _lock:
                        _dropped.setdefault(model, set()).add(param)
                    continue
                if _is_missing_model(e):
                    last_error = e
                    break
                raise
    raise last_error


class _Endpoint:
    def __init__(self, kind, target):
        self._kind, self._target = kind, target

    def create(self, **kwargs):
        return _call(self._kind, self._target.create, kwargs)

    def __getattr__(self, name):
        return getattr(self._target, name)


class _Chat:
    def __init__(self, chat):
        self._chat = chat
        self.completions = _Endpoint("chat", chat.completions)

    def __getattr__(self, name):
        return getattr(self._chat, name)


class UpgradedOpenAI:
    """OpenAI 클라이언트를 감싸 chat.completions.create / responses.create만 가로챈다. 나머지는 그대로."""

    def __init__(self, client):
        self._client = client
        self.chat = _Chat(client.chat)
        self.responses = _Endpoint("responses", client.responses)

    def __getattr__(self, name):
        return getattr(self._client, name)


def wrap(client):
    return client if isinstance(client, UpgradedOpenAI) else UpgradedOpenAI(client)


def models_used():
    """화면 표시용: 역할별로 실제 쓰인(또는 쓸 예정인) 모델."""
    with _lock:
        return {"booth": _resolved.get(BOOTH_MODEL, BOOTH_MODEL), "booth_effort": BOOTH_EFFORT,
                "task": _resolved.get(TASK_MODEL, TASK_MODEL), "task_effort": TASK_EFFORT}


def check_models(client):
    """시작할 때 한 번: 설정한 모델이 이 계정에서 보이는지 알려준다 (실패해도 실행은 계속)."""
    try:
        available = {m.id for m in client.models.list()}
    except Exception as e:
        print(f"모델 목록을 확인하지 못했습니다 ({e}). 실행 중 모델이 없으면 자동으로 대체합니다.")
        return
    for role, model in (("부스 기획", BOOTH_MODEL), ("일반 작업", TASK_MODEL)):
        if model in available:
            print(f"✓ {role} 모델: {model}")
        else:
            alt = next((m for m in FALLBACKS["booth" if role == "부스 기획" else "task"] if m in available), None)
            print(f"⚠️  {role} 모델 {model}이(가) 이 계정 목록에 없습니다. "
                  + (f"{alt}(으)로 대체됩니다." if alt else "대체 모델도 목록에 없습니다.")
                  + " .env의 V10B_BOOTH_MODEL / V10B_TASK_MODEL로 바꿀 수 있습니다.")

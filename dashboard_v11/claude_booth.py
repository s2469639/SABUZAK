"""섹션 4. Claude 마케팅 에이전트 부스 컨셉 기획 (v11).

Claude 마케팅 플러그인의 /marketing:competitive-brief 흐름을 API로 옮겨, 부스 기획을 네 단계로 진행한다.
  ① 경쟁 브리프  Claude가 웹 검색(web_search 서버 도구)으로 경쟁 제품·시장·박람회를 직접 조사하고
                 경쟁 구도 → 메시지 비교 → 포지셔닝 빈틈 → 이기는 방법을 정리 (skills/competitive_brief)
  ② 부스 기획    빈틈을 빅 아이디어로 삼아 전략 뼈대 + 6개 실행 항목 초안 (tavily_v9 skills/booth_marketing)
  ③ 바이어 채점  미국 대형 유통 MD 페르소나가 채점표(rubric.md)로 1~5점 채점
  ④ 수정         기준 점수 미만 항목이 있을 때만 고침

Tavily 조사(섹션 3)는 쓰지 않는다. 결과는 tavily_v9와 같은 부스 구조(화면 재사용)에 경쟁 브리프를 더한 것.
플러그인 스킬 자체는 API에서 부를 수 없으므로 그 방법론을 skills/competitive_brief/SKILL.md로 옮겨 시스템 프롬프트에 넣는다.
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(HERE)
TAVILY_DIR = os.path.join(ROOT_DIR, "tavily_v9")
if TAVILY_DIR not in sys.path:
    sys.path.insert(0, TAVILY_DIR)

import research as v9  # noqa: E402  (tavily_v9/research.py: 부스 구조 정리 함수·스키마 재사용)
from constants.personas import PLANNER_PERSONA, REVIEWER_PERSONA  # noqa: E402  (tavily_v9/constants)
from env_setup import ENV_PATH, load_env  # noqa: E402
from http_compat import SAFE_HEADERS  # noqa: E402
from skill_loader import _read, _split_front_matter, load_skill  # noqa: E402

logger = logging.getLogger("sabuzak.dashboard_v11.claude_booth")

VERSION = "v11.0"             # 프롬프트·단계를 바꾸면 올려서 캐시 무효화
MODEL = os.getenv("CLAUDE_BOOTH_MODEL") or "claude-opus-5"
EFFORT = os.getenv("CLAUDE_BOOTH_EFFORT") or "high"            # low | medium | high | xhigh | max
REVIEW_EFFORT = os.getenv("CLAUDE_REVIEW_EFFORT") or "medium"
WEB_SEARCH = os.getenv("CLAUDE_WEB_SEARCH", "1") != "0"         # 0이면 웹 검색 없이 모델 지식만
WEB_SEARCH_MAX_USES = int(os.getenv("CLAUDE_WEB_SEARCH_MAX_USES") or 8)
USE_FALLBACKS = os.getenv("CLAUDE_FALLBACKS", "1") != "0"       # 서버 측 대체 모델 (거절 시 자동 재시도)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
AGENT_SKILL = os.getenv("CLAUDE_AGENT_SKILL") or "competitive_brief"
BOOTH_SKILL = os.getenv("CLAUDE_BOOTH_SKILL") or "booth_marketing"
REVISE_BELOW = int(os.getenv("CLAUDE_REVISE_BELOW") or 4)
MAX_TOKENS = 32000
MAX_CONTINUATIONS = 5         # 웹 검색이 길어져 pause_turn으로 멈췄을 때 이어서 진행하는 횟수
MAX_NOTES = 14
MAX_AGENT_SKILL_CHARS = 20000
CACHE_TTL_DAYS = 30
SKILLS_DIR = os.path.join(HERE, "skills")
DEFAULT_DB_PATH = os.path.join(HERE, "booth_cache.db")

PROFILE_LABELS = {"strengths": "강점", "ingredients": "원료", "certifications": "인증", "price": "가격대"}
COMPETITOR_TYPES = {"direct": "직접 경쟁", "indirect": "간접 경쟁", "trade_show": "박람회 경쟁"}

COMPETITIVE_SCHEMA = """{
  "market_snapshot": "대상 시장에서 이 제품군의 현재 모습 1~2문장",
  "notes": [{"id": "R1", "topic": "competitor", "text": "조사 메모 (한국어 한두 문장, 수치·브랜드는 원문 표기)",
             "source_url": "실제로 본 페이지 URL", "source_title": ""}],
  "competitors": [{"name": "제품·브랜드명", "owner": "회사", "type": "direct | indirect | trade_show",
                   "price": "현지 가격·용량", "channels": "주요 판매 채널", "positioning": "누구에게 어떤 약속",
                   "key_message": "대표 문구", "strengths": "", "weaknesses": "", "basis": ["R1"]}],
  "common_claims": ["경쟁사들이 공통으로 하는 말 (차별이 안 되는 말)"],
  "white_space": {"text": "우리가 차지할 포지셔닝 빈틈 한 문장", "why": "왜 지금 이 시장에서 의미 있나", "basis": ["R2", "기업:강점"]},
  "our_edge": [{"text": "우리만의 증명 포인트", "against": "맞서는 경쟁사·약점", "basis": ["기업:원료"]}],
  "objections": [{"objection": "바이어가 부스에서 할 법한 반론", "answer": "짧은 답변", "basis": []}]
}"""


class ClaudeRefusal(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Claude 호출
# ---------------------------------------------------------------------------

def get_client():
    load_env()
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(f"ANTHROPIC_API_KEY가 설정되어 있지 않습니다 ({ENV_PATH} 확인).")
    # 예전 brotli가 깔린 PC에서도 동작하도록 br 압축을 요청하지 않는다 (v10과 동일)
    return anthropic.Anthropic(api_key=key, default_headers=SAFE_HEADERS, max_retries=3)


def _block_get(block, key, default=None):
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _collect_citations(content):
    """웹 검색 결과 블록과 본문 인용에서 실제로 받은 URL을 모은다. 반환: ({url: title}, 검색 오류 코드 목록)"""
    urls, errors = {}, []
    for block in content:
        btype = _block_get(block, "type")
        if btype == "web_search_tool_result":
            result = _block_get(block, "content")
            if isinstance(result, list):
                for item in result:
                    url = _block_get(item, "url")
                    if url:
                        urls.setdefault(url, _block_get(item, "title") or "")
            elif result is not None:     # 검색 오류도 HTTP 200으로 온다
                errors.append(str(_block_get(result, "error_code") or "unknown"))
        elif btype == "text":
            for c in _block_get(block, "citations") or []:
                url = _block_get(c, "url")
                if url:
                    urls.setdefault(url, _block_get(c, "title") or "")
    return urls, errors


def _final_text(content):
    """마지막 도구 사용 뒤에 나온 본문(최종 답변)을 돌려준다. 검색 중간의 안내 문장을 JSON 파싱에서 뺀다."""
    last_tool = -1
    for i, block in enumerate(content):
        if _block_get(block, "type") in ("server_tool_use", "web_search_tool_result"):
            last_tool = i
    texts = [_block_get(b, "text") or "" for b in content[last_tool + 1:] if _block_get(b, "type") == "text"]
    if not "".join(texts).strip():
        texts = [_block_get(b, "text") or "" for b in content if _block_get(b, "type") == "text"]
    return "\n".join(texts).strip()


def _call(client, system, user, *, tools=None, effort=EFFORT, stats=None):
    """Claude 한 번 호출 (스트리밍, 적응형 사고, 시스템 프롬프트 캐시, 서버 측 대체 모델).
    웹 검색이 길어 pause_turn으로 멈추면 이어서 진행한다. 반환: {"text", "content", "model", "fallback_used"}"""
    messages = [{"role": "user", "content": user}]
    kwargs = dict(model=MODEL, max_tokens=MAX_TOKENS,
                  system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                  thinking={"type": "adaptive"}, output_config={"effort": effort})
    if tools:
        kwargs["tools"] = tools
    if USE_FALLBACKS:
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")

    content, msg = [], None
    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(messages=messages, **kwargs) as stream:
            msg = stream.get_final_message()
        content += list(msg.content)
        _add_usage(stats, msg)
        if msg.stop_reason != "pause_turn":
            break
        # 서버 도구 반복 한도에 걸려 멈춘 경우: 지금까지의 답변을 그대로 돌려주면 서버가 이어서 진행한다
        messages = [messages[0], {"role": "assistant", "content": content}]

    if msg.stop_reason == "refusal":
        details = getattr(msg, "stop_details", None)
        raise ClaudeRefusal(f"Claude가 요청을 처리하지 않았습니다 ({getattr(details, 'category', None) or '사유 미상'}).")
    fallback_used = any(_block_get(b, "type") == "fallback" for b in content)
    if stats is not None:
        stats["models"] = list(dict.fromkeys(stats.get("models", []) + [msg.model]))
        stats["fallback_used"] = stats.get("fallback_used", False) or fallback_used
    return {"text": _final_text(content), "content": content, "model": msg.model,
            "fallback_used": fallback_used, "stop_reason": msg.stop_reason}


def _add_usage(stats, msg):
    if stats is None:
        return
    usage = getattr(msg, "usage", None)
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        stats[key] = stats.get(key, 0) + (getattr(usage, key, 0) or 0)
    server = getattr(usage, "server_tool_use", None)
    stats["web_search_requests"] = stats.get("web_search_requests", 0) + (getattr(server, "web_search_requests", 0) or 0)
    stats["calls"] = stats.get("calls", 0) + 1


def _ask_json(client, system, user, *, tools=None, effort=EFFORT, stats=None):
    """JSON 답변을 받는다. 본문에서 JSON을 못 찾으면 한 번 더 'JSON으로만 옮겨 적기'를 요청한다.
    (웹 검색 결과 인용과 구조화 출력은 함께 쓸 수 없어 본문에서 JSON을 꺼낸다)"""
    result = _call(client, system, user, tools=tools, effort=effort, stats=stats)
    try:
        return v9._extract_json(result["text"]), result
    except (ValueError, json.JSONDecodeError):
        if not result["text"]:
            raise ValueError("Claude 답변이 비어 있습니다.")
        repair = _call(client, "당신은 JSON 변환기입니다. 설명 없이 JSON 객체 하나만 출력합니다.",
                       "아래 답변의 내용을 요청된 JSON 형식 그대로 옮겨 적으세요. 내용은 바꾸지 마세요.\n\n"
                       f"[요청 형식]\n{user[-3000:]}\n\n[답변]\n{result['text']}", effort="low", stats=stats)
        return v9._extract_json(repair["text"]), result


# ---------------------------------------------------------------------------
# 스킬(시스템 프롬프트)
# ---------------------------------------------------------------------------

def load_agent_skill(name=None):
    """skills/<이름>/ 아래 SKILL.md와 나머지 *.md(참고 문서)를 읽는다.
    Claude 마케팅 플러그인의 실제 스킬 문서를 폴더째 넣어도 된다 (Claude 모델이므로 도구 지시 줄도 그대로 둔다)."""
    name = (name or AGENT_SKILL).strip()
    folder = os.path.join(SKILLS_DIR, name)
    warnings = []
    if not os.path.isfile(os.path.join(folder, "SKILL.md")):
        warnings.append(f"에이전트 스킬 '{name}'을(를) 찾지 못해 competitive_brief를 씁니다.")
        name, folder = "competitive_brief", os.path.join(SKILLS_DIR, "competitive_brief")
    meta, body = _split_front_matter(_read(os.path.join(folder, "SKILL.md")))
    files, parts = ["SKILL.md"], [body.strip()]
    for root, _, fns in os.walk(folder):
        for fn in sorted(fns):
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, folder)
            if fn.endswith(".md") and rel != "SKILL.md":
                parts.append(f"## 참고: {rel}\n{_split_front_matter(_read(path))[1].strip()}")
                files.append(rel)
    text = "\n\n".join(p for p in parts if p)
    if len(text) > MAX_AGENT_SKILL_CHARS:
        warnings.append(f"에이전트 스킬이 길어 {MAX_AGENT_SKILL_CHARS}자까지만 사용합니다.")
        text = text[:MAX_AGENT_SKILL_CHARS]
    return {"name": meta.get("name") or name, "folder": name, "text": text, "files": files, "warnings": warnings,
            "fingerprint": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]}


AGENT_ROLE = ("당신은 Claude 마케팅 에이전트입니다. 경쟁 브리프(competitive brief)로 시장의 빈틈을 찾고, "
              "그 빈틈을 해외 식품 박람회 부스 전략으로 바꾸는 일을 합니다. 결과물은 한국어로 씁니다.")


def research_system(agent_skill):
    return f"{AGENT_ROLE}\n\n{PLANNER_PERSONA}\n\n# 업무 방법: 경쟁 브리프\n\n{agent_skill['text']}"


def planner_system(agent_skill, booth_skill):
    parts = [AGENT_ROLE, PLANNER_PERSONA,
             "# 업무 방법 1: 경쟁 브리프 (이미 수행됨, 결과가 입력으로 주어짐)\n\n" + agent_skill["text"],
             "# 업무 방법 2: 부스 컨셉 기획 (순서대로 따르세요)\n\n" + booth_skill["instructions"]]
    if booth_skill["examples"]:
        parts.append("# 좋은 예시 (형식·밀도 참고, 사실 근거로 쓰지 말 것)\n\n" + booth_skill["examples"])
    return "\n\n".join(parts)


def reviewer_system(booth_skill):
    return REVIEWER_PERSONA + "\n\n# 채점표\n아래 기준으로 기획안을 채점하세요.\n\n" + booth_skill["rubric_text"]


# ---------------------------------------------------------------------------
# ① 경쟁 브리프 (웹 검색)
# ---------------------------------------------------------------------------

def _inputs_block(inputs, profile):
    profile_text = "\n".join(f"- {k}: {v}" for k, v in profile.items() if v) or "(입력 없음)"
    site = inputs.get("exhibition_website")
    return f"""[제품] {inputs['name']} / [시장] {inputs['country_en']}
[박람회] {inputs.get('exhibition_name') or '(미정)'}{f' ({site})' if site else ''}

[기업 제품 정보] (근거 표기: "기업:항목명")
{profile_text}"""


def _research_prompt(inputs_text, with_web):
    how = ("웹 검색으로 최신 자료를 직접 찾으세요. 대상 국가의 유통몰·언론·업계지·박람회 공식 사이트를 우선합니다. "
           "notes의 source_url에는 실제로 검색 결과에서 연 페이지 URL만 적으세요."
           if with_web else
           "웹 검색 없이 알고 있는 지식으로 정리하세요. 확실하지 않은 브랜드·가격·수치는 쓰지 마세요. source_url은 빈 문자열.")
    topics = ", ".join(f"{k}({v})" for k, v in v9.RESEARCH_TOPICS.items())
    return f"""업무 방법(경쟁 브리프) 1~5단계를 수행하세요. 부스 실행안은 아직 쓰지 마세요. {how}

{inputs_text}

- notes: 조사 메모 6~{MAX_NOTES}개. id는 R1부터 차례로. topic은 {topics} 중 하나.
- competitors: 3~6개. type은 direct(직접)·indirect(간접)·trade_show(같은 박람회 출전) 중 하나.
- basis에는 근거가 된 조사 메모 id("R3")나 기업 정보("기업:강점")를 적고, 근거가 없으면 "기획".
- 설명은 한국어. 브랜드·제품명·문구는 원문 표기 유지.

최종 답변은 아래 형식의 JSON 객체 하나만 출력하세요:
{COMPETITIVE_SCHEMA}"""


def _country_iso2(country_en):
    try:
        return v9._country_iso2(country_en)
    except Exception:
        return None


def normalize_notes(data, citations, method):
    """조사 메모 정리. 모델이 붙인 R번호를 유지하고(경쟁사 근거가 그 번호를 가리키므로), 출처를 확인해 표시한다."""
    notes, taken = [], set()
    for n in (data or {}).get("notes") or []:
        if not isinstance(n, dict) or not str(n.get("text") or "").strip():
            continue
        nid = str(n.get("id") or "").strip().upper()
        if not re.fullmatch(r"R\d+", nid) or nid in taken:
            nid = next(f"R{i}" for i in range(1, 1000) if f"R{i}" not in taken)
        taken.add(nid)
        url = str(n.get("source_url") or "").strip() if method == "web_search" else ""
        if not url:
            status = "AI 지식"
        elif url in citations or any(url.rstrip("/") == c.rstrip("/") for c in citations):
            status = "웹 출처"
        else:
            status = "출처 미확인"   # 모델이 적은 URL이 실제 검색 결과에 없음
        topic = n.get("topic") if n.get("topic") in v9.RESEARCH_TOPICS else "trend"
        notes.append({"id": nid, "topic": topic, "topic_label": v9.RESEARCH_TOPICS[topic],
                      "text": str(n["text"]).strip(), "source_url": url,
                      "source_title": str(n.get("source_title") or citations.get(url, "") or "").strip(),
                      "source_status": status})
        if len(notes) >= MAX_NOTES:
            break
    return notes


def normalize_competitive(data, note_index, profile):
    data = data if isinstance(data, dict) else {}

    def text(obj, key):
        return str((obj or {}).get(key) or "").strip()

    def basis(obj):
        return v9._classify_basis((obj or {}).get("basis"), note_index, profile)

    competitors = []
    for c in data.get("competitors") or []:
        if isinstance(c, dict) and text(c, "name"):
            ctype = text(c, "type") if text(c, "type") in COMPETITOR_TYPES else "direct"
            competitors.append({**{k: text(c, k) for k in ("name", "owner", "price", "channels", "positioning",
                                                            "key_message", "strengths", "weaknesses")},
                                "type": ctype, "type_label": COMPETITOR_TYPES[ctype], **basis(c)})
    white = data.get("white_space") if isinstance(data.get("white_space"), dict) else {}
    return {
        "market_snapshot": text(data, "market_snapshot"),
        "competitors": competitors[:6],
        "common_claims": [str(x).strip() for x in data.get("common_claims") or [] if str(x).strip()][:5],
        "white_space": {"text": text(white, "text"), "why": text(white, "why"), **basis(white)},
        "our_edge": [{"text": text(e, "text"), "against": text(e, "against"), **basis(e)}
                     for e in data.get("our_edge") or [] if isinstance(e, dict) and text(e, "text")][:4],
        "objections": [{"objection": text(o, "objection"), "answer": text(o, "answer"), **basis(o)}
                       for o in data.get("objections") or [] if isinstance(o, dict) and text(o, "objection")][:4],
    }


def competitive_research(client, inputs, profile, agent_skill, stats):
    """반환: (경쟁 브리프 원본 dict, research={"method", "notes", "citations", "error", "search_errors"})"""
    inputs_text = _inputs_block(inputs, profile)
    system = research_system(agent_skill)
    error = ""
    if WEB_SEARCH:
        tool = {"type": "web_search_20260209", "name": "web_search", "max_uses": WEB_SEARCH_MAX_USES}
        iso2 = _country_iso2(inputs["country_en"])
        if iso2:
            tool["user_location"] = {"type": "approximate", "country": iso2}
        try:
            data, result = _ask_json(client, system, _research_prompt(inputs_text, True), tools=[tool], stats=stats)
            citations, search_errors = _collect_citations(result["content"])
            notes = normalize_notes(data, citations, "web_search")
            if notes or data.get("competitors"):
                return data, {"method": "web_search", "notes": notes, "error": "", "search_errors": search_errors,
                              "citations": [{"url": u, "title": t} for u, t in citations.items()]}
            error = "웹 검색 답변에서 조사 메모를 찾지 못함"
        except ClaudeRefusal:
            raise
        except Exception as e:
            error = f"웹 검색 실패: {e}"
            logger.warning("Claude 웹 검색 조사 실패 (모델 지식으로 대체): %s", e)
    data, _ = _ask_json(client, system, _research_prompt(inputs_text, False), stats=stats)
    return data, {"method": "knowledge", "notes": normalize_notes(data, {}, "knowledge"), "citations": [],
                  "error": error, "search_errors": []}


# ---------------------------------------------------------------------------
# ②~④ 기획 → 채점 → 수정
# ---------------------------------------------------------------------------

PLAN_SCHEMA = f"""{{
  "brief": {v9.BRIEF_SCHEMA},
  "plan": {v9.BOOTH_SCHEMA}
}}"""


def _facts(inputs_text, competitive_raw, notes):
    brief = {k: v for k, v in (competitive_raw or {}).items() if k != "notes"}
    memo = [{"id": n["id"], "topic": n["topic_label"], "text": n["text"], "source": n["source_status"]} for n in notes]
    return (f"{inputs_text}\n\n[경쟁 브리프]\n{json.dumps(brief, ensure_ascii=False, indent=1)}\n\n"
            f"[조사 메모] (근거 표기: 메모 id, 예: \"R3\")\n"
            + (json.dumps(memo, ensure_ascii=False, indent=1) if memo else "(조사 메모 없음)"))


def plan_booth_concept(client, inputs, profile, facts, note_index, agent_skill, booth_skill, stats):
    planner = planner_system(agent_skill, booth_skill)
    country = inputs["country_en"]

    # ② 전략 뼈대 + 기획안 초안 (한 번에: 경쟁 브리프의 빈틈이 빅 아이디어로 이어지게)
    plan, _ = _ask_json(client, planner, f"""경쟁 브리프에서 찾은 포지셔닝 빈틈을 빅 아이디어로 삼아 {country} 박람회 부스 컨셉을 기획하세요.
업무 방법 2의 1~4단계(인사이트·타깃 바이어·빅 아이디어·믿을 이유)를 brief에, 5~9단계(6개 실행 항목·동선·KPI)를 plan에 쓰세요.
경쟁사 부스·제품과 같아 보이는 연출은 피하고, 바이어 반론에 대한 답이 부스 안에 준비되게 하세요.

{facts}

{v9.BOOTH_RULES}
- brief: 인사이트 2~4개, 타깃 바이어 1~2순위, 빅 아이디어 한 문장(바이어 언어 + 한국어), 믿을 이유 2~4개.
- visitor_flow: 3초·30초·3분 동선을 각각 한두 문장. kpis: 부스 성과 지표 2~3개.

JSON 객체 하나만 출력하세요:
{PLAN_SCHEMA}""", stats=stats)
    brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
    draft = plan.get("plan") if isinstance(plan.get("plan"), dict) else plan

    # ③ 바이어 채점
    review, final, stage = None, draft, "draft"
    try:
        ids = ", ".join(c["id"] for c in booth_skill["criteria"])
        review, _ = _ask_json(client, reviewer_system(booth_skill), f"""아래는 {inputs['name']}의 {country} 박람회 부스 기획 초안입니다.
채점표의 각 항목({ids})을 1~5점으로 채점하고 바이어 입장에서 검토 의견을 주세요.
특히 경쟁 브리프의 경쟁 제품과 비교해 차별성이 드러나는지 보세요.

[조사 결과]
{facts}

[기획 초안]
{json.dumps({"brief": brief, "plan": draft}, ensure_ascii=False, indent=1)}

- scores: 항목 id별 {{"score": 1~5, "reason": "한 줄 이유"}}
- overall: 한 줄 총평 (한국어)
- comments: 고칠 점 3~6개. section은 main_visual/slogan/signature_pairing/demonstration/packaging/merchandising/overall 중 하나,
  issue(문제), suggestion(바이어가 원하는 개선 방향). 한국어.
JSON 객체 하나만: {{"scores": {{"insight": {{"score": 4, "reason": ""}}}}, "overall": "", "comments": [{{"section": "", "issue": "", "suggestion": ""}}]}}""",
                              effort=REVIEW_EFFORT, stats=stats)
    except Exception as e:
        logger.warning("부스 컨셉 채점 실패 (초안 사용): %s", e)
        review = None
    scores = v9.normalize_scores(review, booth_skill["criteria"])
    low = [x for x in scores if x["score"] is not None and x["score"] < REVISE_BELOW]

    # ④ 기준 미만 항목이 있을 때만 수정
    if review and low:
        try:
            revised, _ = _ask_json(client, planner, f"""당신이 쓴 부스 기획 초안이 바이어 채점표로 평가되었습니다. 점수가 낮은 항목을 중심으로 고쳐 최종안을 쓰세요.
받아들이지 않는 의견은 반영하지 않아도 되지만, applied에 무엇을 반영했는지 적으세요.

{facts}

[전략 뼈대]
{json.dumps(brief, ensure_ascii=False, indent=1)}

[기획 초안]
{json.dumps(draft, ensure_ascii=False, indent=1)}

[채점과 검토 의견]
{json.dumps(review, ensure_ascii=False, indent=1)}
기준 점수({REVISE_BELOW}점) 미만: {", ".join(f"{x['label']}({x['score']}점)" for x in low)}

{v9.BOOTH_RULES}
- visitor_flow·kpis도 유지하세요.
- applied: 반영한 의견 요약 1~5개 (한국어)

JSON 객체 하나만 (위 초안과 같은 구조 + applied):
{v9.BOOTH_SCHEMA[:-1]},
  "applied": [""]
}}""", stats=stats)
            if isinstance(revised, dict) and revised.get("summary"):
                final, stage = revised, "revised"
        except Exception as e:
            logger.warning("부스 컨셉 수정 실패 (초안 사용): %s", e)
    elif review:
        stage = "passed"

    booth = v9.normalize_booth(final, note_index, profile)
    review = review if isinstance(review, dict) else {}
    booth.update({
        "brief": v9.normalize_brief(brief, note_index, profile),
        "mode": "B",
        "stage": stage,
        "revise_below": REVISE_BELOW,
        "scores": scores,
        "review": {"overall": str(review.get("overall") or "").strip(),
                   "comments": [{"section": v9.BOOTH_SECTIONS.get(c.get("section"), (c.get("section") or "전체",))[0],
                                 "issue": str(c.get("issue") or "").strip(),
                                 "suggestion": str(c.get("suggestion") or "").strip()}
                                for c in review.get("comments") or [] if isinstance(c, dict)]},
        "applied": [str(a).strip() for a in (final.get("applied") or []) if str(a).strip()] if stage == "revised" else [],
    })
    return booth


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS booth_cache (k TEXT PRIMARY KEY, v TEXT, at TEXT)")
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fresh(ts, days):
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(ts) < timedelta(days=days)
    except (TypeError, ValueError):
        return False


def plan_booth(inputs, *, force=False, db_path=None, client=None):
    """사용자 입력만으로 Claude 마케팅 에이전트가 부스 컨셉을 기획한다.
    inputs: name, country_en, exhibition_name, exhibition_website, strengths, ingredients, certifications, price"""
    profile = {label: (inputs.get(k) or "").strip()[:300] for k, label in PROFILE_LABELS.items()
               if (inputs.get(k) or "").strip()}
    agent_skill = load_agent_skill()
    booth_skill = load_skill(BOOTH_SKILL)
    key = hashlib.sha256(json.dumps({
        "v": VERSION, "m": MODEL, "e": EFFORT, "re": REVIEW_EFFORT, "w": WEB_SEARCH, "wn": WEB_SEARCH_MAX_USES,
        "rb": REVISE_BELOW, "as": agent_skill["fingerprint"], "bs": booth_skill["fingerprint"], "p": profile,
        "i": {k: inputs.get(k) for k in ("name", "country_en", "exhibition_name", "exhibition_website")},
    }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    conn = _db(db_path or DEFAULT_DB_PATH)
    try:
        if not force:
            row = conn.execute("SELECT v, at FROM booth_cache WHERE k=?", (key,)).fetchone()
            if row and _fresh(row[1], CACHE_TTL_DAYS):
                return {**json.loads(row[0]), "from_cache": True}

        client = client or get_client()
        stats = {}
        competitive_raw, research = competitive_research(client, inputs, profile, agent_skill, stats)
        note_index = {n["id"]: n for n in research["notes"]}
        facts = _facts(_inputs_block(inputs, profile), competitive_raw, research["notes"])
        booth = plan_booth_concept(client, inputs, profile, facts, note_index, agent_skill, booth_skill, stats)
        booth.update({
            "competitive": normalize_competitive(competitive_raw, note_index, profile),
            "research": research,
            "source_mode": "claude_marketing_agent",
            "skill": {"name": booth_skill["name"], "folder": booth_skill["folder"], "files": booth_skill["files"],
                      "fingerprint": booth_skill["fingerprint"], "warnings": booth_skill["warnings"]},
            "agent_skill": {k: agent_skill[k] for k in ("name", "folder", "files", "fingerprint", "warnings")},
            "planner_persona": PLANNER_PERSONA,
            "reviewer_persona": REVIEWER_PERSONA,
            "has_profile": bool(profile),
            "model": MODEL,
            "effort": EFFORT,
            "served_models": stats.get("models", []),
            "fallback_used": stats.get("fallback_used", False),
            "usage": {k: v for k, v in stats.items() if k not in ("models", "fallback_used")},
            "fetched_at": _now(),
            "from_cache": False,
            "version": VERSION,
        })
        conn.execute("INSERT OR REPLACE INTO booth_cache VALUES (?, ?, ?)",
                     (key, json.dumps(booth, ensure_ascii=False), booth["fetched_at"]))
        conn.commit()
        return booth
    finally:
        conn.close()

"""스킬 문서(마크다운)를 읽어 OpenAI 프롬프트로 쓰는 로더.

폴더 구조 (skills/<이름>/)
  SKILL.md       필수. 업무 방법(작업 순서·체크리스트·금지 사항). 맨 앞 --- 사이의 name/description은 읽고 본문에서 뺌
  rubric.md      선택. 검토자 채점표. "- id | 이름 | 5점의 모습" 줄을 채점 항목으로 읽음
  examples.md    선택. 좋은 예시 (형식·밀도 참고)
  references/    선택. 추가 참고 문서(*.md). 글자 수 한도를 넘으면 뒤에서부터 자름

Claude 스킬 문서를 그대로 넣어도 되도록, Claude 전용 도구 사용 지시(예: "Use the Read tool")가 있는 줄은 뺍니다.
"""

import hashlib
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
DEFAULT_SKILL = "booth_marketing"
MAX_SKILL_CHARS = 16000        # SKILL.md + 예시 + 참고 문서 합계 (rubric 별도)
MAX_RUBRIC_CHARS = 4000

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
CLAUDE_TOOL_LINE = re.compile(
    r"\b(Read|Write|Edit|Bash|Glob|Grep|WebFetch|WebSearch|Task|TodoWrite|Skill|NotebookEdit)\s+tool\b"
    r"|\$ARGUMENTS|\bmcp__\w+", re.IGNORECASE)
RUBRIC_LINE = re.compile(r"^\s*-\s*([a-z][a-z0-9_]*)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*$")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _split_front_matter(text):
    meta = {}
    m = FRONT_MATTER.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end():]
    return meta, text


def clean_for_openai(text):
    """Claude 전용 도구 지시가 있는 줄을 뺀다. 나머지 업무 방법은 그대로 둔다."""
    return "\n".join(line for line in text.splitlines() if not CLAUDE_TOOL_LINE.search(line)).strip()


def parse_rubric(text):
    criteria = []
    for line in (text or "").splitlines():
        m = RUBRIC_LINE.match(line)
        if m and m.group(1) not in {c["id"] for c in criteria}:
            criteria.append({"id": m.group(1), "label": m.group(2), "description": m.group(3)})
    return criteria


def load_skill(name=None):
    """반환: {"name", "description", "instructions", "examples", "references", "rubric_text", "criteria",
             "fingerprint", "chars", "warnings", "files"}"""
    name = (name or DEFAULT_SKILL).strip()
    warnings = []
    folder = os.path.join(SKILLS_DIR, name)
    if not os.path.isfile(os.path.join(folder, "SKILL.md")):
        warnings.append(f"스킬 '{name}'을(를) 찾지 못해 기본 스킬({DEFAULT_SKILL})을 씁니다.")
        name, folder = DEFAULT_SKILL, os.path.join(SKILLS_DIR, DEFAULT_SKILL)

    files = ["SKILL.md"]
    meta, body = _split_front_matter(_read(os.path.join(folder, "SKILL.md")))
    instructions = clean_for_openai(body)
    examples = clean_for_openai(_read(os.path.join(folder, "examples.md")))
    if examples:
        files.append("examples.md")

    references = []
    ref_dir = os.path.join(folder, "references")
    if os.path.isdir(ref_dir):
        for fn in sorted(os.listdir(ref_dir)):
            if fn.endswith(".md"):
                references.append(f"## {fn}\n{clean_for_openai(_split_front_matter(_read(os.path.join(ref_dir, fn)))[1])}")
                files.append(f"references/{fn}")

    # 글자 수 한도: 업무 방법 > 예시 > 참고 문서 순으로 지키고, 넘치면 뒤쪽부터 자른다
    budget = MAX_SKILL_CHARS
    parts = []
    for label, text in (("instructions", instructions), ("examples", examples), ("references", "\n\n".join(references))):
        if len(text) > budget:
            if text:
                warnings.append(f"스킬 {label}이(가) 길어 {budget}자까지만 사용합니다.")
            text = text[:max(budget, 0)]
        budget -= len(text)
        parts.append(text)
    instructions, examples, references_text = parts

    rubric_text = clean_for_openai(_read(os.path.join(folder, "rubric.md")))
    if rubric_text:
        files.append("rubric.md")
    criteria = parse_rubric(rubric_text)
    if not criteria:  # 채점표가 없는 스킬(예: 가져온 Claude 스킬)은 기본 채점표를 쓴다
        rubric_text = clean_for_openai(_read(os.path.join(SKILLS_DIR, DEFAULT_SKILL, "rubric.md")))
        criteria = parse_rubric(rubric_text)
        if name != DEFAULT_SKILL:
            warnings.append("이 스킬에 채점표(rubric.md)가 없어 기본 채점표를 씁니다.")
    rubric_text = rubric_text[:MAX_RUBRIC_CHARS]

    combined = "\n".join([instructions, examples, references_text, rubric_text])
    return {
        "name": meta.get("name") or name,
        "folder": name,
        "description": meta.get("description", ""),
        "instructions": instructions,
        "examples": examples,
        "references": references_text,
        "rubric_text": rubric_text,
        "criteria": criteria,
        "fingerprint": hashlib.sha1(combined.encode("utf-8")).hexdigest()[:12],
        "chars": len(combined),
        "warnings": warnings,
        "files": files,
    }


def planner_system_prompt(persona, skill):
    parts = [persona, "# 업무 방법 (스킬)\n아래 방법을 순서대로 따르세요.\n\n" + skill["instructions"]]
    if skill["examples"]:
        parts.append("# 좋은 예시 (형식·밀도 참고, 사실 근거로 쓰지 말 것)\n\n" + skill["examples"])
    if skill["references"]:
        parts.append("# 참고 문서\n\n" + skill["references"])
    return "\n\n".join(parts)


def reviewer_system_prompt(persona, skill):
    return persona + "\n\n# 채점표\n아래 기준으로 기획안을 채점하세요.\n\n" + skill["rubric_text"]

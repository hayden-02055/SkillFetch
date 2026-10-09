import json
from pathlib import Path

from pydantic import ValidationError

from skillfetch import llm
from skillfetch.models import TaskAnalysis
from skillfetch.parser import InvalidSkillError, parse_frontmatter

MAX_QUERIES = 3

SYSTEM_PROMPT = """\
You decide whether a coding agent would benefit from an external Agent Skill \
(a SKILL.md file with specialized instructions) for the user's task.

Set requires_skill to false when:
- the task is general programming a capable coding agent already handles well, or
- one of the listed local skills already covers it.

Otherwise set requires_skill to true and write 1-3 short GitHub search queries \
(2-4 keywords each) naming the specialized capability, e.g. "react design review" \
or "pdf form filling". Do not include the words "agent", "skill" or "SKILL.md".

Respond with JSON only:
{"task": "<short task summary>", "requires_skill": <true|false>, "search_queries": ["..."]}"""


def find_local_skills(dirs: list[Path] | None = None) -> list[dict]:
    """Name/description of skills already installed for Claude Code."""
    if dirs is None:
        dirs = [Path.home() / ".claude" / "skills", Path.cwd() / ".claude" / "skills"]
    skills = []
    for directory in dirs:
        for skill_file in sorted(directory.glob("*/SKILL.md")):
            try:
                meta, _ = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, InvalidSkillError):
                continue
            if isinstance(meta.get("name"), str):
                skills.append(
                    {"name": meta["name"], "description": str(meta.get("description", ""))}
                )
    return skills


def analyze_task(task: str, local_skills: list[dict]) -> TaskAnalysis:
    user = f"Task:\n{task}\n\nLocal skills:\n{json.dumps(local_skills, ensure_ascii=False)}"
    data = llm.chat_json(SYSTEM_PROMPT, user)
    try:
        analysis = TaskAnalysis.model_validate(data)
    except ValidationError as exc:
        raise llm.LLMError(f"LLM returned an unexpected task analysis: {exc}") from exc
    queries = [q.strip() for q in analysis.search_queries if q.strip()][:MAX_QUERIES]
    if analysis.requires_skill and not queries:
        raise llm.LLMError("LLM asked for a skill search but returned no search queries.")
    return analysis.model_copy(update={"search_queries": queries})

import re

import yaml

from skillfetch.models import SkillCandidate

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


class InvalidSkillError(ValueError):
    pass


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter mapping, body)."""
    text = text.lstrip("﻿")
    match = _FRONTMATTER.match(text)
    if not match:
        raise InvalidSkillError("missing YAML frontmatter")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise InvalidSkillError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise InvalidSkillError("frontmatter is not a mapping")
    return meta, text[match.end() :]


def parse_skill(content: str, repository: str, commit_sha: str, skill_path: str) -> SkillCandidate:
    meta, body = parse_frontmatter(content)
    fields = {}
    for key in ("name", "description"):
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidSkillError(f"missing '{key}' in frontmatter")
        fields[key] = " ".join(value.split())
    if not body.strip():
        raise InvalidSkillError("empty skill body")
    return SkillCandidate(
        name=fields["name"],
        description=fields["description"],
        repository=repository,
        commit_sha=commit_sha,
        skill_path=skill_path,
        source_url=f"https://github.com/{repository}/blob/{commit_sha}/{skill_path}",
        content=content,
    )

import pytest
from conftest import SHA, fixture_text

from skillfetch.parser import InvalidSkillError, parse_skill


def _parse(content: str):
    return parse_skill(content, "example/agent-skills", SHA, "skills/x/SKILL.md")


def test_parses_frontmatter_and_keeps_original_content():
    content = fixture_text("frontend_design.md")
    skill = _parse(content)
    assert skill.name == "frontend-design"
    # folded YAML description is normalized to one line
    assert skill.description == (
        "Guidance for building polished, accessible React dashboards and component layouts."
    )
    assert skill.commit_sha == SHA
    assert skill.source_url == (
        f"https://github.com/example/agent-skills/blob/{SHA}/skills/x/SKILL.md"
    )
    assert skill.content == content


@pytest.mark.parametrize(
    "content, reason",
    [
        (fixture_text("invalid.md"), "missing YAML frontmatter"),
        ("---\nname: [unclosed\n---\nbody\n", "invalid YAML"),
        ("---\n- a\n- b\n---\nbody\n", "not a mapping"),
        ("---\ndescription: d\n---\nbody\n", "missing 'name'"),
        ("---\nname: n\n---\nbody\n", "missing 'description'"),
        ("---\nname: n\ndescription: 3\n---\nbody\n", "missing 'description'"),
        ("---\nname: n\ndescription: d\n---\n\n  \n", "empty skill body"),
        ("---\nname: n\ndescription: d\nbody without closing fence\n", "missing YAML"),
    ],
)
def test_rejects_malformed_skill(content, reason):
    with pytest.raises(InvalidSkillError, match=reason):
        _parse(content)


def test_accepts_crlf_and_bom():
    skill = _parse("﻿---\r\nname: n\r\ndescription: d\r\n---\r\nbody\r\n")
    assert (skill.name, skill.description) == ("n", "d")

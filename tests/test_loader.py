from datetime import UTC, datetime

import pytest
from conftest import SHA, fixture_text

from skillfetch import loader
from skillfetch.loader import LoadError, load_skill
from skillfetch.models import (
    DiscoveryCache,
    RankedCandidate,
    SecurityFinding,
    SecurityReport,
    SkillCandidate,
    SkillEvaluation,
)
from skillfetch.parser import parse_skill

CLEAN = SecurityReport(findings=[])


def _ranked(content=None, name=None, sha=SHA, path="skills/frontend-design/SKILL.md"):
    candidate = parse_skill(
        content or fixture_text("frontend_design.md"), "example/agent-skills", sha, path
    )
    if name is not None:
        candidate = candidate.model_copy(update={"name": name})
    evaluation = SkillEvaluation(relevance=0.9, reason="fits", recommended=True)
    return RankedCandidate(candidate=candidate, evaluation=evaluation)


def test_load_writes_skill_into_session():
    ranked = _ranked()
    path = load_skill(ranked, CLEAN)

    session = loader.current_session()
    assert path == session / "frontend-design" / "SKILL.md"
    assert session.parent == loader.home() / "sessions"
    assert path.read_text(encoding="utf-8") == ranked.candidate.content
    assert path.stat().st_mode & 0o111 == 0  # not executable
    assert [s.commit_sha for s in loader.list_loaded()] == [SHA]


def test_loading_same_source_twice_is_idempotent():
    first = load_skill(_ranked(), CLEAN)
    assert load_skill(_ranked(), CLEAN) == first


def test_never_overwrites_a_different_skill_with_same_name():
    path = load_skill(_ranked(), CLEAN)
    original = path.read_bytes()
    other = _ranked(content=fixture_text("frontend_design.md") + "\nchanged\n", sha="f" * 40)

    with pytest.raises(LoadError, match="already loaded"):
        load_skill(other, CLEAN)
    assert path.read_bytes() == original


def test_blocked_report_prevents_loading():
    finding = SecurityFinding(category="instruction_override", severity="high", line=1, excerpt="x")
    with pytest.raises(LoadError, match="blocked"):
        load_skill(_ranked(), SecurityReport(findings=[finding]))
    assert loader.current_session() is None


def test_skill_name_cannot_escape_session_directory():
    path = load_skill(_ranked(name="../../../etc/passwd"), CLEAN)
    session = loader.current_session().resolve()
    assert path.parent.parent == session
    assert path.parent.name == "etc-passwd"


def test_skill_name_without_usable_characters_is_rejected():
    with pytest.raises(LoadError, match="no usable characters"):
        load_skill(_ranked(name="../.."), CLEAN)


def test_oversized_skill_is_rejected():
    big = fixture_text("frontend_design.md") + "x" * loader.MAX_SKILL_BYTES
    with pytest.raises(LoadError, match="larger than"):
        load_skill(_ranked(content=big), CLEAN)


def test_tampered_session_pointer_is_ignored():
    pointer = loader.home() / "current_session"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("../../outside")
    assert loader.current_session() is None
    session = loader.current_session(create=True)
    assert session.parent == loader.home() / "sessions"


def test_clean_removes_session_files():
    path = load_skill(_ranked(), CLEAN)
    removed = loader.clean_session()
    assert removed == path.parent.parent
    assert not removed.exists()
    assert loader.list_loaded() == []
    assert loader.clean_session() is None


def test_get_candidate_requires_previous_discovery():
    with pytest.raises(LoadError, match="Run `skillfetch discover` first"):
        loader.get_candidate(1)


def test_get_candidate_rejects_unknown_id():
    loader.save_discovery(
        DiscoveryCache(task="t", created_at=datetime.now(UTC).isoformat(), recommendations=[])
    )
    with pytest.raises(LoadError, match="Unknown candidate id 1"):
        loader.get_candidate(1)


def test_get_candidate_returns_saved_recommendation():
    ranked = _ranked()
    loader.save_discovery(DiscoveryCache(task="t", created_at="now", recommendations=[ranked]))
    assert loader.get_candidate(1) == ranked


def test_skill_candidate_model_matches_spec_fields():
    assert list(SkillCandidate.model_fields) == [
        "name",
        "description",
        "repository",
        "commit_sha",
        "skill_path",
        "source_url",
        "content",
    ]

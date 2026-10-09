import pytest
from conftest import SHA

from skillfetch import llm
from skillfetch.models import SkillCandidate
from skillfetch.ranker import CONTENT_PREVIEW_CHARS, rank


def _candidate(name: str, content: str = "body") -> SkillCandidate:
    return SkillCandidate(
        name=name,
        description=f"{name} description",
        repository="example/repo",
        commit_sha=SHA,
        skill_path=f"{name}/SKILL.md",
        source_url=f"https://github.com/example/repo/blob/{SHA}/{name}/SKILL.md",
        content=content,
    )


def _respond(monkeypatch, evaluations):
    calls = []

    def fake(system, user):
        calls.append(user)
        return {"evaluations": evaluations}

    monkeypatch.setattr(llm, "chat_json", fake)
    return calls


def test_returns_top_three_recommended_by_relevance(monkeypatch):
    candidates = [_candidate(n) for n in "abcde"]
    _respond(
        monkeypatch,
        [
            {"id": 0, "relevance": 0.5, "reason": "ok", "recommended": True},
            {"id": 1, "relevance": 0.99, "reason": "great", "recommended": False},
            {"id": 2, "relevance": 1.7, "reason": "best", "recommended": True},
            {"id": 3, "relevance": 0.7, "reason": "good", "recommended": True},
            {"id": 4, "relevance": 0.6, "reason": "fine", "recommended": True},
        ],
    )
    ranked = rank("task", candidates, [])
    assert [r.candidate.name for r in ranked] == ["c", "d", "e"]
    assert ranked[0].evaluation.relevance == 1.0  # clamped


def test_returns_empty_when_nothing_is_recommended(monkeypatch):
    _respond(monkeypatch, [{"id": 0, "relevance": 0.2, "reason": "no", "recommended": False}])
    assert rank("task", [_candidate("a")], []) == []


def test_skips_malformed_and_out_of_range_entries(monkeypatch):
    _respond(
        monkeypatch,
        [
            {"id": 7, "relevance": 0.9, "reason": "x", "recommended": True},
            {"id": "zero", "relevance": 0.9, "reason": "x", "recommended": True},
            {"id": 0, "reason": "missing relevance", "recommended": True},
            {"id": 1, "relevance": 0.8, "reason": "ok", "recommended": True},
        ],
    )
    ranked = rank("task", [_candidate("a"), _candidate("b")], [])
    assert [r.candidate.name for r in ranked] == ["b"]


@pytest.mark.parametrize("evaluations", [[], [{"id": 0}], "nonsense"])
def test_no_valid_evaluations_is_an_llm_error(monkeypatch, evaluations):
    _respond(monkeypatch, evaluations)
    with pytest.raises(llm.LLMError, match="no valid skill evaluations"):
        rank("task", [_candidate("a")], [])


def test_no_candidates_skips_llm(monkeypatch):
    calls = _respond(monkeypatch, [])
    assert rank("task", [], []) == []
    assert calls == []


def test_prompt_delimits_and_truncates_untrusted_content(monkeypatch):
    calls = _respond(monkeypatch, [{"id": 0, "relevance": 0.5, "reason": "x", "recommended": True}])
    rank("task", [_candidate("a", content="A" * (CONTENT_PREVIEW_CHARS + 500))], [])
    prompt = calls[0]
    assert "A" * CONTENT_PREVIEW_CHARS in prompt
    assert "A" * (CONTENT_PREVIEW_CHARS + 1) not in prompt
    assert "<<<CANDIDATE 0 " in prompt and "<<<END CANDIDATE 0 " in prompt

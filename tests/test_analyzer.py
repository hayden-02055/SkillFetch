from types import SimpleNamespace

import httpx
import openai
import pytest

from skillfetch import llm
from skillfetch.analyzer import analyze_task, find_local_skills


def _respond(monkeypatch, data):
    monkeypatch.setattr(llm, "chat_json", lambda system, user: data)


def test_analysis_trims_and_caps_queries(monkeypatch):
    _respond(
        monkeypatch,
        {"task": "t", "requires_skill": True, "search_queries": [" a ", "", "b", "c", "d"]},
    )
    assert analyze_task("t", []).search_queries == ["a", "b", "c"]


def test_skill_not_required(monkeypatch):
    _respond(monkeypatch, {"task": "t", "requires_skill": False, "search_queries": []})
    assert analyze_task("rename a variable", []).requires_skill is False


def test_search_requested_without_queries_is_an_error(monkeypatch):
    _respond(monkeypatch, {"task": "t", "requires_skill": True, "search_queries": []})
    with pytest.raises(llm.LLMError, match="no search queries"):
        analyze_task("t", [])


def test_unexpected_shape_is_an_error(monkeypatch):
    _respond(monkeypatch, {"answer": "yes"})
    with pytest.raises(llm.LLMError, match="unexpected task analysis"):
        analyze_task("t", [])


def test_find_local_skills(tmp_path):
    good = tmp_path / "skills" / "pdf"
    good.mkdir(parents=True)
    (good / "SKILL.md").write_text("---\nname: pdf\ndescription: PDF tools\n---\nbody\n")
    bad = tmp_path / "skills" / "broken"
    bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter")

    skills = find_local_skills([tmp_path / "skills", tmp_path / "missing"])
    assert skills == [{"name": "pdf", "description": "PDF tools"}]


# --- llm.chat_json failure handling ---------------------------------------


def test_missing_api_key_is_an_llm_error():
    with pytest.raises(llm.LLMError, match="LLM API call failed"):
        llm.chat_json("system", "user")


class _FakeOpenAI:
    content: str | None = "{}"
    error: Exception | None = None

    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.parametrize(
    "content, error",
    [
        ("not json", "invalid JSON"),
        ("[1, 2]", "not an object"),
        (None, "invalid JSON"),
    ],
)
def test_bad_llm_output_is_an_llm_error(monkeypatch, content, error):
    monkeypatch.setattr(_FakeOpenAI, "content", content)
    monkeypatch.setattr(llm, "OpenAI", _FakeOpenAI)
    with pytest.raises(llm.LLMError, match=error):
        llm.chat_json("system", "user")


def test_api_connection_error_is_an_llm_error(monkeypatch):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    monkeypatch.setattr(_FakeOpenAI, "error", openai.APIConnectionError(request=request))
    monkeypatch.setattr(llm, "OpenAI", _FakeOpenAI)
    with pytest.raises(llm.LLMError, match="LLM API call failed"):
        llm.chat_json("system", "user")


def test_valid_json_object_is_returned(monkeypatch):
    monkeypatch.setattr(_FakeOpenAI, "content", '{"ok": true}')
    monkeypatch.setattr(llm, "OpenAI", _FakeOpenAI)
    assert llm.chat_json("system", "user") == {"ok": True}

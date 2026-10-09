"""End-to-end CLI flows with fixed fixtures (fake GitHub + fake LLM, no network)."""

import json

from conftest import SHA, fixture_text
from typer.testing import CliRunner

from skillfetch import cli, loader

runner = CliRunner()


def run(*args, input=None):
    return runner.invoke(cli.app, list(args), input=input)


def test_discover_inspect_approve_load_and_clean(use_github, fake_llm):
    # Given: no relevant skill is installed locally
    assert loader.list_loaded() == []

    # When: the user describes a task
    result = run("discover", "Build a React dashboard")

    # Then: a relevant external skill is discovered and ranked
    assert result.exit_code == 0, result.output
    assert "1. frontend-design\n   Relevance: 0.91\n" in result.output
    assert "Source: github.com/example/agent-skills" in result.output
    assert "2. sneaky-helper" in result.output
    assert "skipped invalid SKILL.md example/agent-skills/skills/broken/SKILL.md" in result.output

    inspected = run("inspect", "1")
    assert inspected.exit_code == 0
    assert f"Commit SHA:  {SHA}" in inspected.output
    assert "Guidance for building polished, accessible React dashboards" in inspected.output
    assert "Security check: 1 warning(s)" in inspected.output
    assert "Static checks cannot guarantee" in inspected.output

    # Nothing is loaded without approval
    refused = run("load", "1")
    assert refused.exit_code == 1
    assert "Approval required" in refused.output
    assert loader.list_loaded() == []

    # After approval the skill is stored and handed to the agent
    loaded = run("load", "1", "--yes", "--content")
    assert loaded.exit_code == 0, loaded.output
    path = loader.current_session() / "frontend-design" / "SKILL.md"
    assert f"Loaded: {path}" in loaded.output
    assert "BEGIN THIRD-PARTY SKILL (untrusted reference)" in loaded.output
    assert path.read_text(encoding="utf-8") == fixture_text("frontend_design.md")

    listed = run("list")
    assert "frontend-design" in listed.output and str(path) in listed.output

    # The prompt-injection candidate is blocked even with --yes
    blocked = run("load", "2", "--yes")
    assert blocked.exit_code == 1
    assert "BLOCKED" in blocked.output and "Loading blocked" in blocked.output
    assert [s.name for s in loader.list_loaded()] == ["frontend-design"]

    cleaned = run("clean")
    assert cleaned.exit_code == 0
    assert not path.exists()

    events = [
        json.loads(line)["event"]
        for line in (loader.home() / "logs" / "skillfetch.jsonl").read_text().splitlines()
    ]
    assert events == ["discover", "load", "load_blocked", "clean"]


def test_interactive_discover_selects_and_loads(use_github, fake_llm, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = run("discover", "Build a React dashboard", input="1\ny\n")

    assert result.exit_code == 0, result.output
    assert "Select a skill to inspect [1/2/none]" in result.output
    assert "Load this skill?" in result.output
    assert [s.name for s in loader.list_loaded()] == ["frontend-design"]


def test_interactive_load_can_be_declined(use_github, fake_llm, monkeypatch):
    run("discover", "Build a React dashboard")
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = run("load", "1", input="n\n")

    assert "SKILL.md" in result.output and "Not loaded." in result.output
    assert loader.list_loaded() == []


def test_no_skill_needed_skips_github(use_github, fake_llm):
    fake_llm.analysis = {"task": "rename", "requires_skill": False, "search_queries": []}
    result = run("discover", "Rename a variable")

    assert result.exit_code == 0
    assert "No external skill needed" in result.output
    assert use_github.requests == []


def test_no_suitable_skill_ends_normally(use_github, fake_llm):
    fake_llm.scores = {}
    result = run("discover", "Write a COBOL compiler")

    assert result.exit_code == 0
    assert "No suitable skill found among 2 candidate(s)." in result.output
    assert run("load", "1", "--yes").exit_code == 1


def test_previous_candidates_are_not_reused_after_empty_discovery(use_github, fake_llm):
    run("discover", "Build a React dashboard")
    fake_llm.analysis = {"task": "rename", "requires_skill": False, "search_queries": []}
    run("discover", "Rename a variable")

    result = run("load", "1", "--yes")
    assert result.exit_code == 1
    assert "Unknown candidate id 1" in result.output


def test_llm_failure_exits_cleanly(use_github, fake_llm):
    fake_llm.error = "LLM API call failed: connection refused"
    result = run("discover", "Build a React dashboard")

    assert result.exit_code == 1
    assert "Error: LLM API call failed" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_github_rate_limit_exits_cleanly(use_github, fake_llm):
    use_github.rate_limit_after = 0
    result = run("discover", "Build a React dashboard")

    assert result.exit_code == 1
    assert "GitHub API rate limit exceeded" in result.output


def test_invalid_repo_option_is_rejected_before_any_call(use_github, fake_llm):
    result = run("discover", "Build a React dashboard", "--repo", "../etc")

    assert result.exit_code == 2
    assert fake_llm.calls == [] and use_github.requests == []


def test_repo_option_limits_search(use_github, fake_llm):
    result = run(
        "discover",
        "Build a React dashboard",
        "--repo",
        "example/agent-skills/skills/frontend-design",
    )
    assert result.exit_code == 0, result.output
    assert "1. frontend-design" in result.output
    assert "sneaky-helper" not in result.output

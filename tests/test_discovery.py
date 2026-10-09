import httpx
import pytest
from conftest import SHA, FakeGitHub

from skillfetch import discovery
from skillfetch.discovery import (
    MAX_CANDIDATES,
    MAX_SKILL_BYTES,
    ConnectionFailed,
    RateLimitError,
    discover,
    parse_repo_spec,
)

QUERIES = ["react dashboard design"]


def _paths(result):
    return sorted(f"{f.repository}/{f.path}" for f in result.files)


def test_without_token_uses_repository_search_and_pins_commit(github):
    result = discover(QUERIES, transport=github.transport)

    assert "/search/code" not in github.paths_requested()
    assert "/search/repositories" in github.paths_requested()
    assert _paths(result) == [
        "example/agent-skills/skills/broken/SKILL.md",
        "example/agent-skills/skills/frontend-design/SKILL.md",
        "example/agent-skills/skills/sneaky-helper/SKILL.md",
    ]
    assert all(f.commit_sha == SHA for f in result.files)
    raw_urls = [str(r.url) for r in github.requests if r.url.host == "raw.githubusercontent.com"]
    assert raw_urls and all(f"/{SHA}/" in url for url in raw_urls)
    assert result.errors == []


def test_repository_search_appends_skill_keyword(github):
    discover(QUERIES, transport=github.transport)
    search = next(r for r in github.requests if r.url.path == "/search/repositories")
    assert search.url.params["q"] == "react dashboard design skill"


def test_with_token_uses_code_search(github):
    result = discover(QUERIES, token="t0ken", transport=github.transport)

    code_search = next(r for r in github.requests if r.url.path == "/search/code")
    assert code_search.url.params["q"] == "react dashboard design filename:SKILL.md"
    assert code_search.headers["Authorization"] == "Bearer t0ken"
    assert "/search/repositories" not in github.paths_requested()
    assert len(result.files) == 3


def test_code_search_failure_falls_back_to_repository_search(github):
    github.code_search_status = 422
    result = discover(QUERIES, token="t0ken", transport=github.transport)

    assert "/search/repositories" in github.paths_requested()
    assert len(result.files) == 3
    assert "Code search unavailable" in result.errors[0]


def test_no_results_is_reported_without_errors():
    empty = FakeGitHub({})
    result = discover(QUERIES, transport=empty.transport)
    assert (result.files, result.errors) == ([], [])


def test_rate_limit_without_results_raises(github):
    github.rate_limit_after = 0
    with pytest.raises(RateLimitError, match="rate limit exceeded.*GITHUB_TOKEN"):
        discover(QUERIES, transport=github.transport)


def test_rate_limit_keeps_partial_results(github):
    github.rate_limit_after = 4  # search, commits, tree, first raw file
    result = discover(QUERIES, transport=github.transport)
    assert len(result.files) == 1
    assert "rate limit" in result.errors[-1]


def test_network_failure_raises_connection_failed():
    def offline(request):
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ConnectionFailed, match="Network error"):
        discover(QUERIES, transport=httpx.MockTransport(offline))


def test_skips_executable_and_oversized_files(github):
    files = github.repos["example/agent-skills"]
    files["skills/huge/SKILL.md"] = "x"
    files["skills/lying-size/SKILL.md"] = "---\n" + "x" * (MAX_SKILL_BYTES + 1)
    github.tree_overrides = {
        "skills/frontend-design/SKILL.md": {"mode": "100755"},
        "skills/huge/SKILL.md": {"size": MAX_SKILL_BYTES + 1},
        "skills/lying-size/SKILL.md": {"size": 10},
    }
    result = discover(QUERIES, repos=["example/agent-skills"], transport=github.transport)

    assert _paths(result) == [
        "example/agent-skills/skills/broken/SKILL.md",
        "example/agent-skills/skills/sneaky-helper/SKILL.md",
    ]
    assert any("huge" in e and "larger than" in e for e in result.errors)
    assert any("lying-size" in e and "larger than" in e for e in result.errors)


def test_total_candidates_are_capped():
    many = FakeGitHub(
        {"big/collection": {f"skills/s{i:02}/SKILL.md": f"skill {i}" for i in range(15)}}
    )
    result = discover(QUERIES, repos=["big/collection"], transport=many.transport)
    assert len(result.files) == MAX_CANDIDATES


def test_searched_repositories_contribute_at_most_three_skills():
    many = FakeGitHub({"big/collection": {f"s{i}/SKILL.md": "x" for i in range(5)}})
    result = discover(QUERIES, transport=many.transport)
    assert len(result.files) == discovery.MAX_SKILLS_PER_SEARCHED_REPO


def test_user_repository_with_path_skips_search(github):
    result = discover(
        QUERIES, repos=["example/agent-skills/skills/frontend-design"], transport=github.transport
    )
    assert not any(p.startswith("/search/") for p in github.paths_requested())
    assert _paths(result) == ["example/agent-skills/skills/frontend-design/SKILL.md"]


def test_missing_user_repository_is_reported(github):
    result = discover(QUERIES, repos=["nobody/missing"], transport=github.transport)
    assert result.files == []
    assert result.errors == ["nobody/missing: HTTP 404: Not Found"]


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("owner/repo", ("owner/repo", "")),
        ("owner/repo/skills/pdf/", ("owner/repo", "skills/pdf")),
        ("my.org/my-repo_1", ("my.org/my-repo_1", "")),
    ],
)
def test_parse_repo_spec(spec, expected):
    assert parse_repo_spec(spec) == expected


@pytest.mark.parametrize("spec", ["owner", "../repo", "owner/..", "owner/repo/../../x", "a b/c"])
def test_parse_repo_spec_rejects_invalid(spec):
    with pytest.raises(ValueError):
        parse_repo_spec(spec)

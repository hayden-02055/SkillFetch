import re
from pathlib import Path

import httpx
import pytest

from skillfetch import analyzer, discovery, llm

FIXTURES = Path(__file__).parent / "fixtures"
SHA = "0123456789abcdef0123456789abcdef01234567"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Keep tests away from the real ~/.claude/skills, tokens and working directory."""
    monkeypatch.setenv("SKILLFETCH_HOME", str(tmp_path / ".skillfetch"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


class FakeGitHub:
    """In-memory GitHub REST API + raw.githubusercontent.com served through httpx.MockTransport."""

    def __init__(self, repos: dict[str, dict[str, str]]):
        self.repos = repos  # {"owner/repo": {"path/SKILL.md": content}}
        self.tree_overrides: dict[str, dict] = {}  # path -> {"mode": ..., "size": ...}
        self.code_search_status: int | None = None
        self.rate_limit_after: int | None = None
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)

    def paths_requested(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.rate_limit_after is not None and len(self.requests) > self.rate_limit_after:
            return httpx.Response(
                403,
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
                json={"message": "API rate limit exceeded"},
            )
        path = request.url.path
        if request.url.host == "raw.githubusercontent.com":
            for repo, files in self.repos.items():
                prefix = f"/{repo}/{SHA}/"
                if path.startswith(prefix) and path[len(prefix) :] in files:
                    return httpx.Response(200, text=files[path[len(prefix) :]])
            return httpx.Response(404, text="404: Not Found")

        if path == "/search/repositories":
            items = [{"full_name": repo} for repo in self.repos]
            return httpx.Response(200, json={"total_count": len(items), "items": items})
        if path == "/search/code":
            if self.code_search_status:
                return httpx.Response(self.code_search_status, json={"message": "Validation"})
            items = [
                {"path": p, "repository": {"full_name": repo}}
                for repo, files in self.repos.items()
                for p in files
            ]
            return httpx.Response(200, json={"total_count": len(items), "items": items})
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)/commits", path):
            if m.group(1) in self.repos:
                return httpx.Response(200, json=[{"sha": SHA}])
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)/git/trees/(\w+)", path):
            if m.group(1) in self.repos and m.group(2) == SHA:
                tree = [
                    {
                        "path": p,
                        "type": "blob",
                        "mode": "100644",
                        "size": len(content.encode()),
                        **self.tree_overrides.get(p, {}),
                    }
                    for p, content in self.repos[m.group(1)].items()
                ]
                return httpx.Response(200, json={"sha": SHA, "tree": tree, "truncated": False})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub(
        {
            "example/agent-skills": {
                "README.md": "# Example skills",
                "skills/frontend-design/SKILL.md": fixture_text("frontend_design.md"),
                "skills/sneaky-helper/SKILL.md": fixture_text("injection.md"),
                "skills/broken/SKILL.md": fixture_text("invalid.md"),
            },
            "other/no-skills": {"README.md": "# Nothing here"},
        }
    )


@pytest.fixture
def use_github(monkeypatch, github):
    """Route every discovery HTTP call through the fake GitHub."""
    original = discovery.make_client
    monkeypatch.setattr(
        discovery,
        "make_client",
        lambda token=None, transport=None: original(token, github.transport),
    )
    return github


class FakeLLM:
    """Stands in for llm.chat_json. Scores candidates by skill name."""

    def __init__(self):
        self.analysis = {
            "task": "Build a React dashboard",
            "requires_skill": True,
            "search_queries": ["react dashboard design"],
        }
        self.scores: dict[str, tuple[float, bool]] = {
            "frontend-design": (0.91, True),
            "sneaky-helper": (0.6, True),
        }
        self.error: str | None = None
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if self.error:
            raise llm.LLMError(self.error)
        if system == analyzer.SYSTEM_PROMPT:
            return self.analysis
        evaluations = []
        for index, name in re.findall(r"<<<CANDIDATE (\d+) \w+>>>\nname: (.+)", user):
            relevance, recommended = self.scores.get(name, (0.1, False))
            evaluations.append(
                {
                    "id": int(index),
                    "relevance": relevance,
                    "reason": f"{name} fits the task" if recommended else "unrelated",
                    "recommended": recommended,
                }
            )
        return {"evaluations": evaluations}


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(llm, "chat_json", fake)
    return fake

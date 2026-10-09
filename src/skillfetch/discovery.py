"""Find SKILL.md files on GitHub and download them pinned to a commit SHA."""

import re
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
MAX_RESULTS_PER_QUERY = 10
MAX_CANDIDATES = 10
MAX_SKILLS_PER_SEARCHED_REPO = 3
MAX_SKILL_BYTES = 100_000

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_STOPWORDS = {"skill", "skills", "agent", "agents", "the", "and", "for", "with"}


class DiscoveryError(Exception):
    pass


class RateLimitError(DiscoveryError):
    pass


class ConnectionFailed(DiscoveryError):
    pass


class GitHubAPIError(DiscoveryError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


@dataclass
class RawSkill:
    repository: str
    commit_sha: str
    path: str
    content: str


@dataclass
class DiscoveryResult:
    files: list[RawSkill] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def full(self) -> bool:
        return len(self.files) >= MAX_CANDIDATES


def make_client(token: str | None = None, transport: httpx.BaseTransport | None = None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "skillfetch"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(headers=headers, timeout=15.0, follow_redirects=True, transport=transport)


def parse_repo_spec(spec: str) -> tuple[str, str]:
    """'owner/repo[/sub/path]' -> ('owner/repo', 'sub/path')."""
    parts = spec.strip().strip("/").split("/")
    if (
        len(parts) < 2
        or any(part in ("", ".", "..") for part in parts)
        or not all(_NAME.match(part) for part in parts[:2])
    ):
        raise ValueError(f"invalid repository spec: {spec!r} (expected owner/repo[/path])")
    return "/".join(parts[:2]), "/".join(parts[2:])


def discover(
    queries: list[str],
    repos: list[str] | None = None,
    token: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> DiscoveryResult:
    """Collect up to MAX_CANDIDATES SKILL.md files.

    Raises RateLimitError / ConnectionFailed only when nothing could be collected;
    otherwise they are recorded in `errors` next to the partial result.
    """
    targets = [parse_repo_spec(r) for r in repos or []]
    result = DiscoveryResult()
    with make_client(token, transport) as client:
        try:
            if targets:
                _collect_from_repos(client, targets, queries, result, per_repo=MAX_CANDIDATES)
            elif not (token and _collect_by_code_search(client, queries, result)):
                _collect_by_repo_search(client, queries, result)
        except (RateLimitError, ConnectionFailed) as exc:
            if not result.files:
                raise
            result.errors.append(str(exc))
    return result


def _collect_by_code_search(client, queries, result) -> bool:
    """Search SKILL.md file contents. Returns False if code search is unavailable."""
    commits: dict[str, str] = {}
    for query in queries:
        try:
            data = _get_json(
                client,
                f"{GITHUB_API}/search/code",
                {"q": f"{query} filename:SKILL.md", "per_page": MAX_RESULTS_PER_QUERY},
            )
        except GitHubAPIError as exc:
            if exc.status in (401, 403, 422) and not result.files:
                result.errors.append(f"Code search unavailable ({exc}); using repository search.")
                return False
            result.errors.append(f"code search {query!r}: {exc}")
            continue
        for item in data.get("items", []):
            repo, path = item["repository"]["full_name"], item["path"]
            if path.rsplit("/", 1)[-1] != "SKILL.md":
                continue
            try:
                if repo not in commits:
                    commits[repo] = _head_commit(client, repo)
            except GitHubAPIError as exc:
                result.errors.append(f"{repo}: {exc}")
                continue
            _add(client, result, repo, commits[repo], path)
            if result.full:
                return True
    return True


def _collect_by_repo_search(client, queries, result) -> None:
    repos: list[str] = []
    for query in queries:
        q = query if "skill" in query.lower() else f"{query} skill"
        try:
            data = _get_json(
                client,
                f"{GITHUB_API}/search/repositories",
                {"q": q, "per_page": MAX_RESULTS_PER_QUERY},
            )
        except GitHubAPIError as exc:
            result.errors.append(f"repository search {q!r}: {exc}")
            continue
        for item in data.get("items", []):
            if item["full_name"] not in repos:
                repos.append(item["full_name"])
    targets = [(repo, "") for repo in repos]
    _collect_from_repos(client, targets, queries, result, per_repo=MAX_SKILLS_PER_SEARCHED_REPO)


def _collect_from_repos(client, targets, queries, result, per_repo: int) -> None:
    terms = {
        word
        for query in queries
        for word in re.findall(r"[a-z0-9]+", query.lower())
        if len(word) > 2 and word not in _STOPWORDS
    }
    for repo, prefix in targets:
        if result.full:
            return
        try:
            sha = _head_commit(client, repo)
            paths = _skill_paths(client, repo, sha, prefix, result)
        except GitHubAPIError as exc:
            result.errors.append(f"{repo}: {exc}")
            continue
        # Prefer skills whose path mentions the query terms (e.g. skills/frontend-design/).
        paths.sort(key=lambda p: (-sum(t in p.lower() for t in terms), p))
        for path in paths[:per_repo]:
            _add(client, result, repo, sha, path)


def _skill_paths(client, repo: str, sha: str, prefix: str, result) -> list[str]:
    data = _get_json(client, f"{GITHUB_API}/repos/{repo}/git/trees/{sha}", {"recursive": "1"})
    if data.get("truncated"):
        result.errors.append(f"{repo}: file tree truncated by GitHub; some skills may be missed.")
    paths = []
    for entry in data.get("tree", []):
        path = entry.get("path", "")
        if entry.get("type") != "blob" or path.rsplit("/", 1)[-1] != "SKILL.md":
            continue
        if prefix and not path.startswith(prefix + "/"):
            continue
        if entry.get("mode") == "100755":  # never download executables
            continue
        if entry.get("size", 0) > MAX_SKILL_BYTES:
            result.errors.append(f"{repo}/{path}: larger than {MAX_SKILL_BYTES} bytes, skipped.")
            continue
        paths.append(path)
    return paths


def _head_commit(client, repo: str) -> str:
    data = _get_json(client, f"{GITHUB_API}/repos/{repo}/commits", {"per_page": 1})
    if not data:
        raise GitHubAPIError(404, "repository has no commits")
    return data[0]["sha"]


def _add(client, result: DiscoveryResult, repo: str, sha: str, path: str) -> None:
    if result.full or any(f.repository == repo and f.path == path for f in result.files):
        return
    try:
        content = _fetch_text(client, f"{RAW_BASE}/{repo}/{sha}/{quote(path)}")
    except GitHubAPIError as exc:
        result.errors.append(f"{repo}/{path}: {exc}")
        return
    result.files.append(RawSkill(repository=repo, commit_sha=sha, path=path, content=content))


def _get_json(client, url: str, params: dict | None = None):
    try:
        response = client.get(url, params=params)
    except httpx.RequestError as exc:
        raise ConnectionFailed(f"Network error while contacting GitHub: {exc}") from exc
    _raise_for_status(response)
    return response.json()


def _fetch_text(client, url: str) -> str:
    try:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                response.read()
                _raise_for_status(response)
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_SKILL_BYTES:
                    raise GitHubAPIError(413, f"larger than {MAX_SKILL_BYTES} bytes, skipped")
    except httpx.RequestError as exc:
        raise ConnectionFailed(f"Network error while contacting GitHub: {exc}") from exc
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHubAPIError(415, "not valid UTF-8 text") from exc


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        message = response.json().get("message", "")
    except (ValueError, AttributeError):
        message = response.text[:200]
    remaining = response.headers.get("x-ratelimit-remaining")
    if response.status_code in (403, 429) and (remaining == "0" or "rate limit" in message.lower()):
        reset = response.headers.get("x-ratelimit-reset")
        hint = f" (resets at unix time {reset})" if reset else ""
        raise RateLimitError(
            f"GitHub API rate limit exceeded{hint}. Set GITHUB_TOKEN to raise the limit."
        )
    raise GitHubAPIError(response.status_code, message or response.reason_phrase)

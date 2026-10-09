# SkillFetch

**Discover skills when needed, not before.**

SkillFetch is a small CLI that looks at a task description, searches GitHub for
`SKILL.md` Agent Skills that could help, ranks them with an LLM, statically
inspects them, and — only after the user approves — saves one into a temporary
session directory so a coding agent can read it.

Status: experimental MVP (see `SkillFetch.md` for the design).

## Install

```bash
uv venv && uv pip install -e '.[dev]'
```

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | yes | Task analysis and ranking (OpenAI SDK) |
| `SKILLFETCH_MODEL` | no | Model name, default `gpt-5.4-mini` |
| `OPENAI_BASE_URL` | no | OpenAI-compatible endpoint (read by the OpenAI SDK) |
| `GITHUB_TOKEN` | recommended | Enables code search and raises the GitHub rate limit |
| `SKILLFETCH_HOME` | no | Storage directory, default `./.skillfetch` |

Without `GITHUB_TOKEN`, GitHub code search is unavailable, so SkillFetch searches
repositories and checks their file trees for `SKILL.md`. The unauthenticated limit
(60 requests/hour) allows only a few discoveries per hour.

## Usage

```bash
skillfetch discover "Build a React dashboard"     # analyze, search, rank (max 3)
skillfetch discover "Fill a PDF form" --repo anthropics/skills/skills   # search one repo/path
skillfetch inspect 1                              # full text, source, commit SHA, security check
skillfetch load 1                                 # asks for approval, prints the SKILL.md path
skillfetch load 1 --yes --content                 # non-interactive approval, also prints the text
skillfetch list                                   # skills loaded in the current session
skillfetch clean                                  # delete the current session's files
```

Candidate ids refer to the most recent `discover` run.

Storage layout (add `.skillfetch/` to your `.gitignore`):

```
.skillfetch/
  cache/last_discovery.json       # last discovery result
  sessions/<session-id>/<skill>/  # SKILL.md + source.json
  logs/skillfetch.jsonl           # discover/load/clean events
  current_session
```

## Claude Code integration

Copy `integrations/claude-code/SKILL.md` to `~/.claude/skills/skillfetch/SKILL.md`
(or `.claude/skills/skillfetch/` in a project). It tells Claude Code to run
`discover`, show the candidates, run `inspect`, ask for approval, and only then run
`load <id> --yes`.

## Security model

External skills are treated as untrusted input.

- **High risk → loading is blocked:** prompt injection (e.g. "ignore previous
  instructions", "do not tell the user"), `curl … | sh`, `rm -rf /` or `~`, reading
  SSH/AWS credentials, sending secrets over the network.
- **Medium risk → warning only:** shell code blocks, package installs, environment
  variable access, network calls, `sudo`, broad file permissions.
- Only `SKILL.md` is downloaded (max 100 KB, pinned to a commit SHA, never executable
  files). Nothing from a skill is executed or installed.
- `load` without `--yes` asks for confirmation. In a non-interactive shell it refuses
  unless `--yes` is given.
- Skills are written only inside the session directory and never overwrite an
  existing file.

Static checks cannot guarantee safety. Read the skill before approving it.

## Limitations

- Searched repositories contribute at most 3 `SKILL.md` files each, and at most 10
  candidates are evaluated in total. Within a repository, paths that mention the
  search terms are preferred, so a relevant skill in a large collection can be missed.
- Relevance scores are LLM heuristics; they do not prove a skill improves results.
- One LLM provider (OpenAI SDK).

## Development

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
```

Tests use fixed fixtures (fake GitHub API and fake LLM) and make no network calls.

"""Local storage under .skillfetch/: discovery cache, logs and per-session loaded skills.

.skillfetch/
  cache/last_discovery.json
  sessions/<session-id>/<skill-name>/{SKILL.md,source.json}
  logs/skillfetch.jsonl
  current_session
"""

import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from skillfetch.discovery import MAX_SKILL_BYTES
from skillfetch.models import DiscoveryCache, LoadedSkill, RankedCandidate, SecurityReport

_SESSION_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


class LoadError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("SKILLFETCH_HOME", ".skillfetch")).resolve()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- discovery cache -------------------------------------------------------


def save_discovery(cache: DiscoveryCache) -> None:
    path = home() / "cache" / "last_discovery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cache.model_dump_json(indent=2), encoding="utf-8")


def get_candidate(candidate_id: int) -> RankedCandidate:
    path = home() / "cache" / "last_discovery.json"
    if not path.exists():
        raise LoadError("No discovery results. Run `skillfetch discover` first.")
    try:
        cache = DiscoveryCache.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise LoadError("Discovery cache is corrupt. Run `skillfetch discover` again.") from exc
    if not 1 <= candidate_id <= len(cache.recommendations):
        raise LoadError(
            f"Unknown candidate id {candidate_id}. "
            f"The last discovery has {len(cache.recommendations)} candidate(s)."
        )
    return cache.recommendations[candidate_id - 1]


# --- logs ------------------------------------------------------------------


def log_event(event: str, **fields) -> None:
    path = home() / "logs" / "skillfetch.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": _now(), "event": event, **fields}, ensure_ascii=False) + "\n")


# --- sessions --------------------------------------------------------------


def current_session(create: bool = False) -> Path | None:
    pointer = home() / "current_session"
    if pointer.exists():
        session_id = pointer.read_text(encoding="utf-8").strip()
        if _SESSION_ID.match(session_id):
            return home() / "sessions" / session_id
    if not create:
        return None
    session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(session_id, encoding="utf-8")
    return home() / "sessions" / session_id


def skill_dirname(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64].strip("-")
    if not slug:
        raise LoadError(f"Skill name {name!r} has no usable characters.")
    return slug


def load_skill(ranked: RankedCandidate, report: SecurityReport) -> Path:
    """Write an approved skill into the current session. Never overwrites existing files."""
    candidate = ranked.candidate
    if report.blocked:
        raise LoadError("Loading blocked: the security inspection found high-risk content.")
    data = candidate.content.encode("utf-8")
    if len(data) > MAX_SKILL_BYTES:
        raise LoadError(f"Skill is larger than {MAX_SKILL_BYTES} bytes.")

    session = current_session(create=True).resolve()
    target = (session / skill_dirname(candidate.name)).resolve()
    if target.parent != session:
        raise LoadError("Refusing to write outside the session directory.")

    skill_file = target / "SKILL.md"
    if target.exists():
        existing = _read_source(target)
        if existing and (existing.repository, existing.commit_sha, existing.skill_path) == (
            candidate.repository,
            candidate.commit_sha,
            candidate.skill_path,
        ):
            return skill_file
        raise LoadError(
            f"A different skill named {target.name!r} is already loaded in this session. "
            "Run `skillfetch clean` first."
        )

    target.mkdir(parents=True)
    with skill_file.open("xb") as f:
        f.write(data)
    source = LoadedSkill(
        name=candidate.name,
        repository=candidate.repository,
        commit_sha=candidate.commit_sha,
        skill_path=candidate.skill_path,
        source_url=candidate.source_url,
        path=str(skill_file),
        loaded_at=_now(),
    )
    with (target / "source.json").open("x", encoding="utf-8") as f:
        f.write(source.model_dump_json(indent=2))
    return skill_file


def list_loaded() -> list[LoadedSkill]:
    session = current_session()
    if session is None or not session.exists():
        return []
    skills = []
    for skill_dir in sorted(p for p in session.iterdir() if p.is_dir()):
        source = _read_source(skill_dir)
        if source:
            skills.append(source)
    return skills


def clean_session() -> Path | None:
    """Delete the current session's files. Returns the removed directory, if any."""
    session = current_session()
    pointer = home() / "current_session"
    if pointer.exists():
        pointer.unlink()
    if session is None or not session.exists():
        return None
    shutil.rmtree(session)
    return session


def _read_source(skill_dir: Path) -> LoadedSkill | None:
    try:
        return LoadedSkill.model_validate_json((skill_dir / "source.json").read_text("utf-8"))
    except (OSError, ValidationError):
        return None

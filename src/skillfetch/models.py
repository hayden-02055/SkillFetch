from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TaskAnalysis(BaseModel):
    task: str
    requires_skill: bool
    search_queries: list[str] = Field(default_factory=list)


class SkillCandidate(BaseModel):
    name: str
    description: str
    repository: str
    commit_sha: str
    skill_path: str
    source_url: str
    content: str


class SkillEvaluation(BaseModel):
    relevance: float
    reason: str
    recommended: bool

    @field_validator("relevance")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return max(0.0, min(1.0, value))


class RankedCandidate(BaseModel):
    candidate: SkillCandidate
    evaluation: SkillEvaluation


class SecurityFinding(BaseModel):
    category: str
    severity: Literal["high", "medium"]
    line: int
    excerpt: str


class SecurityReport(BaseModel):
    findings: list[SecurityFinding]

    @property
    def blocked(self) -> bool:
        return any(f.severity == "high" for f in self.findings)


class DiscoveryCache(BaseModel):
    """Result of the last `discover` run; candidate ids are 1-based indexes into it."""

    task: str
    created_at: str
    recommendations: list[RankedCandidate]


class LoadedSkill(BaseModel):
    """Stored as source.json next to each loaded SKILL.md."""

    name: str
    repository: str
    commit_sha: str
    skill_path: str
    source_url: str
    path: str
    loaded_at: str

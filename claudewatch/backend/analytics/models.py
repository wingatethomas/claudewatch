"""Analytics data models — typed return values for all query methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STALE = "stale"


@dataclass(frozen=True)
class ToolUsage:
    name: str
    count: int


@dataclass(frozen=True)
class FileUsage:
    path: str
    count: int
    last_accessed: str


@dataclass(frozen=True)
class TokenSummary:
    model: str
    input: int
    output: int
    cache: int
    total: int


@dataclass(frozen=True)
class TimeBucket:
    bucket: str  # "2026-03-28" or "2026-03-28 14:00"
    value: int


@dataclass(frozen=True)
class SessionOverview:
    session_id: str
    proj_key: str
    first_ts: str
    last_ts: str
    user_messages: int
    asst_messages: int
    tool_count: int
    total_tokens: int
    primary_model: str
    primary_branch: str
    agent_count: int


@dataclass(frozen=True)
class PRLink:
    number: int
    url: str
    repository: str
    timestamp: str


@dataclass(frozen=True)
class GlobalSummary:
    total_sessions: int
    total_messages: int
    total_tools: int
    total_tokens: int
    total_agents: int


@dataclass(frozen=True)
class ProjectSummary:
    proj_key: str
    session_count: int
    agent_count: int
    tool_count: int


@dataclass(frozen=True)
class RelatedSession:
    session_id: str
    proj_key: str
    shared_files: int
    shared_file_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileHotspot:
    path: str
    session_count: int
    total_accesses: int


@dataclass(frozen=True)
class ToolSequence:
    first: str
    second: str
    count: int


@dataclass(frozen=True)
class BranchActivity:
    branch: str
    session_count: int
    event_count: int
    last_active: str


@dataclass(frozen=True)
class AgentInfo:
    agent_id: str
    session_id: str
    parent_agent_id: str
    agent_type: str
    description: str
    status: AgentStatus | str
    started_at: str
    ended_at: str
    entry_count: int
    proj_key: str

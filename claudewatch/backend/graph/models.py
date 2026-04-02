"""Graph query result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionStep:
    kind: str
    file_path: str
    timestamp: str


@dataclass(frozen=True)
class ImpactResult:
    changed: str
    impacted: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HotspotResult:
    qualified_name: str
    file_path: str
    edits: int


@dataclass(frozen=True)
class RelatedSessionResult:
    session_id: str
    branch: str
    shared_symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BehaviorResult:
    kind: str
    frequency: int


@dataclass(frozen=True)
class ProjectGraphResult:
    files: int
    symbols: int
    sessions: int
    actions: int


@dataclass(frozen=True)
class PRImpactResult:
    changed: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowPattern:
    first: str
    then: str
    frequency: int


@dataclass(frozen=True)
class FileHistoryResult:
    session_id: str
    action_kind: str
    timestamp: str


@dataclass(frozen=True)
class SymbolNode:
    id: str
    name: str
    qualified_name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int

"""Data Transfer Objects for cross-layer communication.

All DTOs are frozen dataclasses suffixed with DTO. They carry data
across service boundaries without exposing internal repo/model details.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BaseDTO:
    """Base class for all DTOs. Immutable by default."""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PinDTO(BaseDTO):
    """Pinned session returned by BookmarkService."""

    session_id: str
    project: str
    cwd: str
    note: str
    timestamp: str


@dataclass(frozen=True)
class HistoryEntryDTO(BaseDTO):
    """Ended session returned by HistoryService."""

    session_id: str
    project: str
    cwd: str
    model: str
    host_app: str
    ended_at: str


@dataclass(frozen=True)
class UpdateInfoDTO(BaseDTO):
    """Available update returned by UpdateService."""

    tag: str
    download_url: str


@dataclass(frozen=True)
class ActivityEventDTO(BaseDTO):
    """Single event in a session timeline."""

    kind: str
    summary: str
    detail: str
    timestamp: str

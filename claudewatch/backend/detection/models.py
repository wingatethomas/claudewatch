"""Typed models for detection-internal data."""

from __future__ import annotations

from dataclasses import dataclass

from claudewatch.backend.core.models import HostApp


@dataclass(frozen=True)
class PendingToolResult:
    """Result of checking JSONL for a pending tool_use."""

    has_pending: bool
    one_line: str
    context: str


@dataclass(frozen=True)
class ToolUseInfo:
    """Formatted tool_use display strings."""

    one_line: str
    context: str


@dataclass(frozen=True)
class PromptInfo:
    """Extracted permission prompt context from terminal buffer."""

    one_line: str
    context: str


@dataclass(frozen=True)
class TerminalMatch:
    """Result of matching a session to a Terminal.app window."""

    window_title: str
    window_id: int | None
    host_app: HostApp

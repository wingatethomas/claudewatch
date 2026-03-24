"""Parse session activity timeline from Claude Code JSONL logs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from claudewatch.backend.core.base_service import BaseService
from claudewatch.backend.core.dto import ActivityEventDTO
from claudewatch.backend.core.services.session_log import SessionLogService


@dataclass
class ActivityEntry:
    """A single event in the session timeline."""

    kind: str  # "user", "assistant", "tool", "thinking"
    summary: str  # one-line description
    detail: str  # longer context (tool input, full text)
    timestamp: str  # ISO timestamp or empty


class ActivityService(BaseService):
    """Parses session JSONL logs into activity timelines."""

    def __init__(self, session_log_svc: SessionLogService) -> None:
        super().__init__()
        self._session_log_svc = session_log_svc

    def parse(self, cwd: str, max_entries: int = 100) -> list[ActivityEventDTO]:  # noqa: PLR0912
        """Parse the most recent JSONL for a CWD into an activity timeline.

        Returns newest-first list of ActivityEventDTO objects.
        """
        path = self._session_log_svc.find_most_recent(cwd)
        if not path:
            return []

        lines = self._session_log_svc.read_full(path)
        if not lines:
            return []

        entries: list[ActivityEventDTO] = []
        for line in lines:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            dtype = d.get("type", "")
            ts = d.get("timestamp", "")
            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue

            if dtype == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    entries.append(
                        ActivityEventDTO(
                            kind="user",
                            summary=_truncate(content.strip(), 80),
                            detail=content.strip(),
                            timestamp=ts,
                        )
                    )

            elif dtype in ("assistant", "progress"):
                if dtype == "progress":
                    msg = d.get("data", {}).get("message", {})
                    if not isinstance(msg, dict):
                        continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    bt = block.get("type", "")
                    if bt == "tool_use":
                        entries.append(_parse_tool_use_dto(block, ts))
                    elif bt == "text":
                        text = block.get("text", "").strip()
                        if text:
                            entries.append(
                                ActivityEventDTO(
                                    kind="assistant",
                                    summary=_truncate(text, 80),
                                    detail=text,
                                    timestamp=ts,
                                )
                            )

        # Return newest first, capped
        return list(reversed(entries[-max_entries:]))


# ---------------------------------------------------------------------------
# Backward-compatible module-level function
# ---------------------------------------------------------------------------

def parse_activity(cwd: str, max_entries: int = 100) -> list[ActivityEntry]:  # noqa: PLR0912
    """Parse the most recent JSONL for a CWD into an activity timeline.

    Returns newest-first list of ActivityEntry objects.

    .. deprecated::
        Use ``ActivityService.parse()`` instead. This wrapper exists for
        backward compatibility with callers that have not migrated yet.
    """
    svc = ActivityService(SessionLogService())
    dtos = svc.parse(cwd, max_entries=max_entries)
    return [
        ActivityEntry(kind=d.kind, summary=d.summary, detail=d.detail, timestamp=d.timestamp)
        for d in dtos
    ]


def _build_tool_use_fields(block: dict, ts: str) -> tuple[str, str, str]:
    """Extract summary and detail from a tool_use block.

    Returns (summary, detail, timestamp).
    """
    name = block.get("name", "Unknown")
    inp = block.get("input", {})
    detail_parts = [f"Tool: {name}"]

    if isinstance(inp, dict):
        if "command" in inp:
            summary = f"{name}: {_truncate(inp['command'], 60)}"
            detail_parts.append(f"Command: {inp['command']}")
        elif "file_path" in inp:
            path = inp["file_path"]
            summary = f"{name}: {os.path.basename(path)}"
            detail_parts.append(f"File: {path}")
        elif "pattern" in inp:
            summary = f"{name}: {_truncate(inp['pattern'], 40)}"
            detail_parts.append(f"Pattern: {inp['pattern']}")
        else:
            summary = name
    else:
        summary = name

    return summary, "\n".join(detail_parts), ts


def _parse_tool_use_dto(block: dict, ts: str) -> ActivityEventDTO:
    """Parse a tool_use block into an ActivityEventDTO."""
    summary, detail, timestamp = _build_tool_use_fields(block, ts)
    return ActivityEventDTO(kind="tool", summary=summary, detail=detail, timestamp=timestamp)


def _parse_tool_use(block: dict, ts: str) -> ActivityEntry:
    """Parse a tool_use block into an ActivityEntry."""
    summary, detail, timestamp = _build_tool_use_fields(block, ts)
    return ActivityEntry(kind="tool", summary=summary, detail=detail, timestamp=timestamp)


def _truncate(text: str, length: int) -> str:
    """Truncate text, replacing newlines with spaces."""
    text = text.replace("\n", " ").strip()
    if len(text) > length:
        return text[: length - 1] + "…"
    return text

"""Parse session activity timeline from Claude Code JSONL logs."""

from __future__ import annotations

import json
import os

from claudewatch.backend.core.dto import ActivityEventDTO
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService


class ActivityService(BaseService):
    """Parses session JSONL logs into activity timelines."""

    def __init__(self, session_log_service: SessionLogService) -> None:
        super().__init__()
        self._session_log_service = session_log_service

    def parse(self, cwd: str, max_entries: int = 100) -> list[ActivityEventDTO]:  # noqa: PLR0912
        """Parse the most recent JSONL for a CWD into an activity timeline.

        Returns newest-first list of ActivityEventDTO objects.
        """
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return []

        lines = self._session_log_service.read_full(path)
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

            # Recaps live on the entry itself (d.content), not in message
            if dtype == "system" and d.get("subtype") == "away_summary":
                content = d.get("content", "")
                if isinstance(content, str) and content.strip():
                    entries.append(
                        ActivityEventDTO(
                            kind="recap",
                            summary=_truncate(content.strip(), 80),
                            detail=content.strip(),
                            timestamp=ts,
                        )
                    )
                continue

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


def _build_tool_use_fields(block: dict[str, object], ts: str) -> tuple[str, str, str]:
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


def _parse_tool_use_dto(block: dict[str, object], ts: str) -> ActivityEventDTO:
    """Parse a tool_use block into an ActivityEventDTO."""
    summary, detail, timestamp = _build_tool_use_fields(block, ts)
    return ActivityEventDTO(kind="tool", summary=summary, detail=detail, timestamp=timestamp)


def _truncate(text: str, length: int) -> str:
    """Truncate text, replacing newlines with spaces."""
    text = text.replace("\n", " ").strip()
    if len(text) > length:
        return text[: length - 1] + "…"
    return text

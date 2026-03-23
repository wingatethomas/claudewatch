"""Parse session activity timeline from Claude Code JSONL logs."""

import json
import os
from dataclasses import dataclass

from claudewatch.backend.services.jsonl import find_most_recent_jsonl, read_jsonl_full


@dataclass
class ActivityEntry:
    """A single event in the session timeline."""

    kind: str  # "user", "assistant", "tool", "thinking"
    summary: str  # one-line description
    detail: str  # longer context (tool input, full text)
    timestamp: str  # ISO timestamp or empty


def parse_activity(cwd: str, max_entries: int = 100) -> list[ActivityEntry]:  # noqa: PLR0912
    """Parse the most recent JSONL for a CWD into an activity timeline.

    Returns newest-first list of ActivityEntry objects.
    """
    path = find_most_recent_jsonl(cwd)
    if not path:
        return []

    lines = read_jsonl_full(path)
    if not lines:
        return []

    entries: list[ActivityEntry] = []
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
                    ActivityEntry(
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
                    entries.append(_parse_tool_use(block, ts))
                elif bt == "text":
                    text = block.get("text", "").strip()
                    if text:
                        entries.append(
                            ActivityEntry(
                                kind="assistant",
                                summary=_truncate(text, 80),
                                detail=text,
                                timestamp=ts,
                            )
                        )

    # Return newest first, capped
    return list(reversed(entries[-max_entries:]))


def _parse_tool_use(block: dict, ts: str) -> ActivityEntry:
    """Parse a tool_use block into an ActivityEntry."""
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

    return ActivityEntry(
        kind="tool",
        summary=summary,
        detail="\n".join(detail_parts),
        timestamp=ts,
    )


def _truncate(text: str, length: int) -> str:
    """Truncate text, replacing newlines with spaces."""
    text = text.replace("\n", " ").strip()
    if len(text) > length:
        return text[: length - 1] + "…"
    return text

"""Centralized field-name constants for Claude Code's JSONL session-log shape.

Claude Code's JSONL schema evolves: PR #187 added ``away_summary`` recap entries,
PR #201 added ``ai-title`` entries. Centralizing the strings that identify each
entry shape (the discriminator values, not generic structural keys like ``type``)
reduces the blast radius of the next format change to this single file.

These are ``StrEnum`` so members compare equal to raw JSON strings —
``EntryType.USER == "user"`` is ``True`` and ``d["type"] == EntryType.USER``
works without ``.value``. If Claude Code renames any of these tokens, update
the value here and every consumer keeps parsing.
"""

from enum import StrEnum


class EntryType(StrEnum):
    """Top-level ``type`` values on a JSONL line."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    AI_TITLE = "ai-title"
    PROGRESS = "progress"
    LAST_PROMPT = "last-prompt"
    PR_LINK = "pr-link"
    QUEUE_OPERATION = "queue-operation"
    FILE_HISTORY_SNAPSHOT = "file-history-snapshot"
    MODE = "mode"
    PERMISSION_MODE = "permission-mode"
    ATTACHMENT = "attachment"


# Entries that never affect session state — skip in scans.
BOOKKEEPING_TYPES: frozenset[EntryType] = frozenset(
    {
        EntryType.LAST_PROMPT,
        EntryType.PR_LINK,
        EntryType.QUEUE_OPERATION,
        EntryType.FILE_HISTORY_SNAPSHOT,
        EntryType.MODE,
        EntryType.PERMISSION_MODE,
        EntryType.ATTACHMENT,
    }
)


class Subtype(StrEnum):
    """``system`` entry subtypes."""

    AWAY_SUMMARY = "away_summary"


class BlockType(StrEnum):
    """Content-block ``type`` values inside an assistant message."""

    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    TEXT = "text"


# Single-value field name — no enum needed.
FIELD_AI_TITLE = "aiTitle"

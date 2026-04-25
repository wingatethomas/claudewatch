"""Centralized field-name constants for Claude Code's JSONL session-log shape.

Claude Code's JSONL schema evolves: PR #187 added ``away_summary`` recap entries,
PR #201 added ``ai-title`` entries. Centralizing the strings that identify each
entry shape (the discriminator values, not generic structural keys like ``type``)
reduces the blast radius of the next format change to this single file.

If Claude Code renames any of these tokens, update the value here and every
consumer keeps parsing.
"""

# Top-level JSONL entry-type values
TYPE_USER = "user"
TYPE_ASSISTANT = "assistant"
TYPE_SYSTEM = "system"
TYPE_AI_TITLE = "ai-title"

# `system` subtype values
SUBTYPE_AWAY_SUMMARY = "away_summary"

# Field name for the `ai-title` entry's title payload
FIELD_AI_TITLE = "aiTitle"

# Content-block ``type`` values inside an assistant message
BLOCK_TOOL_USE = "tool_use"
BLOCK_TEXT = "text"

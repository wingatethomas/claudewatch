"""Parse session metadata from Claude Code JSONL session logs."""

from __future__ import annotations

import json
import os

from claudewatch.backend.core.dto import TokenUsageDTO
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService

# Model display names — keep factual. Use readable family + version so rows
# show "opus 4.6" rather than the ambiguous "o4.6" which reads as a typo.
MODEL_DISPLAY_NAMES: dict[str, str] = {
    "claude-opus-4-6": "opus 4.6",
    "claude-sonnet-4-6": "sonnet 4.6",
    "claude-haiku-4-5": "haiku 4.5",
    "claude-sonnet-4-5-20250514": "sonnet 4.5",
    "claude-opus-4-20250512": "opus 4",
}

_MAX_TOKEN_CACHE = 200

_EMPTY_TOKENS = TokenUsageDTO(input=0, output=0, cache_create=0, cache_read=0)

_M = 1_000_000
_K = 1000


def _fmt_tokens(n: int) -> str:
    """Format a token count as compact string (e.g. 42K, 1.2M)."""
    if n >= _M:
        return f"{n / _M:.1f}M"
    if n >= _K:
        return f"{n / _K:.0f}K"
    return str(n)


def format_tokens_compact(tokens: TokenUsageDTO) -> str:
    """Single-line compact summary for cards: '49K in · 591K out · 288M cache'."""
    total_in = tokens.input
    total_out = tokens.output
    cache = tokens.cache_create + tokens.cache_read
    if total_in + total_out + cache == 0:
        return ""
    total = total_in + total_out + cache
    parts = [f"{_fmt_tokens(total_in)} in", f"{_fmt_tokens(total_out)} out"]
    if cache:
        parts.append(f"{_fmt_tokens(cache)} cache")
    parts.append(f"{_fmt_tokens(total)} total")
    return " · ".join(parts)


def format_tokens_breakdown(tokens: TokenUsageDTO) -> list[str]:
    """Detailed breakdown lines for a submenu."""
    total_in = tokens.input + tokens.cache_create + tokens.cache_read
    total_out = tokens.output
    if total_in + total_out == 0:
        return []
    lines = [
        f"Input: {_fmt_tokens(tokens.input)} tokens",
        f"Output: {_fmt_tokens(total_out)} tokens",
    ]
    if tokens.cache_create:
        lines.append(f"Cache write: {_fmt_tokens(tokens.cache_create)} tokens")
    if tokens.cache_read:
        lines.append(f"Cache read: {_fmt_tokens(tokens.cache_read)} tokens")
    lines.append(f"Total: {_fmt_tokens(total_in + total_out)} tokens")
    return lines


class UsageService(BaseService):
    """Parses model identity and token usage from Claude Code session logs."""

    def __init__(self, session_log_service: SessionLogService) -> None:
        super().__init__()
        self._session_log_service = session_log_service
        # CWD -> (tokens_dto, jsonl_mtime)
        self._token_cache: dict[str, tuple[TokenUsageDTO, float]] = {}

    def get_model(self, cwd: str) -> str:
        """Get the model name for the most recent session at a CWD.

        Reads the last assistant message from the JSONL to find the model.
        Returns a display name like 'opus 4.6' or empty string if unavailable.
        """
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return ""

        tail = self._session_log_service.read_tail(path)
        if not tail:
            return ""

        last_model = ""
        for line in tail.strip().splitlines():
            try:
                d = json.loads(line)
                msg = d.get("message", {})
                if isinstance(msg, dict):
                    model = msg.get("model", "")
                    if model:
                        last_model = model
            except (json.JSONDecodeError, AttributeError):
                continue

        return MODEL_DISPLAY_NAMES.get(last_model, last_model)

    def get_tokens(self, cwd: str) -> TokenUsageDTO:
        """Get token usage breakdown for the most recent session at a CWD.

        Returns TokenUsageDTO(input, output, cache_create, cache_read) summed across all messages.
        Cached by JSONL mtime — only re-reads when the file changes.
        """
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return _EMPTY_TOKENS

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return _EMPTY_TOKENS

        cached = self._token_cache.get(cwd)
        if cached and cached[1] >= mtime:
            return cached[0]

        lines = self._session_log_service.read_full(path)
        total_in = 0
        total_out = 0
        total_cache_create = 0
        total_cache_read = 0
        for line in lines:
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            msg = d.get("message", {})
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage", {})
            if not isinstance(usage, dict):
                continue
            total_in += usage.get("input_tokens", 0)
            total_cache_create += usage.get("cache_creation_input_tokens", 0)
            total_cache_read += usage.get("cache_read_input_tokens", 0)
            total_out += usage.get("output_tokens", 0)

        result = TokenUsageDTO(
            input=total_in,
            output=total_out,
            cache_create=total_cache_create,
            cache_read=total_cache_read,
        )
        if len(self._token_cache) >= _MAX_TOKEN_CACHE:
            # Evict oldest entry by mtime
            oldest = min(self._token_cache, key=lambda k: self._token_cache[k][1])
            del self._token_cache[oldest]
        self._token_cache[cwd] = (result, mtime)
        return result

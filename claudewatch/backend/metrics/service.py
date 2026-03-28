"""Metrics service — extracts and aggregates insights from JSONL session logs.

Parses session files to compute: tool usage, message counts, models used,
files touched, agent spawns, and more. Results are cached per-session by mtime.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService

log = logging.getLogger("claudewatch")


@dataclass
class SessionMetrics:
    """Aggregated metrics for a single session."""

    user_messages: int = 0
    assistant_messages: int = 0
    tools: dict[str, int] = field(default_factory=dict)
    models: set[str] = field(default_factory=set)
    files_touched: set[str] = field(default_factory=set)
    agent_spawns: int = 0
    commands_run: list[str] = field(default_factory=list)

    @classmethod
    def from_jsonl(cls, path: str) -> SessionMetrics:
        """Parse a JSONL file and extract metrics."""
        metrics = cls()
        try:
            with open(path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    metrics._process_entry(entry)
        except OSError:
            log.warning("metrics: failed to read %s", path)
        return metrics

    def _process_entry(self, entry: dict) -> None:
        """Process a single JSONL entry."""
        entry_type = entry.get("type", "")
        message = entry.get("message", {})
        if not isinstance(message, dict):
            return

        if entry_type == "user":
            self.user_messages += 1
        elif entry_type == "assistant":
            self.assistant_messages += 1
            model = message.get("model", "")
            if model and model != "<synthetic>":
                self.models.add(model)
            self._extract_tools(message)

    def _extract_tools(self, message: dict) -> None:
        """Extract tool usage from assistant message content blocks."""
        content = message.get("content", [])
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_name = block.get("name", "")
            if not tool_name:
                continue
            self.tools[tool_name] = self.tools.get(tool_name, 0) + 1

            # Track agent spawns
            if tool_name == "Agent":
                self.agent_spawns += 1

            # Track files touched
            tool_input = block.get("input", {})
            if isinstance(tool_input, dict):
                file_path = tool_input.get("file_path", "")
                if file_path:
                    self.files_touched.add(file_path)

                # Track bash commands
                if tool_name == "Bash":
                    command = tool_input.get("command", "")
                    if command:
                        self.commands_run.append(command[:100])  # truncate long commands


@dataclass
class AggregatedMetrics:
    """Metrics aggregated across multiple sessions."""

    total_sessions: int = 0
    total_user_messages: int = 0
    total_assistant_messages: int = 0
    tools: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    total_agent_spawns: int = 0
    total_files_touched: int = 0
    top_tools: list[tuple[str, int]] = field(default_factory=list)
    top_commands: list[tuple[str, int]] = field(default_factory=list)


class MetricsService(BaseService):
    """Aggregates metrics across all session JSONL files."""

    def __init__(self, session_log_service: SessionLogService) -> None:
        super().__init__()
        self._session_log_service = session_log_service
        self._cache: dict[str, tuple[float, SessionMetrics]] = {}  # path → (mtime, metrics)

    def get_session_metrics(self, cwd: str) -> SessionMetrics | None:
        """Get metrics for the most recent session at a CWD. Cached by mtime."""
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return None

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None

        cached = self._cache.get(path)
        if cached and cached[0] >= mtime:
            return cached[1]

        metrics = SessionMetrics.from_jsonl(path)
        self._cache[path] = (mtime, metrics)
        return metrics

    def get_aggregated(self, cwds: list[str]) -> AggregatedMetrics:
        """Aggregate metrics across multiple sessions."""
        agg = AggregatedMetrics()
        command_counts: dict[str, int] = {}

        for cwd in cwds:
            metrics = self.get_session_metrics(cwd)
            if not metrics:
                continue
            agg.total_sessions += 1
            agg.total_user_messages += metrics.user_messages
            agg.total_assistant_messages += metrics.assistant_messages
            agg.total_agent_spawns += metrics.agent_spawns
            agg.total_files_touched += len(metrics.files_touched)

            for tool, count in metrics.tools.items():
                agg.tools[tool] = agg.tools.get(tool, 0) + count

            for model in metrics.models:
                agg.models[model] = agg.models.get(model, 0) + 1

            for cmd in metrics.commands_run:
                # Normalize command to first word
                first_word = cmd.split()[0] if cmd.split() else cmd
                command_counts[first_word] = command_counts.get(first_word, 0) + 1

        agg.top_tools = sorted(agg.tools.items(), key=lambda x: -x[1])[:10]
        agg.top_commands = sorted(command_counts.items(), key=lambda x: -x[1])[:10]
        return agg

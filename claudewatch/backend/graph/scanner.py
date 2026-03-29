"""SubagentScanner — discovers subagent JSONL files and metadata on disk.

Scans ~/.claude/projects/<proj_key>/<session_id>/subagents/ for child agent
transcripts. Reads meta.json for agent type and description. Extracts
parentUuid from the first JSONL entry to link to parent session.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from claudewatch.backend.graph.models import AgentStatus, ScannedAgentDTO, WorktreeProjectDTO

log = logging.getLogger("claudewatch")

_AGENT_JSONL_RE = re.compile(r"^agent-(.+)\.jsonl$")
_WORKTREE_RE = re.compile(r"^(.+)--claude-worktrees-(.+)$")


class SubagentScanner:
    """Discovers subagent files from the Claude projects directory."""

    def __init__(self, projects_dir: str) -> None:
        self._projects_dir = projects_dir

    @property
    def projects_dir(self) -> str:
        return self._projects_dir

    def count_agents(self, proj_key: str, session_id: str) -> int:
        """Fast count of subagent JSONL files without parsing content."""
        subagents_dir = os.path.join(self._projects_dir, proj_key, session_id, "subagents")
        if not os.path.isdir(subagents_dir):
            return 0
        try:
            return sum(1 for f in os.listdir(subagents_dir) if _AGENT_JSONL_RE.match(f))
        except OSError:
            return 0

    def scan_session(self, proj_key: str, session_id: str) -> list[ScannedAgentDTO]:
        """Scan a session directory for subagent JSONL files.

        Returns a list of ScannedAgentDTO with agent metadata and parent linkage.
        """
        subagents_dir = os.path.join(self._projects_dir, proj_key, session_id, "subagents")
        if not os.path.isdir(subagents_dir):
            return []

        agents: list[ScannedAgentDTO] = []
        try:
            filenames = os.listdir(subagents_dir)
        except OSError:
            log.warning("graph: failed to list subagents in %s", subagents_dir)
            return []

        for filename in filenames:
            match = _AGENT_JSONL_RE.match(filename)
            if not match:
                continue

            agent_id = match.group(1)
            jsonl_path = os.path.join(subagents_dir, filename)

            # Read mtime for activity detection
            try:
                last_active = os.path.getmtime(jsonl_path)
            except OSError:
                last_active = 0.0

            # Read meta file for type + description
            meta_path = os.path.join(subagents_dir, f"agent-{agent_id}.meta.json")
            agent_type, description = self._read_meta(meta_path)

            # Read JSONL for parentUuid, sessionId, and lifecycle timestamps
            parent_uuid, linked_session_id = self._read_first_entry(jsonl_path)
            started_at, ended_at, entry_count, completed = self._read_lifecycle(jsonl_path)

            # Derive agent status
            _active_threshold = 30
            age = time.time() - last_active if last_active > 0 else float("inf")
            if age < _active_threshold:
                status = AgentStatus.ACTIVE
            elif completed:
                status = AgentStatus.COMPLETED
            else:
                status = AgentStatus.STALE

            agents.append(
                ScannedAgentDTO(
                    agent_id=agent_id,
                    agent_type=agent_type,
                    description=description,
                    parent_uuid=parent_uuid,
                    session_id=linked_session_id or session_id,
                    jsonl_path=jsonl_path,
                    last_active=last_active,
                    started_at=started_at,
                    ended_at=ended_at,
                    entry_count=entry_count,
                    status=status,
                )
            )

        return agents

    def find_worktree_projects(self, proj_key: str) -> list[WorktreeProjectDTO]:
        """Find worktree project directories related to a base project.

        Worktree dirs follow the pattern: <proj_key>--claude-worktrees-<branch>
        """
        worktrees: list[WorktreeProjectDTO] = []
        try:
            entries = os.listdir(self._projects_dir)
        except OSError:
            return []

        for entry in entries:
            match = _WORKTREE_RE.match(entry)
            if not match:
                continue
            base_key = match.group(1)
            branch = match.group(2)
            if base_key == proj_key:
                worktrees.append(WorktreeProjectDTO(proj_key=entry, branch=branch))

        return worktrees

    def list_sessions(self, proj_key: str) -> list[str]:
        """List all session IDs (JSONL files) for a project directory."""
        proj_dir = os.path.join(self._projects_dir, proj_key)
        if not os.path.isdir(proj_dir):
            return []

        sessions: list[str] = []
        try:
            for filename in os.listdir(proj_dir):
                if filename.endswith(".jsonl"):
                    sessions.append(filename.removesuffix(".jsonl"))
        except OSError:
            pass
        return sessions

    @staticmethod
    def _read_meta(path: str) -> tuple[str, str]:
        """Read agent meta.json. Returns (agent_type, description)."""
        try:
            with open(path) as f:
                data = json.load(f)
            return (
                data.get("agentType", "unknown"),
                data.get("description", ""),
            )
        except (OSError, json.JSONDecodeError, ValueError):
            return ("unknown", "")

    @staticmethod
    def _read_lifecycle(path: str) -> tuple[str, str, int, bool]:
        """Read first/last timestamps, entry count, and completion from JSONL.

        Returns (started_at, ended_at, entry_count, completed).
        An agent is considered completed if its last assistant message
        contains text content (not a tool_use awaiting approval).
        """
        first_ts = ""
        last_ts = ""
        count = 0
        completed = False
        try:
            with open(path) as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    count += 1
                    try:
                        entry = json.loads(stripped)
                        ts = entry.get("timestamp", "")
                        if ts:
                            if not first_ts:
                                first_ts = ts
                            last_ts = ts
                        # Check if last assistant message has text (completed)
                        msg = entry.get("message", {})
                        if isinstance(msg, dict) and msg.get("role") == "assistant":
                            content = msg.get("content", [])
                            if isinstance(content, list) and content:
                                last_block = content[-1]
                                if isinstance(last_block, dict):
                                    completed = last_block.get("type") == "text"
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            pass
        return (first_ts, last_ts, count, completed)

    @staticmethod
    def _read_first_entry(path: str) -> tuple[str, str]:
        """Read first JSONL entry for parentUuid and sessionId.

        Returns (parent_uuid, session_id). Both default to empty string.
        """
        try:
            with open(path) as f:
                first_line = f.readline()
                if not first_line.strip():
                    return ("", "")
                entry = json.loads(first_line)
                return (
                    entry.get("parentUuid", ""),
                    entry.get("sessionId", ""),
                )
        except (OSError, json.JSONDecodeError, ValueError):
            return ("", "")

"""Agent scanner — discovers subagents from disk (meta.json + JSONL headers)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time

from claudewatch.backend.analytics.models import AgentInfo

log = logging.getLogger("claudewatch")

# Subagent directories live under:
# ~/.claude/projects/<proj_key>/<session_id>/
# Each subagent dir contains a JSONL file and possibly a meta.json
_STALE_THRESHOLD = 300  # 5 minutes without updates → stale


class AgentScanner:
    """Scans disk for subagent metadata and writes to the agents table."""

    def __init__(self, conn: sqlite3.Connection, projects_dir: str) -> None:
        self._conn = conn
        self.projects_dir = projects_dir

    def scan_all(self) -> int:
        """Scan every project for agents. Returns total agents found."""
        total = 0
        if not os.path.isdir(self.projects_dir):
            return 0
        try:
            proj_keys = os.listdir(self.projects_dir)
        except OSError:
            return 0
        for proj_key in proj_keys:
            proj_dir = os.path.join(self.projects_dir, proj_key)
            if not os.path.isdir(proj_dir):
                continue
            # Session dirs are subdirectories that contain JSONL files
            try:
                entries = os.listdir(proj_dir)
            except OSError:
                continue
            for entry_name in entries:
                if entry_name.endswith(".jsonl"):
                    # Top-level JSONL = session file, look for subagent dirs
                    session_id = entry_name.removesuffix(".jsonl")
                    total += self.scan_session(proj_key, session_id)
        self._conn.commit()
        return total

    def scan_session(self, proj_key: str, session_id: str) -> int:
        """Scan one session directory for subagent metadata. Returns count found."""
        session_dir = os.path.join(self.projects_dir, proj_key, session_id)
        if not os.path.isdir(session_dir):
            return 0
        count = 0
        try:
            agent_dirs = os.listdir(session_dir)
        except OSError:
            return 0
        for agent_dir_name in agent_dirs:
            agent_path = os.path.join(session_dir, agent_dir_name)
            if not os.path.isdir(agent_path):
                continue
            meta = self._read_meta(agent_path)
            if meta is None:
                meta = self._infer_from_jsonl(agent_path, agent_dir_name)
            if meta is None:
                continue
            agent_id = meta.get("agent_id", agent_dir_name)
            agent_type = meta.get("type", meta.get("agent_type", "general-purpose"))
            description = meta.get("description", "")
            parent = meta.get("parent_agent_id", "")
            started_at = meta.get("started_at", "")
            ended_at = meta.get("ended_at", "")
            entry_count = meta.get("entry_count", 0)
            status = self._derive_status(agent_path, ended_at)
            try:
                self._conn.execute(
                    "INSERT INTO agents "
                    "(agent_id, session_id, parent_agent_id, agent_type, "
                    "description, status, started_at, ended_at, entry_count, proj_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(agent_id) DO UPDATE SET "
                    "status=excluded.status, ended_at=excluded.ended_at, "
                    "entry_count=excluded.entry_count",
                    (
                        agent_id,
                        session_id,
                        parent,
                        agent_type,
                        description,
                        status,
                        started_at,
                        ended_at,
                        entry_count,
                        proj_key,
                    ),
                )
                count += 1
            except Exception:
                log.exception("scanner: error inserting agent %s", agent_id)
        return count

    def count_agents(self, proj_key: str, session_id: str) -> int:
        """Fast agent count from DB (no disk scan)."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM agents WHERE session_id = ? AND proj_key = ?",
            (session_id, proj_key),
        ).fetchone()
        return row["c"] if row else 0

    def agents_for_session(self, session_id: str) -> list[AgentInfo]:
        """Query agent info from DB for a given session."""
        rows = self._conn.execute(
            "SELECT * FROM agents WHERE session_id = ? ORDER BY started_at",
            (session_id,),
        ).fetchall()
        return [
            AgentInfo(
                agent_id=r["agent_id"],
                session_id=r["session_id"],
                parent_agent_id=r["parent_agent_id"] or "",
                agent_type=r["agent_type"],
                description=r["description"] or "",
                status=r["status"],
                started_at=r["started_at"] or "",
                ended_at=r["ended_at"] or "",
                entry_count=r["entry_count"],
                proj_key=r["proj_key"],
            )
            for r in rows
        ]

    def _read_meta(self, agent_path: str) -> dict | None:
        meta_path = os.path.join(agent_path, "meta.json")
        if not os.path.isfile(meta_path):
            return None
        try:
            with open(meta_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _infer_from_jsonl(self, agent_path: str, dir_name: str) -> dict | None:
        """Try to infer agent metadata from the JSONL file in the agent dir."""
        try:
            jsonl_files = [f for f in os.listdir(agent_path) if f.endswith(".jsonl")]
        except OSError:
            return None
        if not jsonl_files:
            return None
        jsonl_path = os.path.join(agent_path, jsonl_files[0])
        try:
            with open(jsonl_path) as f:
                first_line = f.readline()
            entry = json.loads(first_line)
            if isinstance(entry, dict):
                with open(jsonl_path) as count_f:
                    entry_count = sum(1 for _ in count_f)
                return {
                    "agent_id": dir_name,
                    "type": entry.get("agentType", "general-purpose"),
                    "description": entry.get("description", ""),
                    "started_at": entry.get("timestamp", ""),
                    "entry_count": entry_count,
                }
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _derive_status(self, agent_path: str, ended_at: str) -> str:
        """Derive agent status from disk state."""
        if ended_at:
            return "completed"
        # Check if any file was modified recently
        try:
            latest_mtime = 0.0
            for fname in os.listdir(agent_path):
                fpath = os.path.join(agent_path, fname)
                try:
                    mt = os.path.getmtime(fpath)
                    latest_mtime = max(latest_mtime, mt)
                except OSError:
                    continue
            if latest_mtime > 0 and (time.time() - latest_mtime) < _STALE_THRESHOLD:
                return "active"
        except OSError:
            pass
        return "stale"

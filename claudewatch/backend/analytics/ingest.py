"""Ingest — JSONL to normalized SQLite tables with byte-offset checkpoints."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import UTC, datetime

log = logging.getLogger("claudewatch")

# Tools that operate on files, keyed by the input field that holds the path
_FILE_TOOLS: dict[str, str] = {
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "Grep": "path",
    "Glob": "path",
    "NotebookEdit": "file_path",
}

_ACCESS_TYPE: dict[str, str] = {
    "Read": "read",
    "Edit": "edit",
    "Write": "write",
    "Grep": "grep",
    "Glob": "glob",
    "NotebookEdit": "edit",
}

# PR URL pattern: github.com/owner/repo/pull/123
_PR_PATTERN = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)")


class Ingest:
    """Reads JSONL session logs and writes normalized rows into SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def full_scan(self, projects_dir: str) -> dict[str, int]:
        """Scan all projects, ignoring checkpoints (full re-ingest)."""
        self._conn.execute("DELETE FROM checkpoints")
        self._conn.commit()
        return self._scan(projects_dir, incremental=False)

    def incremental_scan(self, projects_dir: str) -> dict[str, int]:
        """Scan all projects, skipping files whose mtime+size haven't changed."""
        return self._scan(projects_dir, incremental=True)

    def _scan(self, projects_dir: str, *, incremental: bool) -> dict[str, int]:
        stats: dict[str, int] = {}
        if not os.path.isdir(projects_dir):
            return stats
        try:
            proj_keys = os.listdir(projects_dir)
        except OSError:
            log.warning("ingest: cannot list %s", projects_dir)
            return stats
        for proj_key in proj_keys:
            proj_dir = os.path.join(projects_dir, proj_key)
            if not os.path.isdir(proj_dir):
                continue
            try:
                files = [f for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
            except OSError:
                continue
            for fname in files:
                path = os.path.join(proj_dir, fname)
                session_id = fname.removesuffix(".jsonl")
                try:
                    count = self.process_file(path, session_id, proj_key, incremental=incremental)
                    if count > 0:
                        stats[session_id] = count
                except Exception:
                    log.exception("ingest: error processing %s", path)
        return stats

    def process_file(
        self,
        path: str,
        session_id: str,
        proj_key: str,
        *,
        incremental: bool = True,
    ) -> int:
        """Process a single JSONL file. Returns number of new entries ingested."""
        try:
            stat = os.stat(path)
        except OSError:
            return 0

        mtime = stat.st_mtime
        size = stat.st_size

        byte_offset = 0
        if incremental:
            row = self._conn.execute(
                "SELECT byte_offset, file_size, file_mtime FROM checkpoints WHERE file_path = ?",
                (path,),
            ).fetchone()
            if row:
                if row["file_mtime"] == mtime and row["file_size"] == size:
                    return 0  # unchanged
                byte_offset = row["byte_offset"]

        count = 0
        new_offset = byte_offset
        try:
            with open(path, "rb") as f:
                f.seek(byte_offset)
                for line_bytes in f:
                    new_offset += len(line_bytes)
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    self._process_entry(entry, session_id, proj_key)
                    count += 1
        except OSError:
            log.warning("ingest: failed to read %s", path)
            return 0

        # Update checkpoint
        self._conn.execute(
            "INSERT INTO checkpoints (file_path, byte_offset, file_size, file_mtime, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET "
            "byte_offset=excluded.byte_offset, file_size=excluded.file_size, "
            "file_mtime=excluded.file_mtime, updated_at=excluded.updated_at",
            (path, new_offset, size, mtime, time.time()),
        )

        if count > 0:
            self._update_session(session_id, proj_key)

        self._conn.commit()
        return count

    def _process_entry(self, entry: dict, session_id: str, proj_key: str) -> None:
        entry_type = entry.get("type", "")
        if not entry_type:
            return

        ts = entry.get("timestamp", "")
        ts_epoch = _parse_epoch(ts)
        uuid = entry.get("uuid")
        parent_uuid = entry.get("parentUuid") or entry.get("parent_uuid")

        message = entry.get("message", {})
        if not isinstance(message, dict):
            message = {}

        model = message.get("model", "") or ""
        if model == "<synthetic>":
            model = ""

        # Insert event
        cursor = self._conn.execute(
            "INSERT INTO events "
            "(session_id, uuid, parent_uuid, entry_type, timestamp, ts_epoch, "
            "proj_key, model, is_sidechain) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                uuid,
                parent_uuid,
                entry_type,
                ts,
                ts_epoch,
                proj_key,
                model if model else None,
                1 if entry.get("isSidechain") else 0,
            ),
        )
        event_id = cursor.lastrowid

        # Extract tools from assistant messages
        if entry_type == "assistant":
            self._extract_tools(message, event_id, session_id, proj_key, ts, ts_epoch)
            self._extract_tokens(message, event_id, session_id, proj_key, ts, ts_epoch)

        # Check for PR links in text content
        self._extract_pr(entry, session_id, proj_key, ts, ts_epoch)

    def _extract_tools(  # noqa: PLR0913
        self,
        message: dict,
        event_id: int,
        session_id: str,
        proj_key: str,
        ts: str,
        ts_epoch: float,
    ) -> None:
        content = message.get("content", [])
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_name = block.get("name", "")
            if not tool_name:
                continue
            tool_input = block.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}

            file_path = None
            command = None
            pattern = None

            # Extract file path
            path_field = _FILE_TOOLS.get(tool_name)
            if path_field:
                file_path = tool_input.get(path_field, "")
            elif tool_name == "Bash":
                command = (tool_input.get("command") or "")[:200]
            elif tool_name == "Agent":
                pass  # tracked via agent_spawns

            # Also check generic file_path for tools not in the map
            if not file_path:
                file_path = tool_input.get("file_path", "")

            # Extract pattern for search tools
            if tool_name in ("Grep", "Glob"):
                pattern = tool_input.get("pattern", "")

            cursor = self._conn.execute(
                "INSERT INTO tools "
                "(event_id, session_id, name, tool_use_id, file_path, command, "
                "pattern, timestamp, ts_epoch, proj_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    session_id,
                    tool_name,
                    block.get("id"),
                    file_path or None,
                    command,
                    pattern,
                    ts,
                    ts_epoch,
                    proj_key,
                ),
            )
            tool_id = cursor.lastrowid

            # Insert file access records
            if file_path:
                access_type = _ACCESS_TYPE.get(tool_name, "read")
                self._conn.execute(
                    "INSERT INTO files "
                    "(tool_id, session_id, path, access_type, timestamp, ts_epoch, proj_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tool_id, session_id, file_path, access_type, ts, ts_epoch, proj_key),
                )

    def _extract_tokens(  # noqa: PLR0913
        self,
        message: dict,
        event_id: int,
        session_id: str,
        proj_key: str,
        ts: str,
        ts_epoch: float,
    ) -> None:
        usage = message.get("usage", {})
        if not isinstance(usage, dict) or not usage:
            return
        model = message.get("model", "") or ""
        if model == "<synthetic>":
            model = ""
        if not model:
            return
        input_tokens = usage.get("input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0
        cache_create = usage.get("cache_creation_input_tokens", 0) or 0
        cache_read = usage.get("cache_read_input_tokens", 0) or 0
        if input_tokens or output_tokens or cache_create or cache_read:
            self._conn.execute(
                "INSERT INTO tokens "
                "(event_id, session_id, model, input, output, cache_create, "
                "cache_read, timestamp, ts_epoch, proj_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    session_id,
                    model,
                    input_tokens,
                    output_tokens,
                    cache_create,
                    cache_read,
                    ts,
                    ts_epoch,
                    proj_key,
                ),
            )

    def _extract_pr(
        self,
        entry: dict,
        session_id: str,
        proj_key: str,
        ts: str,
        ts_epoch: float,
    ) -> None:
        """Scan entry text content for GitHub PR URLs."""
        message = entry.get("message", {})
        if not isinstance(message, dict):
            return
        content = message.get("content", [])
        if isinstance(content, str):
            self._find_prs(content, session_id, proj_key, ts, ts_epoch)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        self._find_prs(text, session_id, proj_key, ts, ts_epoch)

    def _find_prs(
        self,
        text: str,
        session_id: str,
        proj_key: str,
        ts: str,
        ts_epoch: float,
    ) -> None:
        for match in _PR_PATTERN.finditer(text):
            repo = match.group(1)
            number = int(match.group(2))
            url = match.group(0)
            self._conn.execute(
                "INSERT OR IGNORE INTO pull_requests "
                "(session_id, number, url, repository, timestamp, ts_epoch, proj_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, number, url, repo, ts, ts_epoch, proj_key),
            )

    def _update_session(self, session_id: str, proj_key: str) -> None:
        """Recompute session summary row from event/tool/token tables."""
        row = self._conn.execute(
            "SELECT "
            "  MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts, "
            "  MIN(ts_epoch) AS first_epoch, MAX(ts_epoch) AS last_epoch, "
            "  SUM(CASE WHEN entry_type='user' THEN 1 ELSE 0 END) AS user_msgs, "
            "  SUM(CASE WHEN entry_type='assistant' THEN 1 ELSE 0 END) AS asst_msgs "
            "FROM events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row or row["first_ts"] is None:
            return

        tool_count = self._conn.execute(
            "SELECT COUNT(*) AS c FROM tools WHERE session_id = ?",
            (session_id,),
        ).fetchone()["c"]

        token_row = self._conn.execute(
            "SELECT "
            "  COALESCE(SUM(input), 0) AS inp, "
            "  COALESCE(SUM(output), 0) AS outp, "
            "  COALESCE(SUM(cache_create + cache_read), 0) AS cache "
            "FROM tokens WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        # Primary model: most frequent model in events
        model_row = self._conn.execute(
            "SELECT model, COUNT(*) AS c FROM events "
            "WHERE session_id = ? AND model IS NOT NULL AND model != '' "
            "GROUP BY model ORDER BY c DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        primary_model = model_row["model"] if model_row else None

        # Primary branch: most frequent branch in events
        branch_row = self._conn.execute(
            "SELECT git_branch, COUNT(*) AS c FROM events "
            "WHERE session_id = ? AND git_branch IS NOT NULL AND git_branch != '' "
            "GROUP BY git_branch ORDER BY c DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        primary_branch = branch_row["git_branch"] if branch_row else None

        agent_count = self._conn.execute(
            "SELECT COUNT(*) AS c FROM agents WHERE session_id = ?",
            (session_id,),
        ).fetchone()["c"]

        self._conn.execute(
            "INSERT INTO sessions "
            "(session_id, proj_key, first_ts, last_ts, first_epoch, last_epoch, "
            "user_messages, asst_messages, tool_count, input_tokens, output_tokens, "
            "cache_tokens, primary_model, primary_branch, agent_count, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "first_ts=excluded.first_ts, last_ts=excluded.last_ts, "
            "first_epoch=excluded.first_epoch, last_epoch=excluded.last_epoch, "
            "user_messages=excluded.user_messages, asst_messages=excluded.asst_messages, "
            "tool_count=excluded.tool_count, input_tokens=excluded.input_tokens, "
            "output_tokens=excluded.output_tokens, cache_tokens=excluded.cache_tokens, "
            "primary_model=excluded.primary_model, primary_branch=excluded.primary_branch, "
            "agent_count=excluded.agent_count, updated_at=excluded.updated_at",
            (
                session_id,
                proj_key,
                row["first_ts"],
                row["last_ts"],
                row["first_epoch"],
                row["last_epoch"],
                row["user_msgs"],
                row["asst_msgs"],
                tool_count,
                token_row["inp"],
                token_row["outp"],
                token_row["cache"],
                primary_model,
                primary_branch,
                agent_count,
                time.time(),
            ),
        )


def _parse_epoch(ts: str) -> float:
    """Parse an ISO timestamp to epoch float. Returns 0.0 on failure."""
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0

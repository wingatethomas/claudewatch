"""Ingest — JSONL to normalized SQLite tables with byte-offset checkpoints."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from claudewatch.backend.analytics.store import (
    AgentRow,
    CheckpointRow,
    EventRow,
    FileRow,
    PullRequestRow,
    SessionRow,
    TokenRow,
    ToolRow,
)
from claudewatch.backend.core.paths import is_safe_projects_path

log = logging.getLogger("claudewatch")

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

_PR_PATTERN = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)")


class Ingest:
    """Reads JSONL session logs and writes normalized rows into SQLite."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def full_scan(self, projects_dir: str) -> dict[str, int]:
        """Scan all projects, ignoring checkpoints (full re-ingest)."""
        with self._session_factory() as s:
            s.query(CheckpointRow).delete()
            s.commit()
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
            if not os.path.isdir(proj_dir) or not is_safe_projects_path(proj_dir, projects_dir):
                continue
            try:
                jsonl_files = [f for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
            except OSError:
                continue
            for fname in jsonl_files:
                path = os.path.join(proj_dir, fname)
                if not is_safe_projects_path(path, projects_dir):
                    continue
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

        with self._session_factory() as s:
            byte_offset = 0
            if incremental:
                cp = s.get(CheckpointRow, path)
                if cp:
                    if cp.file_mtime == mtime and cp.file_size == size:
                        return 0
                    byte_offset = cp.byte_offset

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
                        self._process_entry(s, entry, session_id, proj_key)
                        count += 1
            except OSError:
                log.warning("ingest: failed to read %s", path)
                return 0

            # Upsert checkpoint
            cp = s.get(CheckpointRow, path)
            if cp:
                cp.byte_offset = new_offset
                cp.file_size = size
                cp.file_mtime = mtime
                cp.updated_at = time.time()
            else:
                s.add(
                    CheckpointRow(
                        file_path=path,
                        byte_offset=new_offset,
                        file_size=size,
                        file_mtime=mtime,
                        updated_at=time.time(),
                    )
                )

            if count > 0:
                self._update_session(s, session_id, proj_key)

            s.commit()
        return count

    def _process_entry(self, s: Session, entry: dict, session_id: str, proj_key: str) -> None:
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

        evt = EventRow(
            session_id=session_id,
            uuid=uuid,
            parent_uuid=parent_uuid,
            entry_type=entry_type,
            timestamp=ts,
            ts_epoch=ts_epoch,
            proj_key=proj_key,
            model=model if model else None,
            is_sidechain=1 if entry.get("isSidechain") else 0,
        )
        s.add(evt)
        s.flush()

        if entry_type == "assistant":
            self._extract_tools(s, message, evt.id, session_id, proj_key, ts, ts_epoch)
            self._extract_tokens(s, message, evt.id, session_id, proj_key, ts, ts_epoch)

        self._extract_pr(s, entry, session_id, proj_key, ts, ts_epoch)

    def _extract_tools(  # noqa: PLR0913
        self,
        s: Session,
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

            path_field = _FILE_TOOLS.get(tool_name)
            if path_field:
                file_path = tool_input.get(path_field, "")
            elif tool_name == "Bash":
                command = (tool_input.get("command") or "")[:200]

            if not file_path:
                file_path = tool_input.get("file_path", "")

            if tool_name in ("Grep", "Glob"):
                pattern = tool_input.get("pattern", "")

            tool_row = ToolRow(
                event_id=event_id,
                session_id=session_id,
                name=tool_name,
                tool_use_id=block.get("id"),
                file_path=file_path or None,
                command=command,
                pattern=pattern,
                timestamp=ts,
                ts_epoch=ts_epoch,
                proj_key=proj_key,
            )
            s.add(tool_row)
            s.flush()

            if file_path:
                access_type = _ACCESS_TYPE.get(tool_name, "read")
                s.add(
                    FileRow(
                        tool_id=tool_row.id,
                        session_id=session_id,
                        path=file_path,
                        access_type=access_type,
                        timestamp=ts,
                        ts_epoch=ts_epoch,
                        proj_key=proj_key,
                    )
                )

    def _extract_tokens(  # noqa: PLR0913
        self,
        s: Session,
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
            s.add(
                TokenRow(
                    event_id=event_id,
                    session_id=session_id,
                    model=model,
                    input=input_tokens,
                    output=output_tokens,
                    cache_create=cache_create,
                    cache_read=cache_read,
                    timestamp=ts,
                    ts_epoch=ts_epoch,
                    proj_key=proj_key,
                )
            )

    def _extract_pr(  # noqa: PLR0913
        self,
        s: Session,
        entry: dict,
        session_id: str,
        proj_key: str,
        ts: str,
        ts_epoch: float,
    ) -> None:
        message = entry.get("message", {})
        if not isinstance(message, dict):
            return
        content = message.get("content", [])
        if isinstance(content, str):
            self._find_prs(s, content, session_id, proj_key, ts, ts_epoch)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        self._find_prs(s, text, session_id, proj_key, ts, ts_epoch)

    def _find_prs(  # noqa: PLR0913
        self,
        s: Session,
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
            existing = s.execute(
                select(PullRequestRow).where(
                    PullRequestRow.session_id == session_id,
                    PullRequestRow.url == url,
                )
            ).first()
            if not existing:
                s.add(
                    PullRequestRow(
                        session_id=session_id,
                        number=number,
                        url=url,
                        repository=repo,
                        timestamp=ts,
                        ts_epoch=ts_epoch,
                        proj_key=proj_key,
                    )
                )

    def _update_session(self, s: Session, session_id: str, proj_key: str) -> None:
        """Recompute session summary row from event/tool/token tables."""
        row = s.execute(
            select(
                func.min(EventRow.timestamp).label("first_ts"),
                func.max(EventRow.timestamp).label("last_ts"),
                func.min(EventRow.ts_epoch).label("first_epoch"),
                func.max(EventRow.ts_epoch).label("last_epoch"),
                func.sum(func.iif(EventRow.entry_type == "user", 1, 0)).label("user_msgs"),
                func.sum(func.iif(EventRow.entry_type == "assistant", 1, 0)).label("asst_msgs"),
            ).where(EventRow.session_id == session_id)
        ).first()
        if not row or row.first_ts is None:
            return

        tool_count = s.query(func.count(ToolRow.id)).filter(ToolRow.session_id == session_id).scalar()

        token_row = s.execute(
            select(
                func.coalesce(func.sum(TokenRow.input), 0).label("inp"),
                func.coalesce(func.sum(TokenRow.output), 0).label("outp"),
                func.coalesce(func.sum(TokenRow.cache_create + TokenRow.cache_read), 0).label("cache"),
            ).where(TokenRow.session_id == session_id)
        ).first()

        model_row = s.execute(
            select(EventRow.model, func.count().label("c"))
            .where(EventRow.session_id == session_id, EventRow.model.isnot(None), EventRow.model != "")
            .group_by(EventRow.model)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        primary_model = model_row.model if model_row else None

        branch_row = s.execute(
            select(EventRow.git_branch, func.count().label("c"))
            .where(
                EventRow.session_id == session_id,
                EventRow.git_branch.isnot(None),
                EventRow.git_branch != "",
            )
            .group_by(EventRow.git_branch)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        primary_branch = branch_row.git_branch if branch_row else None

        agent_count = s.query(func.count(AgentRow.id)).filter(AgentRow.session_id == session_id).scalar()

        existing = s.get(SessionRow, session_id)
        if existing:
            existing.proj_key = proj_key
            existing.first_ts = row.first_ts
            existing.last_ts = row.last_ts
            existing.first_epoch = row.first_epoch
            existing.last_epoch = row.last_epoch
            existing.user_messages = row.user_msgs
            existing.asst_messages = row.asst_msgs
            existing.tool_count = tool_count
            existing.input_tokens = token_row.inp
            existing.output_tokens = token_row.outp
            existing.cache_tokens = token_row.cache
            existing.primary_model = primary_model
            existing.primary_branch = primary_branch
            existing.agent_count = agent_count
            existing.updated_at = time.time()
        else:
            s.add(
                SessionRow(
                    session_id=session_id,
                    proj_key=proj_key,
                    first_ts=row.first_ts,
                    last_ts=row.last_ts,
                    first_epoch=row.first_epoch,
                    last_epoch=row.last_epoch,
                    user_messages=row.user_msgs,
                    asst_messages=row.asst_msgs,
                    tool_count=tool_count,
                    input_tokens=token_row.inp,
                    output_tokens=token_row.outp,
                    cache_tokens=token_row.cache,
                    primary_model=primary_model,
                    primary_branch=primary_branch,
                    agent_count=agent_count,
                    updated_at=time.time(),
                )
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

"""Analytics repository — all database access: ingest, scan, and queries."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import UTC, datetime

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from claudewatch.backend.analytics.models import (
    ACCESS_TYPE,
    FILE_TOOLS,
    AgentInfo,
    AgentRow,
    BranchActivity,
    CheckpointRow,
    EventRow,
    FileHotspot,
    FileRow,
    FileUsage,
    GlobalSummary,
    PRLink,
    ProjectSummary,
    PullRequestRow,
    RelatedSession,
    SessionOverview,
    SessionRow,
    TimeBucket,
    TokenRow,
    TokenSummary,
    ToolRow,
    ToolSequence,
    ToolUsage,
)
from claudewatch.backend.core.paths import is_safe_projects_path

log = logging.getLogger("claudewatch")

_PR_PATTERN = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)")

_MAX_FILE_PATH = 2048
_MAX_PATTERN = 1024

_STALE_THRESHOLD = 300  # 5 minutes without updates → stale


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

    def process_file(  # noqa: PLR0912
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
                        try:
                            self._process_entry(s, entry, session_id, proj_key)
                            count += 1
                        except IntegrityError:
                            s.rollback()  # duplicate UUID — skip this entry
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

    def _process_entry(self, s: Session, entry: dict[str, object], session_id: str, proj_key: str) -> None:
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
        message: dict[str, object],
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

            path_field = FILE_TOOLS.get(tool_name)
            if path_field:
                file_path = (tool_input.get(path_field) or "")[:_MAX_FILE_PATH]
            elif tool_name == "Bash":
                command = (tool_input.get("command") or "")[:200]

            if not file_path:
                file_path = (tool_input.get("file_path") or "")[:_MAX_FILE_PATH]

            if tool_name in ("Grep", "Glob"):
                pattern = (tool_input.get("pattern") or "")[:_MAX_PATTERN]

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
                access_type = ACCESS_TYPE.get(tool_name, "read")
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
        message: dict[str, object],
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
        entry: dict[str, object],
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


class AgentScanner:
    """Scans disk for subagent metadata and writes to the agents table."""

    def __init__(self, session_factory: sessionmaker[Session], projects_dir: str) -> None:
        self._session_factory = session_factory
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
            if not os.path.isdir(proj_dir) or not is_safe_projects_path(proj_dir, self.projects_dir):
                continue
            try:
                entries = os.listdir(proj_dir)
            except OSError:
                continue
            for entry_name in entries:
                if entry_name.endswith(".jsonl"):
                    session_id = entry_name.removesuffix(".jsonl")
                    total += self.scan_session(proj_key, session_id)
        return total

    def scan_session(self, proj_key: str, session_id: str) -> int:
        """Scan one session directory for subagent metadata. Returns count found."""
        session_dir = os.path.join(self.projects_dir, proj_key, session_id)
        if not os.path.isdir(session_dir) or not is_safe_projects_path(session_dir, self.projects_dir):
            return 0
        count = 0
        try:
            agent_dirs = os.listdir(session_dir)
        except OSError:
            return 0
        with self._session_factory() as s:
            for agent_dir_name in agent_dirs:
                agent_path = os.path.join(session_dir, agent_dir_name)
                if not os.path.isdir(agent_path) or not is_safe_projects_path(agent_path, self.projects_dir):
                    continue
                meta = self._read_meta(agent_path)
                if meta is None:
                    meta = self._infer_from_jsonl(agent_path, agent_dir_name)
                if meta is None:
                    continue
                agent_id = meta.get("agent_id", agent_dir_name)
                agent_type = meta.get("type", meta.get("agent_type", "general-purpose"))
                description = (meta.get("description") or "")[:1000]
                parent = meta.get("parent_agent_id", "")
                started_at = meta.get("started_at", "")
                ended_at = meta.get("ended_at", "")
                entry_count = meta.get("entry_count", 0)
                status = self._derive_status(agent_path, ended_at)
                try:
                    self._upsert_agent(
                        s,
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
                    )
                    count += 1
                except Exception:
                    log.exception("scanner: error inserting agent %s", agent_id)
            s.commit()
        return count

    def _upsert_agent(  # noqa: PLR0913
        self,
        s: Session,
        agent_id: str,
        session_id: str,
        parent: str,
        agent_type: str,
        description: str,
        status: str,
        started_at: str,
        ended_at: str,
        entry_count: int,
        proj_key: str,
    ) -> None:
        existing = s.execute(select(AgentRow).where(AgentRow.agent_id == agent_id)).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.ended_at = ended_at
            existing.entry_count = entry_count
        else:
            s.add(
                AgentRow(
                    agent_id=agent_id,
                    session_id=session_id,
                    parent_agent_id=parent,
                    agent_type=agent_type,
                    description=description,
                    status=status,
                    started_at=started_at,
                    ended_at=ended_at,
                    entry_count=entry_count,
                    proj_key=proj_key,
                )
            )

    def count_agents(self, proj_key: str, session_id: str) -> int:
        """Fast agent count from DB (no disk scan)."""
        with self._session_factory() as s:
            return (
                s.execute(
                    select(func.count(AgentRow.id)).where(
                        AgentRow.session_id == session_id,
                        AgentRow.proj_key == proj_key,
                    )
                ).scalar()
                or 0
            )

    def agents_for_session(self, session_id: str) -> list[AgentInfo]:
        """Query agent info from DB for a given session."""
        with self._session_factory() as s:
            rows = (
                s.execute(select(AgentRow).where(AgentRow.session_id == session_id).order_by(AgentRow.started_at))
                .scalars()
                .all()
            )
            return [
                AgentInfo(
                    agent_id=r.agent_id,
                    session_id=r.session_id,
                    parent_agent_id=r.parent_agent_id or "",
                    agent_type=r.agent_type,
                    description=r.description or "",
                    status=r.status,
                    started_at=r.started_at or "",
                    ended_at=r.ended_at or "",
                    entry_count=r.entry_count,
                    proj_key=r.proj_key,
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
        if ended_at:
            return "completed"
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


class Queries:
    """All read-only analytics queries via SQLAlchemy ORM."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # --- Tools ---

    def tool_usage(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[ToolUsage]:
        with self._session_factory() as s:
            q = select(ToolRow.name, func.count().label("c")).group_by(ToolRow.name)
            if proj_key:
                q = q.where(ToolRow.proj_key == proj_key)
            if since:
                q = q.where(ToolRow.ts_epoch >= since.timestamp())
            q = q.order_by(desc("c")).limit(limit)
            return [ToolUsage(name=r.name, count=r.c) for r in s.execute(q)]

    def tool_trends(
        self,
        proj_key: str,
        granularity: str = "day",
        since: datetime | None = None,
    ) -> list[TimeBucket]:
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
        with self._session_factory() as s:
            bucket_col = func.strftime(fmt, ToolRow.timestamp).label("bucket")
            q = (
                select(bucket_col, func.count().label("c"))
                .where(ToolRow.proj_key == proj_key)
                .group_by("bucket")
                .order_by("bucket")
            )
            if since:
                q = q.where(ToolRow.ts_epoch >= since.timestamp())
            return [TimeBucket(bucket=r.bucket, value=r.c) for r in s.execute(q)]

    # --- Files ---

    def top_files(
        self,
        proj_key: str,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[FileUsage]:
        with self._session_factory() as s:
            q = (
                select(FileRow.path, func.count().label("c"), func.max(FileRow.timestamp).label("last_ts"))
                .where(FileRow.proj_key == proj_key)
                .group_by(FileRow.path)
                .order_by(desc("c"))
            )
            if since:
                q = q.where(FileRow.ts_epoch >= since.timestamp())
            q = q.limit(limit)
            return [FileUsage(path=r.path, count=r.c, last_accessed=r.last_ts) for r in s.execute(q)]

    def files_for_session(self, session_id: str) -> list[FileUsage]:
        with self._session_factory() as s:
            rows = s.execute(
                select(FileRow.path, func.count().label("c"), func.max(FileRow.timestamp).label("last_ts"))
                .where(FileRow.session_id == session_id)
                .group_by(FileRow.path)
                .order_by(desc("c"))
            )
            return [FileUsage(path=r.path, count=r.c, last_accessed=r.last_ts) for r in rows]

    # --- Tokens ---

    def token_summary(self, session_id: str) -> TokenSummary | None:
        with self._session_factory() as s:
            row = s.execute(
                select(
                    TokenRow.model,
                    func.coalesce(func.sum(TokenRow.input), 0).label("inp"),
                    func.coalesce(func.sum(TokenRow.output), 0).label("outp"),
                    func.coalesce(func.sum(TokenRow.cache_create + TokenRow.cache_read), 0).label("cache"),
                )
                .where(TokenRow.session_id == session_id)
                .group_by(TokenRow.model)
                .order_by(desc("inp"))
                .limit(1)
            ).first()
            if not row:
                return None
            total = row.inp + row.outp + row.cache
            return TokenSummary(model=row.model, input=row.inp, output=row.outp, cache=row.cache, total=total)

    def token_by_project(
        self,
        proj_key: str,
        since: datetime | None = None,
    ) -> list[TokenSummary]:
        with self._session_factory() as s:
            q = (
                select(
                    TokenRow.model,
                    func.coalesce(func.sum(TokenRow.input), 0).label("inp"),
                    func.coalesce(func.sum(TokenRow.output), 0).label("outp"),
                    func.coalesce(func.sum(TokenRow.cache_create + TokenRow.cache_read), 0).label("cache"),
                )
                .where(TokenRow.proj_key == proj_key)
                .group_by(TokenRow.model)
                .order_by(desc("inp"))
            )
            if since:
                q = q.where(TokenRow.ts_epoch >= since.timestamp())
            return [
                TokenSummary(model=r.model, input=r.inp, output=r.outp, cache=r.cache, total=r.inp + r.outp + r.cache)
                for r in s.execute(q)
            ]

    def token_trends(
        self,
        proj_key: str | None = None,
        granularity: str = "day",
        since: datetime | None = None,
    ) -> list[TimeBucket]:
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
        with self._session_factory() as s:
            bucket_col = func.strftime(fmt, TokenRow.timestamp).label("bucket")
            total_col = func.sum(TokenRow.input + TokenRow.output + TokenRow.cache_create + TokenRow.cache_read).label(
                "c"
            )
            q = select(bucket_col, total_col).group_by("bucket").order_by("bucket")
            if proj_key:
                q = q.where(TokenRow.proj_key == proj_key)
            if since:
                q = q.where(TokenRow.ts_epoch >= since.timestamp())
            return [TimeBucket(bucket=r.bucket, value=r.c) for r in s.execute(q)]

    # --- Sessions ---

    def session_overview(self, session_id: str) -> SessionOverview | None:
        with self._session_factory() as s:
            row = s.get(SessionRow, session_id)
            return _row_to_overview(row) if row else None

    def recent_sessions(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[SessionOverview]:
        with self._session_factory() as s:
            q = select(SessionRow)
            if proj_key:
                q = q.where(SessionRow.proj_key == proj_key)
            if since:
                q = q.where(SessionRow.last_epoch >= since.timestamp())
            q = q.order_by(desc(SessionRow.last_epoch)).limit(limit)
            return [_row_to_overview(r) for r in s.execute(q).scalars()]

    # --- PRs ---

    def sessions_for_pr(self, pr_number: int) -> list[str]:
        with self._session_factory() as s:
            rows = s.execute(select(distinct(PullRequestRow.session_id)).where(PullRequestRow.number == pr_number))
            return [r[0] for r in rows]

    def prs_for_session(self, session_id: str) -> list[PRLink]:
        with self._session_factory() as s:
            rows = s.execute(
                select(PullRequestRow).where(PullRequestRow.session_id == session_id).order_by(PullRequestRow.timestamp)
            ).scalars()
            return [PRLink(number=r.number, url=r.url, repository=r.repository, timestamp=r.timestamp) for r in rows]

    # --- Global ---

    def summary(self, since: datetime | None = None) -> GlobalSummary:
        with self._session_factory() as s:
            q = select(
                func.count().label("sessions"),
                func.coalesce(func.sum(SessionRow.user_messages + SessionRow.asst_messages), 0).label("messages"),
                func.coalesce(func.sum(SessionRow.tool_count), 0).label("tools"),
                func.coalesce(
                    func.sum(SessionRow.input_tokens + SessionRow.output_tokens + SessionRow.cache_tokens), 0
                ).label("tokens"),
                func.coalesce(func.sum(SessionRow.agent_count), 0).label("agents"),
            )
            if since:
                q = q.where(SessionRow.last_epoch >= since.timestamp())
            row = s.execute(q).first()
            return GlobalSummary(
                total_sessions=row.sessions,
                total_messages=row.messages,
                total_tools=row.tools,
                total_tokens=row.tokens,
                total_agents=row.agents,
            )

    def top_projects(self, limit: int = 10) -> list[ProjectSummary]:
        with self._session_factory() as s:
            rows = s.execute(
                select(
                    SessionRow.proj_key,
                    func.count().label("session_count"),
                    func.coalesce(func.sum(SessionRow.agent_count), 0).label("agent_count"),
                    func.coalesce(func.sum(SessionRow.tool_count), 0).label("tool_count"),
                )
                .group_by(SessionRow.proj_key)
                .order_by(desc("session_count"))
                .limit(limit)
            )
            return [
                ProjectSummary(
                    proj_key=r.proj_key,
                    session_count=r.session_count,
                    agent_count=r.agent_count,
                    tool_count=r.tool_count,
                )
                for r in rows
            ]

    def agent_type_distribution(self, proj_key: str | None = None) -> dict[str, int]:
        with self._session_factory() as s:
            q = select(AgentRow.agent_type, func.count().label("c")).group_by(AgentRow.agent_type).order_by(desc("c"))
            if proj_key:
                q = q.where(AgentRow.proj_key == proj_key)
            return {r.agent_type: r.c for r in s.execute(q)}

    def model_distribution(self, since: datetime | None = None) -> list[ToolUsage]:
        """Model usage across all sessions, returned as ToolUsage(name=model, count=sessions)."""
        with self._session_factory() as s:
            q = (
                select(SessionRow.primary_model, func.count().label("c"))
                .where(SessionRow.primary_model.isnot(None))
                .group_by(SessionRow.primary_model)
                .order_by(desc("c"))
            )
            if since:
                q = q.where(SessionRow.last_epoch >= since.timestamp())
            return [ToolUsage(name=r.primary_model, count=r.c) for r in s.execute(q)]

    # --- Relationship derivation ---

    def related_sessions(self, session_id: str, limit: int = 10) -> list[RelatedSession]:
        """Sessions ranked by shared file count with the given session."""
        f1 = FileRow.__table__.alias("f1")
        f2 = FileRow.__table__.alias("f2")
        with self._session_factory() as s:
            rows = s.execute(
                select(
                    f2.c.session_id,
                    SessionRow.proj_key,
                    func.count(distinct(f2.c.path)).label("shared"),
                    func.group_concat(distinct(f2.c.path)).label("paths"),
                )
                .select_from(f1)
                .join(f2, (f1.c.path == f2.c.path) & (f1.c.session_id != f2.c.session_id))
                .outerjoin(SessionRow, f2.c.session_id == SessionRow.session_id)
                .where(f1.c.session_id == session_id)
                .group_by(f2.c.session_id)
                .order_by(desc("shared"))
                .limit(limit)
            )
            return [
                RelatedSession(
                    session_id=r.session_id,
                    proj_key=r.proj_key or "",
                    shared_files=r.shared,
                    shared_file_paths=(r.paths or "").split(","),
                )
                for r in rows
            ]

    def hotspot_files(
        self,
        proj_key: str,
        since: datetime | None = None,
        min_sessions: int = 2,
        limit: int = 20,
    ) -> list[FileHotspot]:
        with self._session_factory() as s:
            q = (
                select(
                    FileRow.path,
                    func.count(distinct(FileRow.session_id)).label("sess"),
                    func.count().label("total"),
                )
                .where(FileRow.proj_key == proj_key)
                .group_by(FileRow.path)
                .having(func.count(distinct(FileRow.session_id)) >= min_sessions)
                .order_by(desc("sess"), desc("total"))
                .limit(limit)
            )
            if since:
                q = q.where(FileRow.ts_epoch >= since.timestamp())
            return [FileHotspot(path=r.path, session_count=r.sess, total_accesses=r.total) for r in s.execute(q)]

    def tool_sequences(
        self,
        proj_key: str,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[ToolSequence]:
        t1 = ToolRow.__table__.alias("t1")
        t2 = ToolRow.__table__.alias("t2")
        with self._session_factory() as s:
            q = (
                select(t1.c.name.label("first"), t2.c.name.label("second"), func.count().label("c"))
                .select_from(t1)
                .join(t2, (t1.c.session_id == t2.c.session_id) & (t2.c.id == t1.c.id + 1))
                .where(t1.c.proj_key == proj_key)
                .group_by("first", "second")
                .order_by(desc("c"))
            )
            if since:
                q = q.where(t1.c.ts_epoch >= since.timestamp())
            q = q.limit(limit)
            return [ToolSequence(first=r.first, second=r.second, count=r.c) for r in s.execute(q)]

    def tool_usage_by_agent_type(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, list[ToolUsage]]:
        with self._session_factory() as s:
            q = (
                select(AgentRow.agent_type, ToolRow.name, func.count().label("c"))
                .select_from(ToolRow)
                .join(AgentRow, ToolRow.session_id == AgentRow.session_id)
                .group_by(AgentRow.agent_type, ToolRow.name)
                .order_by(AgentRow.agent_type, desc("c"))
            )
            if proj_key:
                q = q.where(ToolRow.proj_key == proj_key)
            if since:
                q = q.where(ToolRow.ts_epoch >= since.timestamp())
            result: dict[str, list[ToolUsage]] = {}
            for r in s.execute(q):
                if r.agent_type not in result:
                    result[r.agent_type] = []
                result[r.agent_type].append(ToolUsage(name=r.name, count=r.c))
            return result

    def complex_sessions(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[SessionOverview]:
        with self._session_factory() as s:
            tool_div = (
                select(func.count(distinct(ToolRow.name)))
                .where(ToolRow.session_id == SessionRow.session_id)
                .correlate(SessionRow)
                .scalar_subquery()
                .label("tool_diversity")
            )
            file_spread = (
                select(func.count(distinct(FileRow.path)))
                .where(FileRow.session_id == SessionRow.session_id)
                .correlate(SessionRow)
                .scalar_subquery()
                .label("file_spread")
            )
            q = select(SessionRow, tool_div, file_spread)
            if proj_key:
                q = q.where(SessionRow.proj_key == proj_key)
            if since:
                q = q.where(SessionRow.last_epoch >= since.timestamp())
            q = q.order_by(desc(tool_div + file_spread + SessionRow.agent_count)).limit(limit)
            return [_row_to_overview(r[0]) for r in s.execute(q)]

    def branch_activity(
        self,
        proj_key: str,
        since: datetime | None = None,
    ) -> list[BranchActivity]:
        with self._session_factory() as s:
            q = (
                select(
                    EventRow.git_branch,
                    func.count(distinct(EventRow.session_id)).label("sess"),
                    func.count().label("events"),
                    func.max(EventRow.timestamp).label("last_ts"),
                )
                .where(EventRow.proj_key == proj_key, EventRow.git_branch.isnot(None), EventRow.git_branch != "")
                .group_by(EventRow.git_branch)
                .order_by(desc("events"))
            )
            if since:
                q = q.where(EventRow.ts_epoch >= since.timestamp())
            return [
                BranchActivity(branch=r.git_branch, session_count=r.sess, event_count=r.events, last_active=r.last_ts)
                for r in s.execute(q)
            ]


def _row_to_overview(r: SessionRow) -> SessionOverview:
    return SessionOverview(
        session_id=r.session_id,
        proj_key=r.proj_key,
        first_ts=r.first_ts or "",
        last_ts=r.last_ts or "",
        user_messages=r.user_messages,
        asst_messages=r.asst_messages,
        tool_count=r.tool_count,
        total_tokens=r.input_tokens + r.output_tokens + r.cache_tokens,
        primary_model=r.primary_model or "",
        primary_branch=r.primary_branch or "",
        agent_count=r.agent_count,
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

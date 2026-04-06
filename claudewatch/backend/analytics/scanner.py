"""Agent scanner — discovers subagents from disk (meta.json + JSONL headers)."""

from __future__ import annotations

import json
import logging
import os
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from claudewatch.backend.analytics.models import AgentInfo
from claudewatch.backend.analytics.store import AgentRow

log = logging.getLogger("claudewatch")

_STALE_THRESHOLD = 300  # 5 minutes without updates → stale


class AgentScanner:
    """Scans disk for subagent metadata and writes to the agents table."""

    def __init__(self, session_factory: object, projects_dir: str) -> None:
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
            if not os.path.isdir(proj_dir):
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
        if not os.path.isdir(session_dir):
            return 0
        count = 0
        try:
            agent_dirs = os.listdir(session_dir)
        except OSError:
            return 0
        with self._session_factory() as s:
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
                s.query(func.count(AgentRow.id))
                .filter(
                    AgentRow.session_id == session_id,
                    AgentRow.proj_key == proj_key,
                )
                .scalar()
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

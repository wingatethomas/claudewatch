"""Analytics queries — read-only SQL returning typed dataclasses."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from claudewatch.backend.analytics.models import (
    BranchActivity,
    FileHotspot,
    FileUsage,
    GlobalSummary,
    PRLink,
    ProjectSummary,
    RelatedSession,
    SessionOverview,
    TimeBucket,
    TokenSummary,
    ToolSequence,
    ToolUsage,
)


class Queries:
    """All read-only analytics queries. Thread-safe for read operations."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- Tools ---

    def tool_usage(
        self,
        proj_key: str,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[ToolUsage]:
        sql = "SELECT name, COUNT(*) AS c FROM tools WHERE proj_key = ?"
        params: list = [proj_key]
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY name ORDER BY c DESC LIMIT ?"
        params.append(limit)
        return [ToolUsage(name=r["name"], count=r["c"]) for r in self._conn.execute(sql, params).fetchall()]

    def tool_trends(
        self,
        proj_key: str,
        granularity: str = "day",
        since: datetime | None = None,
    ) -> list[TimeBucket]:
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
        sql = f"SELECT strftime('{fmt}', timestamp) AS bucket, COUNT(*) AS c FROM tools WHERE proj_key = ?"  # noqa: S608
        params: list = [proj_key]
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY bucket ORDER BY bucket"
        return [TimeBucket(bucket=r["bucket"], value=r["c"]) for r in self._conn.execute(sql, params).fetchall()]

    # --- Files ---

    def top_files(
        self,
        proj_key: str,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[FileUsage]:
        sql = "SELECT path, COUNT(*) AS c, MAX(timestamp) AS last_ts FROM files WHERE proj_key = ?"
        params: list = [proj_key]
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY path ORDER BY c DESC LIMIT ?"
        params.append(limit)
        return [
            FileUsage(path=r["path"], count=r["c"], last_accessed=r["last_ts"])
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def files_for_session(self, session_id: str) -> list[FileUsage]:
        rows = self._conn.execute(
            "SELECT path, COUNT(*) AS c, MAX(timestamp) AS last_ts "
            "FROM files WHERE session_id = ? "
            "GROUP BY path ORDER BY c DESC",
            (session_id,),
        ).fetchall()
        return [FileUsage(path=r["path"], count=r["c"], last_accessed=r["last_ts"]) for r in rows]

    # --- Tokens ---

    def token_summary(self, session_id: str) -> TokenSummary | None:
        row = self._conn.execute(
            "SELECT model, "
            "  COALESCE(SUM(input), 0) AS inp, "
            "  COALESCE(SUM(output), 0) AS outp, "
            "  COALESCE(SUM(cache_create + cache_read), 0) AS cache "
            "FROM tokens WHERE session_id = ? "
            "GROUP BY model ORDER BY inp DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        total = row["inp"] + row["outp"] + row["cache"]
        return TokenSummary(
            model=row["model"],
            input=row["inp"],
            output=row["outp"],
            cache=row["cache"],
            total=total,
        )

    def token_by_project(
        self,
        proj_key: str,
        since: datetime | None = None,
    ) -> list[TokenSummary]:
        sql = (
            "SELECT model, "
            "  COALESCE(SUM(input), 0) AS inp, "
            "  COALESCE(SUM(output), 0) AS outp, "
            "  COALESCE(SUM(cache_create + cache_read), 0) AS cache "
            "FROM tokens WHERE proj_key = ?"
        )
        params: list = [proj_key]
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY model ORDER BY inp DESC"
        return [
            TokenSummary(
                model=r["model"],
                input=r["inp"],
                output=r["outp"],
                cache=r["cache"],
                total=r["inp"] + r["outp"] + r["cache"],
            )
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def token_trends(
        self,
        proj_key: str | None = None,
        granularity: str = "day",
        since: datetime | None = None,
    ) -> list[TimeBucket]:
        fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
        sql = f"SELECT strftime('{fmt}', timestamp) AS bucket, SUM(input + output + cache_create + cache_read) AS c FROM tokens WHERE 1=1"  # noqa: S608, E501
        params: list = []
        if proj_key:
            sql += " AND proj_key = ?"
            params.append(proj_key)
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY bucket ORDER BY bucket"
        return [TimeBucket(bucket=r["bucket"], value=r["c"]) for r in self._conn.execute(sql, params).fetchall()]

    # --- Sessions ---

    def session_overview(self, session_id: str) -> SessionOverview | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return _row_to_overview(row)

    def recent_sessions(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
        limit: int = 20,
    ) -> list[SessionOverview]:
        sql = "SELECT * FROM sessions WHERE 1=1"
        params: list = []
        if proj_key:
            sql += " AND proj_key = ?"
            params.append(proj_key)
        if since:
            sql += " AND last_epoch >= ?"
            params.append(since.timestamp())
        sql += " ORDER BY last_epoch DESC LIMIT ?"
        params.append(limit)
        return [_row_to_overview(r) for r in self._conn.execute(sql, params).fetchall()]

    # --- PRs ---

    def sessions_for_pr(self, pr_number: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT session_id FROM pull_requests WHERE number = ?",
            (pr_number,),
        ).fetchall()
        return [r["session_id"] for r in rows]

    def prs_for_session(self, session_id: str) -> list[PRLink]:
        rows = self._conn.execute(
            "SELECT number, url, repository, timestamp FROM pull_requests WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [
            PRLink(number=r["number"], url=r["url"], repository=r["repository"], timestamp=r["timestamp"]) for r in rows
        ]

    # --- Global ---

    def summary(self, since: datetime | None = None) -> GlobalSummary:
        where = ""
        params: list = []
        if since:
            where = " WHERE last_epoch >= ?"
            params.append(since.timestamp())
        base = "SELECT COUNT(*) AS sessions, COALESCE(SUM(user_messages + asst_messages), 0) AS messages, COALESCE(SUM(tool_count), 0) AS tools, COALESCE(SUM(input_tokens + output_tokens + cache_tokens), 0) AS tokens, COALESCE(SUM(agent_count), 0) AS agents FROM sessions"  # noqa: E501
        row = self._conn.execute(
            base + where,
            params,
        ).fetchone()
        return GlobalSummary(
            total_sessions=row["sessions"],
            total_messages=row["messages"],
            total_tools=row["tools"],
            total_tokens=row["tokens"],
            total_agents=row["agents"],
        )

    def top_projects(self, limit: int = 10) -> list[ProjectSummary]:
        rows = self._conn.execute(
            "SELECT proj_key, "
            "  COUNT(*) AS session_count, "
            "  COALESCE(SUM(agent_count), 0) AS agent_count, "
            "  COALESCE(SUM(tool_count), 0) AS tool_count "
            "FROM sessions "
            "GROUP BY proj_key ORDER BY session_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            ProjectSummary(
                proj_key=r["proj_key"],
                session_count=r["session_count"],
                agent_count=r["agent_count"],
                tool_count=r["tool_count"],
            )
            for r in rows
        ]

    def agent_type_distribution(
        self,
        proj_key: str | None = None,
    ) -> dict[str, int]:
        sql = "SELECT agent_type, COUNT(*) AS c FROM agents"
        params: list = []
        if proj_key:
            sql += " WHERE proj_key = ?"
            params.append(proj_key)
        sql += " GROUP BY agent_type ORDER BY c DESC"
        return {r["agent_type"]: r["c"] for r in self._conn.execute(sql, params).fetchall()}

    # --- Relationship derivation ---

    def related_sessions(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[RelatedSession]:
        """Sessions ranked by shared file count with the given session."""
        rows = self._conn.execute(
            "SELECT f2.session_id, s.proj_key, "
            "  COUNT(DISTINCT f2.path) AS shared, "
            "  GROUP_CONCAT(DISTINCT f2.path) AS paths "
            "FROM files f1 "
            "JOIN files f2 ON f1.path = f2.path AND f1.session_id != f2.session_id "
            "LEFT JOIN sessions s ON f2.session_id = s.session_id "
            "WHERE f1.session_id = ? "
            "GROUP BY f2.session_id "
            "ORDER BY shared DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [
            RelatedSession(
                session_id=r["session_id"],
                proj_key=r["proj_key"] or "",
                shared_files=r["shared"],
                shared_file_paths=(r["paths"] or "").split(","),
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
        """Files touched across many sessions — candidates for refactoring."""
        sql = "SELECT path, COUNT(DISTINCT session_id) AS sess, COUNT(*) AS total FROM files WHERE proj_key = ?"
        params: list = [proj_key]
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY path HAVING sess >= ? ORDER BY sess DESC, total DESC LIMIT ?"
        params.extend([min_sessions, limit])
        return [
            FileHotspot(
                path=r["path"],
                session_count=r["sess"],
                total_accesses=r["total"],
            )
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def tool_sequences(
        self,
        proj_key: str,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[ToolSequence]:
        """Bigram analysis: consecutive tool pairs ranked by frequency."""
        sql = (
            "SELECT t1.name AS first, t2.name AS second, COUNT(*) AS c "
            "FROM tools t1 "
            "JOIN tools t2 ON t1.session_id = t2.session_id AND t2.id = t1.id + 1 "
            "WHERE t1.proj_key = ?"
        )
        params: list = [proj_key]
        if since:
            sql += " AND t1.ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY first, second ORDER BY c DESC LIMIT ?"
        params.append(limit)
        return [
            ToolSequence(first=r["first"], second=r["second"], count=r["c"])
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def tool_usage_by_agent_type(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, list[ToolUsage]]:
        """Tool distribution keyed by agent_type."""
        sql = (
            "SELECT a.agent_type, t.name, COUNT(*) AS c "
            "FROM tools t "
            "JOIN agents a ON t.session_id = a.session_id "
            "WHERE 1=1"
        )
        params: list = []
        if proj_key:
            sql += " AND t.proj_key = ?"
            params.append(proj_key)
        if since:
            sql += " AND t.ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY a.agent_type, t.name ORDER BY a.agent_type, c DESC"
        result: dict[str, list[ToolUsage]] = {}
        for r in self._conn.execute(sql, params).fetchall():
            atype = r["agent_type"]
            if atype not in result:
                result[atype] = []
            result[atype].append(ToolUsage(name=r["name"], count=r["c"]))
        return result

    def complex_sessions(
        self,
        proj_key: str | None = None,
        since: datetime | None = None,
        limit: int = 10,
    ) -> list[SessionOverview]:
        """Sessions ranked by complexity (tool diversity + file spread + agents)."""
        sql = (
            "SELECT s.*, "
            "  (SELECT COUNT(DISTINCT name) FROM tools WHERE session_id = s.session_id) AS tool_diversity, "
            "  (SELECT COUNT(DISTINCT path) FROM files WHERE session_id = s.session_id) AS file_spread "
            "FROM sessions s WHERE 1=1"
        )
        params: list = []
        if proj_key:
            sql += " AND s.proj_key = ?"
            params.append(proj_key)
        if since:
            sql += " AND s.last_epoch >= ?"
            params.append(since.timestamp())
        sql += " ORDER BY (tool_diversity + file_spread + s.agent_count) DESC LIMIT ?"
        params.append(limit)
        return [_row_to_overview(r) for r in self._conn.execute(sql, params).fetchall()]

    def branch_activity(
        self,
        proj_key: str,
        since: datetime | None = None,
    ) -> list[BranchActivity]:
        sql = (
            "SELECT git_branch, "
            "  COUNT(DISTINCT session_id) AS sess, "
            "  COUNT(*) AS events, "
            "  MAX(timestamp) AS last_ts "
            "FROM events "
            "WHERE proj_key = ? AND git_branch IS NOT NULL AND git_branch != ''"
        )
        params: list = [proj_key]
        if since:
            sql += " AND ts_epoch >= ?"
            params.append(since.timestamp())
        sql += " GROUP BY git_branch ORDER BY events DESC"
        return [
            BranchActivity(
                branch=r["git_branch"],
                session_count=r["sess"],
                event_count=r["events"],
                last_active=r["last_ts"],
            )
            for r in self._conn.execute(sql, params).fetchall()
        ]


def _row_to_overview(r: sqlite3.Row) -> SessionOverview:
    return SessionOverview(
        session_id=r["session_id"],
        proj_key=r["proj_key"],
        first_ts=r["first_ts"] or "",
        last_ts=r["last_ts"] or "",
        user_messages=r["user_messages"],
        asst_messages=r["asst_messages"],
        tool_count=r["tool_count"],
        total_tokens=r["input_tokens"] + r["output_tokens"] + r["cache_tokens"],
        primary_model=r["primary_model"] or "",
        primary_branch=r["primary_branch"] or "",
        agent_count=r["agent_count"],
    )

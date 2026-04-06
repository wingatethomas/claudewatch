"""Analytics queries — read-only ORM queries returning typed dataclasses."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.orm import Session, sessionmaker

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
from claudewatch.backend.analytics.store import (
    AgentRow,
    EventRow,
    FileRow,
    PullRequestRow,
    SessionRow,
    TokenRow,
    ToolRow,
)


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
                .limit(limit)
            )
            if since:
                q = q.where(FileRow.ts_epoch >= since.timestamp())
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
                .limit(limit)
            )
            if since:
                q = q.where(t1.c.ts_epoch >= since.timestamp())
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

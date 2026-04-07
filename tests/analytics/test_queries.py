"""Tests for Queries — all SQL read queries against fixtures."""

import json
import os
from datetime import UTC, datetime

import pytest

from claudewatch.backend.analytics.models import (
    AnalyticsStore,
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
from claudewatch.backend.analytics.repository import Ingest, Queries


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _session_entries(
    model: str = "claude-opus-4-6",
    files: list[str] | None = None,
    tools: list[str] | None = None,
    pr_url: str | None = None,
) -> list[dict]:
    files = files or ["/src/main.py"]
    tools = tools or ["Read", "Edit"]
    entries = [
        {
            "type": "user",
            "timestamp": "2026-03-30T12:00:00Z",
            "message": {"role": "user", "content": "do stuff"},
        },
    ]
    content_blocks: list[dict] = []
    for i, tool_name in enumerate(tools):
        block: dict = {"type": "tool_use", "id": f"tu_{i}", "name": tool_name, "input": {}}
        if tool_name in ("Read", "Edit", "Write"):
            block["input"]["file_path"] = files[i % len(files)]
        elif tool_name == "Bash":
            block["input"]["command"] = "pytest"
        elif tool_name == "Grep":
            block["input"]["path"] = files[0]
            block["input"]["pattern"] = "def "
        content_blocks.append(block)
    if pr_url:
        content_blocks.append({"type": "text", "text": f"See {pr_url}"})
    entries.append(
        {
            "type": "assistant",
            "timestamp": "2026-03-30T12:00:01Z",
            "message": {
                "role": "assistant",
                "model": model,
                "content": content_blocks,
                "usage": {"input_tokens": 1000, "output_tokens": 500},
            },
        }
    )
    entries.append(
        {
            "type": "user",
            "timestamp": "2026-03-30T12:00:02Z",
            "message": {"role": "user", "content": "ok"},
        }
    )
    return entries


@pytest.fixture
def store(tmp_path: str) -> AnalyticsStore:
    return AnalyticsStore(os.path.join(tmp_path, "test.db"))


@pytest.fixture
def queries(store: AnalyticsStore) -> Queries:
    return Queries(store.session)


@pytest.fixture
def ingest(store: AnalyticsStore) -> Ingest:
    return Ingest(store.session)


@pytest.fixture
def populated(store: AnalyticsStore, ingest: Ingest, tmp_path: str) -> str:
    proj = os.path.join(tmp_path, "projects", "-proj")
    os.makedirs(proj)
    _write_jsonl(
        os.path.join(proj, "sess-1.jsonl"),
        _session_entries(
            files=["/src/main.py", "/src/auth.py"],
            tools=["Read", "Edit"],
            pr_url="https://github.com/org/repo/pull/10",
        ),
    )
    _write_jsonl(
        os.path.join(proj, "sess-2.jsonl"),
        _session_entries(
            model="claude-sonnet-4-6",
            files=["/src/auth.py", "/src/db.py"],
            tools=["Read", "Bash"],
        ),
    )
    ingest.full_scan(os.path.join(tmp_path, "projects"))
    return "-proj"


class TestToolQueries:
    def test_tool_usage(self, queries: Queries, populated: str) -> None:
        result = queries.tool_usage(populated)
        assert isinstance(result[0], ToolUsage)
        names = {r.name for r in result}
        assert "Read" in names

    def test_tool_usage_with_limit(self, queries: Queries, populated: str) -> None:
        result = queries.tool_usage(populated, limit=1)
        assert len(result) == 1

    def test_tool_usage_global(self, queries: Queries, populated: str) -> None:
        result = queries.tool_usage()
        assert len(result) > 0
        names = {r.name for r in result}
        assert "Read" in names

    def test_tool_trends(self, queries: Queries, populated: str) -> None:
        result = queries.tool_trends(populated)
        assert len(result) > 0
        assert isinstance(result[0], TimeBucket)


class TestFileQueries:
    def test_top_files(self, queries: Queries, populated: str) -> None:
        result = queries.top_files(populated)
        assert len(result) > 0
        assert isinstance(result[0], FileUsage)
        paths = {r.path for r in result}
        assert "/src/auth.py" in paths

    def test_files_for_session(self, queries: Queries, populated: str) -> None:
        result = queries.files_for_session("sess-1")
        assert len(result) > 0


class TestTokenQueries:
    def test_token_summary(self, queries: Queries, populated: str) -> None:
        result = queries.token_summary("sess-1")
        assert result is not None
        assert isinstance(result, TokenSummary)
        assert result.input > 0

    def test_token_summary_missing(self, queries: Queries) -> None:
        assert queries.token_summary("nonexistent") is None

    def test_token_by_project(self, queries: Queries, populated: str) -> None:
        result = queries.token_by_project(populated)
        assert len(result) > 0

    def test_token_trends(self, queries: Queries, populated: str) -> None:
        result = queries.token_trends(proj_key=populated)
        assert len(result) > 0
        assert isinstance(result[0], TimeBucket)


class TestSessionQueries:
    def test_session_overview(self, queries: Queries, populated: str) -> None:
        result = queries.session_overview("sess-1")
        assert result is not None
        assert isinstance(result, SessionOverview)
        assert result.session_id == "sess-1"
        assert result.user_messages == 2

    def test_session_overview_missing(self, queries: Queries) -> None:
        assert queries.session_overview("nonexistent") is None

    def test_recent_sessions(self, queries: Queries, populated: str) -> None:
        result = queries.recent_sessions(proj_key=populated)
        assert len(result) == 2

    def test_recent_sessions_with_limit(self, queries: Queries, populated: str) -> None:
        result = queries.recent_sessions(proj_key=populated, limit=1)
        assert len(result) == 1


class TestPRQueries:
    def test_sessions_for_pr(self, queries: Queries, populated: str) -> None:
        result = queries.sessions_for_pr(10)
        assert "sess-1" in result

    def test_prs_for_session(self, queries: Queries, populated: str) -> None:
        result = queries.prs_for_session("sess-1")
        assert len(result) == 1
        assert isinstance(result[0], PRLink)
        assert result[0].number == 10


class TestGlobalQueries:
    def test_summary(self, queries: Queries, populated: str) -> None:
        result = queries.summary()
        assert isinstance(result, GlobalSummary)
        assert result.total_sessions == 2
        assert result.total_messages > 0
        assert result.total_tools > 0

    def test_summary_with_since(self, queries: Queries, populated: str) -> None:
        future = datetime(2030, 1, 1, tzinfo=UTC)
        result = queries.summary(since=future)
        assert result.total_sessions == 0

    def test_top_projects(self, queries: Queries, populated: str) -> None:
        result = queries.top_projects()
        assert len(result) == 1
        assert isinstance(result[0], ProjectSummary)
        assert result[0].proj_key == "-proj"

    def test_agent_type_distribution_empty(self, queries: Queries, populated: str) -> None:
        result = queries.agent_type_distribution()
        assert isinstance(result, dict)

    def test_model_distribution(self, queries: Queries, populated: str) -> None:
        result = queries.model_distribution()
        assert len(result) > 0
        assert isinstance(result[0], ToolUsage)
        models = {r.name for r in result}
        assert "claude-opus-4-6" in models or "claude-sonnet-4-6" in models


class TestRelationshipQueries:
    def test_related_sessions(self, queries: Queries, populated: str) -> None:
        result = queries.related_sessions("sess-1")
        assert len(result) > 0
        assert isinstance(result[0], RelatedSession)
        assert result[0].session_id == "sess-2"
        assert "/src/auth.py" in result[0].shared_file_paths

    def test_hotspot_files(self, queries: Queries, populated: str) -> None:
        result = queries.hotspot_files(populated)
        assert len(result) >= 1
        assert isinstance(result[0], FileHotspot)
        assert result[0].session_count >= 2

    def test_tool_sequences(self, queries: Queries, populated: str) -> None:
        result = queries.tool_sequences(populated)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], ToolSequence)

    def test_complex_sessions(self, queries: Queries, populated: str) -> None:
        result = queries.complex_sessions(proj_key=populated)
        assert len(result) > 0
        assert isinstance(result[0], SessionOverview)

    def test_branch_activity_empty(self, queries: Queries, populated: str) -> None:
        result = queries.branch_activity(populated)
        assert isinstance(result, list)

"""Tests for AnalyticsService — facade wiring, enrichment."""

import json
import os

import pytest

from claudewatch.backend.analytics.models import AgentInfo
from claudewatch.backend.analytics.service import AnalyticsService


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_entries() -> list[dict]:
    return [
        {
            "type": "user",
            "timestamp": "2026-03-30T12:00:00Z",
            "message": {"role": "user", "content": "Fix the bug"},
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-30T12:00:01Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/src/main.py"}},
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
    ]


@pytest.fixture
def projects_dir(tmp_path: str) -> str:
    proj_dir = os.path.join(tmp_path, "projects", "-Users-dev-app")
    _write_jsonl(os.path.join(proj_dir, "sess-1.jsonl"), _make_entries())
    return os.path.join(tmp_path, "projects")


@pytest.fixture
def service(tmp_path: str, projects_dir: str) -> AnalyticsService:
    db_path = os.path.join(tmp_path, "analytics.db")
    return AnalyticsService(db_path, projects_dir)


class TestAnalyticsService:
    def test_full_scan(self, service: AnalyticsService) -> None:
        stats = service.full_scan()
        assert "sess-1" in stats

    def test_incremental_scan(self, service: AnalyticsService) -> None:
        service.full_scan()
        stats = service.incremental_scan()
        assert len(stats) == 0  # nothing changed

    def test_queries_property(self, service: AnalyticsService) -> None:
        service.full_scan()
        summary = service.queries.summary()
        assert summary.total_sessions == 1

    def test_agents_for_session_empty(self, service: AnalyticsService) -> None:
        result = service.agents_for_session("nonexistent")
        assert result == []

    def test_agents_for_session_with_data(self, service: AnalyticsService, projects_dir: str) -> None:
        # Create an agent directory
        agent_dir = os.path.join(projects_dir, "-Users-dev-app", "sess-1", "agent-x")
        os.makedirs(agent_dir)
        with open(os.path.join(agent_dir, "meta.json"), "w") as f:
            json.dump(
                {
                    "agent_id": "agent-x",
                    "type": "Explore",
                    "description": "search",
                    "ended_at": "2026-01-01T00:01:00Z",
                },
                f,
            )
        service.full_scan()
        agents = service.agents_for_session("sess-1")
        assert len(agents) == 1
        assert isinstance(agents[0], AgentInfo)

    def test_enrich_sessions(self, service: AnalyticsService, projects_dir: str) -> None:
        # Set up agent
        agent_dir = os.path.join(projects_dir, "-Users-dev-app", "sess-1", "agent-x")
        os.makedirs(agent_dir)
        with open(os.path.join(agent_dir, "meta.json"), "w") as f:
            json.dump({"agent_id": "agent-x", "type": "Explore", "ended_at": "x"}, f)
        service.full_scan()

        # Create a mock session object
        class MockSession:
            def __init__(self) -> None:
                self.cwd = "/Users/dev/app"
                self.session_id = "sess-1"
                self.agent_count = 0

        session = MockSession()
        service.enrich_sessions([session])
        assert session.agent_count == 1

    def test_close(self, service: AnalyticsService) -> None:
        service.close()
        # Should not raise

"""Tests for AgentScanner — agent discovery from disk."""

import json
import os

import pytest

from claudewatch.backend.analytics.models import AgentInfo
from claudewatch.backend.analytics.scanner import AgentScanner
from claudewatch.backend.analytics.store import AnalyticsStore


@pytest.fixture
def store(tmp_path: str) -> AnalyticsStore:
    return AnalyticsStore(os.path.join(tmp_path, "test.db"))


@pytest.fixture
def projects_dir(tmp_path: str) -> str:
    return os.path.join(tmp_path, "projects")


def _setup_agent_dir(  # noqa: PLR0913
    projects_dir: str,
    proj_key: str,
    session_id: str,
    agent_id: str,
    *,
    meta: dict | None = None,
    jsonl_entries: list[dict] | None = None,
) -> str:
    proj_dir = os.path.join(projects_dir, proj_key)
    os.makedirs(proj_dir, exist_ok=True)
    session_jsonl = os.path.join(proj_dir, f"{session_id}.jsonl")
    if not os.path.exists(session_jsonl):
        with open(session_jsonl, "w") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {}}) + "\n")

    agent_dir = os.path.join(proj_dir, session_id, agent_id)
    os.makedirs(agent_dir, exist_ok=True)

    if meta is not None:
        with open(os.path.join(agent_dir, "meta.json"), "w") as f:
            json.dump(meta, f)

    if jsonl_entries is not None:
        with open(os.path.join(agent_dir, "agent.jsonl"), "w") as f:
            for entry in jsonl_entries:
                f.write(json.dumps(entry) + "\n")

    return agent_dir


class TestAgentScanner:
    def test_scan_with_meta_json(self, store: AnalyticsStore, projects_dir: str) -> None:
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-a",
            meta={
                "agent_id": "agent-a",
                "type": "Explore",
                "description": "search codebase",
                "started_at": "2026-01-01T00:00:00Z",
                "ended_at": "2026-01-01T00:01:00Z",
            },
        )
        scanner = AgentScanner(store.session, projects_dir)
        count = scanner.scan_session("-proj", "sess-1")
        assert count == 1
        agents = scanner.agents_for_session("sess-1")
        assert len(agents) == 1
        assert agents[0].agent_type == "Explore"
        assert agents[0].status == "completed"

    def test_scan_infers_from_jsonl(self, store: AnalyticsStore, projects_dir: str) -> None:
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-b",
            jsonl_entries=[
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "agentType": "general-purpose",
                    "description": "fix bug",
                },
                {"type": "assistant", "timestamp": "2026-01-01T00:00:01Z"},
            ],
        )
        scanner = AgentScanner(store.session, projects_dir)
        count = scanner.scan_session("-proj", "sess-1")
        assert count == 1
        agents = scanner.agents_for_session("sess-1")
        assert agents[0].agent_type == "general-purpose"

    def test_scan_all_finds_agents(self, store: AnalyticsStore, projects_dir: str) -> None:
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-a",
            meta={"agent_id": "agent-a", "type": "Explore", "ended_at": "2026-01-01T00:01:00Z"},
        )
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-b",
            meta={"agent_id": "agent-b", "type": "Plan", "ended_at": "2026-01-01T00:01:00Z"},
        )
        scanner = AgentScanner(store.session, projects_dir)
        total = scanner.scan_all()
        assert total == 2

    def test_count_agents_from_db(self, store: AnalyticsStore, projects_dir: str) -> None:
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-a",
            meta={"agent_id": "agent-a", "type": "Explore", "ended_at": "x"},
        )
        scanner = AgentScanner(store.session, projects_dir)
        scanner.scan_all()
        assert scanner.count_agents("-proj", "sess-1") == 1
        assert scanner.count_agents("-proj", "nonexistent") == 0

    def test_agents_for_session_returns_typed(self, store: AnalyticsStore, projects_dir: str) -> None:
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-a",
            meta={"agent_id": "agent-a", "type": "Explore", "description": "hi", "ended_at": "x"},
        )
        scanner = AgentScanner(store.session, projects_dir)
        scanner.scan_all()
        agents = scanner.agents_for_session("sess-1")
        assert isinstance(agents[0], AgentInfo)
        assert agents[0].description == "hi"

    def test_empty_projects_dir(self, store: AnalyticsStore, tmp_path: str) -> None:
        scanner = AgentScanner(store.session, os.path.join(tmp_path, "nonexistent"))
        assert scanner.scan_all() == 0

    def test_no_agent_dirs(self, store: AnalyticsStore, projects_dir: str) -> None:
        proj_dir = os.path.join(projects_dir, "-proj")
        os.makedirs(proj_dir)
        with open(os.path.join(proj_dir, "sess-1.jsonl"), "w") as f:
            f.write("{}\n")
        scanner = AgentScanner(store.session, projects_dir)
        assert scanner.scan_session("-proj", "sess-1") == 0

    def test_upsert_updates_status(self, store: AnalyticsStore, projects_dir: str) -> None:
        _setup_agent_dir(
            projects_dir,
            "-proj",
            "sess-1",
            "agent-a",
            meta={"agent_id": "agent-a", "type": "Explore"},
        )
        scanner = AgentScanner(store.session, projects_dir)
        scanner.scan_session("-proj", "sess-1")
        agents = scanner.agents_for_session("sess-1")
        first_status = agents[0].status

        meta_path = os.path.join(projects_dir, "-proj", "sess-1", "agent-a", "meta.json")
        with open(meta_path, "w") as f:
            json.dump({"agent_id": "agent-a", "type": "Explore", "ended_at": "2026-01-01T00:01:00Z"}, f)
        scanner.scan_session("-proj", "sess-1")
        agents = scanner.agents_for_session("sess-1")
        assert agents[0].status == "completed"
        assert first_status != "completed"

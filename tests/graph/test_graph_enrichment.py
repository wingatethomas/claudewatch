"""Tests for graph enrichment of detected sessions."""

import json
import os

from claudewatch.backend.core.models import ClaudeSession, HostApp
from claudewatch.backend.graph.scanner import SubagentScanner
from claudewatch.backend.graph.service import AgentGraphService


def _write_jsonl(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _make_session(cwd: str, session_id: str) -> ClaudeSession:
    return ClaudeSession(
        pid=1234,
        tty="ttys001",
        project=os.path.basename(cwd),
        cwd=cwd,
        host_app=HostApp.TERMINAL,
        session_id=session_id,
    )


class TestEnrichSessions:
    def test_sets_agent_count(self, tmp_path: str) -> None:
        proj_key = "-Users-dev-myapp"
        session_id = "enrich-sess-001"
        proj = os.path.join(tmp_path, proj_key)

        _write_jsonl(os.path.join(proj, f"{session_id}.jsonl"), [])
        subagents = os.path.join(proj, session_id, "subagents")
        _write_jsonl(os.path.join(subagents, "agent-a1.jsonl"), [{"parentUuid": "p"}])
        _write_jsonl(os.path.join(subagents, "agent-a2.jsonl"), [{"parentUuid": "p"}])
        _write_jsonl(os.path.join(subagents, "agent-a3.jsonl"), [{"parentUuid": "p"}])

        scanner = SubagentScanner(str(tmp_path))
        service = AgentGraphService(scanner)

        session = _make_session("/Users/dev/myapp", session_id)
        service.enrich_sessions([session])

        assert session.agent_count == 3

    def test_zero_agents(self, tmp_path: str) -> None:
        proj_key = "-Users-dev-empty"
        session_id = "enrich-sess-002"
        proj = os.path.join(tmp_path, proj_key)
        _write_jsonl(os.path.join(proj, f"{session_id}.jsonl"), [])

        scanner = SubagentScanner(str(tmp_path))
        service = AgentGraphService(scanner)

        session = _make_session("/Users/dev/empty", session_id)
        service.enrich_sessions([session])

        assert session.agent_count == 0

    def test_skips_sessions_without_id(self, tmp_path: str) -> None:
        scanner = SubagentScanner(str(tmp_path))
        service = AgentGraphService(scanner)

        session = _make_session("/Users/dev/myapp", "")
        service.enrich_sessions([session])

        assert session.agent_count == 0

    def test_multiple_sessions(self, tmp_path: str) -> None:
        for session_id, agent_count in [("sess-a", 2), ("sess-b", 0), ("sess-c", 1)]:
            proj = os.path.join(tmp_path, "-Users-dev-multi")
            _write_jsonl(os.path.join(proj, f"{session_id}.jsonl"), [])
            for i in range(agent_count):
                subagents = os.path.join(proj, session_id, "subagents")
                _write_jsonl(os.path.join(subagents, f"agent-{session_id}-{i}.jsonl"), [{"parentUuid": "p"}])

        scanner = SubagentScanner(str(tmp_path))
        service = AgentGraphService(scanner)

        sessions = [
            _make_session("/Users/dev/multi", "sess-a"),
            _make_session("/Users/dev/multi", "sess-b"),
            _make_session("/Users/dev/multi", "sess-c"),
        ]
        service.enrich_sessions(sessions)

        assert sessions[0].agent_count == 2
        assert sessions[1].agent_count == 0
        assert sessions[2].agent_count == 1


class TestScannerCountAgents:
    def test_counts_only_agent_jsonl(self, tmp_path: str) -> None:
        subagents = os.path.join(tmp_path, "-proj", "sess", "subagents")
        _write_jsonl(os.path.join(subagents, "agent-x.jsonl"), [{}])
        _write_jsonl(os.path.join(subagents, "agent-y.jsonl"), [{}])
        _write_json(os.path.join(subagents, "agent-x.meta.json"), {})
        # Non-agent files should be ignored
        os.makedirs(subagents, exist_ok=True)
        with open(os.path.join(subagents, "other.txt"), "w") as f:
            f.write("not an agent")

        scanner = SubagentScanner(str(tmp_path))
        assert scanner.count_agents("-proj", "sess") == 2

    def test_returns_zero_for_missing_dir(self, tmp_path: str) -> None:
        scanner = SubagentScanner(str(tmp_path))
        assert scanner.count_agents("-nonexistent", "sess") == 0

"""Tests for linking agent-team teammate sessions to their parent."""

import os

from claudewatch.backend.core.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.backend.detection.service import link_agent_sessions
from tests.detection.test_detect_integration import _build_service, _cwd_to_proj_dir, _write_jsonl

_TASK = "ORM authorization variant conditions"


def _parent(pid: int = 1, *, task: str = _TASK, last_activity: float = 100.0) -> ClaudeSession:
    return ClaudeSession(
        pid=pid,
        tty=f"ttys{pid:03d}",
        project="mainproj",
        cwd="/Users/dev/mainproj",
        host_app=HostApp.TERMINAL,
        session_id=f"session-{pid}",
        ai_title=task,
        last_activity=last_activity,
    )


def _teammate(pid: int = 9, *, task: str = _TASK) -> ClaudeSession:
    return ClaudeSession(
        pid=pid,
        tty=f"ttys{pid:03d}",
        project="otherrepo",
        cwd="/Users/dev/otherrepo",
        host_app=HostApp.TERMINAL,
        window_title=f"otherrepo — ✳ {task} — node ◂ claude — 120×40",
    )


class TestLinkAgentSessions:
    def test_unpaired_title_match_links_to_parent(self) -> None:
        parent = _parent()
        agent = _teammate()
        link_agent_sessions([parent, agent], {parent.pid: 100.0, agent.pid: 200.0})
        assert agent.agent_of_pid == parent.pid
        assert agent.is_agent
        assert parent.agent_of_pid is None

    def test_paired_teammate_nests_under_earlier_started(self) -> None:
        parent = _parent(pid=1)
        teammate = _parent(pid=2)
        link_agent_sessions([parent, teammate], {1: 100.0, 2: 500.0})
        assert parent.agent_of_pid is None
        assert teammate.agent_of_pid == parent.pid

    def test_paired_sessions_with_distinct_tasks_never_marked(self) -> None:
        first = _parent(pid=1, task="task one")
        second = _parent(pid=2, task="task two")
        link_agent_sessions([first, second], {1: 100.0, 2: 200.0})
        assert first.agent_of_pid is None
        assert second.agent_of_pid is None

    def test_different_task_not_linked(self) -> None:
        parent = _parent()
        agent = _teammate(task="a completely different task")
        link_agent_sessions([parent, agent], {parent.pid: 100.0, agent.pid: 200.0})
        assert agent.agent_of_pid is None

    def test_no_paired_candidate_stays_plain(self) -> None:
        agent = _teammate()
        other = _teammate(pid=10)
        link_agent_sessions([agent, other], {agent.pid: 100.0, other.pid: 200.0})
        assert agent.agent_of_pid is None
        assert other.agent_of_pid is None

    def test_generic_title_never_links(self) -> None:
        parent = _parent(task="Claude Code")
        agent = _teammate(task="Claude Code")
        link_agent_sessions([parent, agent], {parent.pid: 100.0, agent.pid: 200.0})
        assert agent.agent_of_pid is None

    def test_empty_title_never_links(self) -> None:
        parent = _parent()
        agent = _teammate()
        agent.window_title = ""
        link_agent_sessions([parent, agent], {parent.pid: 100.0, agent.pid: 200.0})
        assert agent.agent_of_pid is None

    def test_earliest_started_parent_wins(self) -> None:
        late = _parent(pid=1)
        early = _parent(pid=2)
        agent = _teammate()
        link_agent_sessions([late, early, agent], {1: 500.0, 2: 100.0, agent.pid: 600.0})
        assert agent.agent_of_pid == early.pid
        assert late.agent_of_pid == early.pid
        assert early.agent_of_pid is None

    def test_pid_breaks_start_tie(self) -> None:
        low = _parent(pid=1)
        high = _parent(pid=2)
        agent = _teammate()
        link_agent_sessions([low, high, agent], {1: 100.0, 2: 100.0, agent.pid: 200.0})
        assert agent.agent_of_pid == low.pid

    def test_unknown_start_times_fall_back_to_pid(self) -> None:
        low = _parent(pid=1)
        high = _parent(pid=2)
        link_agent_sessions([low, high], {1: 0.0, 2: 0.0})
        assert low.agent_of_pid is None
        assert high.agent_of_pid == low.pid


class TestDetectLinksAgents:
    def test_detect_links_teammate_with_no_jsonl(self, tmp_path) -> None:
        from claudewatch.backend.core.process.models import ProcessInfo

        parent_cwd = "/Users/dev/mainproj"
        agent_cwd = "/Users/dev/otherrepo"
        entries = [
            {"type": "ai-title", "aiTitle": _TASK},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
        ]
        _write_jsonl(os.path.join(_cwd_to_proj_dir(str(tmp_path), parent_cwd), "s1.jsonl"), entries, age_seconds=120)
        svc = _build_service(
            str(tmp_path),
            [100, 200],
            pid_info={
                100: ProcessInfo(tty="ttys001", ppid=1, comm="claude"),
                200: ProcessInfo(tty="ttys002", ppid=1, comm="claude"),
            },
            pid_cwds={100: parent_cwd, 200: agent_cwd},
            terminal_titles={
                "/dev/ttys001": (f"mainproj — ✳ {_TASK} — node ◂ claude", 1),
                "/dev/ttys002": (f"otherrepo — ✳ {_TASK} — node ◂ claude", 2),
            },
        )
        try:
            sessions = svc.detect()
            by_pid = {s.pid: s for s in sessions}
            assert by_pid[200].agent_of_pid == 100
            assert by_pid[100].agent_of_pid is None
            assert by_pid[200].session_id == ""
            assert by_pid[200].permission_mode == ""
            assert by_pid[200].status == SessionStatus.IDLE
            assert by_pid[200].just_finished is False
        finally:
            for p in svc._test_patchers:
                p.stop()

"""Tests for linking agent-team teammate sessions to their parent."""

import os

from claudewatch.backend.core.models import ClaudeSession, HostApp, SessionStatus
from claudewatch.backend.detection.service import link_agent_sessions
from tests.detection.test_detect_integration import _build_service, _cwd_to_proj_dir, _write_jsonl

_TASK = "ORM authorization variant conditions"
_NOW = 1_000_000.0


def _parent(pid: int = 1, *, task: str = _TASK, last_activity: float = _NOW - 60) -> ClaudeSession:
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


def _teammate(pid: int = 9, *, task: str = _TASK, working: bool = True) -> ClaudeSession:
    spinner = "⠋" if working else "✳"
    return ClaudeSession(
        pid=pid,
        tty=f"ttys{pid:03d}",
        project="otherrepo",
        cwd="/Users/dev/otherrepo",
        host_app=HostApp.TERMINAL,
        status=SessionStatus.WORKING if working else SessionStatus.IDLE,
        window_title=f"otherrepo — {spinner} {task} — node ◂ claude — 120×40",
    )


def _starts(*sessions: ClaudeSession) -> dict[int, float]:
    return {s.pid: _NOW - 600 + s.pid for s in sessions}


class TestLinkAgentSessions:
    def test_unpaired_working_teammate_links(self) -> None:
        parent = _parent()
        agent = _teammate(working=True)
        link_agent_sessions([parent, agent], _starts(parent, agent), _NOW)
        assert agent.agent_of_pid == parent.pid
        assert agent.is_agent
        assert parent.agent_of_pid is None

    def test_unpaired_idle_teammate_does_not_link(self) -> None:
        parent = _parent()
        agent = _teammate(working=False)
        link_agent_sessions([parent, agent], _starts(parent, agent), _NOW)
        assert agent.agent_of_pid is None

    def test_paired_hot_teammate_nests_under_earlier_started(self) -> None:
        parent = _parent(pid=1)
        teammate = _parent(pid=2, last_activity=_NOW - 120)
        teammate.status = SessionStatus.IDLE
        link_agent_sessions([parent, teammate], {1: _NOW - 900, 2: _NOW - 300}, _NOW)
        assert parent.agent_of_pid is None
        assert teammate.agent_of_pid == parent.pid

    def test_cold_paired_pair_never_links(self) -> None:
        first = _parent(pid=1, last_activity=_NOW - 90_000)
        second = _parent(pid=2, last_activity=_NOW - 7_200)
        first.status = SessionStatus.IDLE
        second.status = SessionStatus.IDLE
        link_agent_sessions([first, second], {1: _NOW - 100_000, 2: _NOW - 10_000}, _NOW)
        assert first.agent_of_pid is None
        assert second.agent_of_pid is None

    def test_stale_idle_paired_teammate_does_not_link(self) -> None:
        parent = _parent(pid=1)
        teammate = _parent(pid=2, last_activity=_NOW - 4_000)
        teammate.status = SessionStatus.IDLE
        link_agent_sessions([parent, teammate], {1: _NOW - 900, 2: _NOW - 300}, _NOW)
        assert teammate.agent_of_pid is None

    def test_working_paired_teammate_links_regardless_of_activity(self) -> None:
        parent = _parent(pid=1)
        teammate = _parent(pid=2, last_activity=_NOW - 90_000)
        teammate.status = SessionStatus.WORKING
        link_agent_sessions([parent, teammate], {1: _NOW - 900, 2: _NOW - 300}, _NOW)
        assert teammate.agent_of_pid == parent.pid

    def test_cold_parent_with_hot_teammate_still_links(self) -> None:
        parent = _parent(pid=1, last_activity=_NOW - 90_000)
        parent.status = SessionStatus.IDLE
        teammate = _parent(pid=2, last_activity=_NOW - 60)
        teammate.status = SessionStatus.IDLE
        link_agent_sessions([parent, teammate], {1: _NOW - 100_000, 2: _NOW - 300}, _NOW)
        assert parent.agent_of_pid is None
        assert teammate.agent_of_pid == parent.pid

    def test_paired_sessions_with_distinct_tasks_never_marked(self) -> None:
        first = _parent(pid=1, task="task one")
        second = _parent(pid=2, task="task two")
        link_agent_sessions([first, second], _starts(first, second), _NOW)
        assert first.agent_of_pid is None
        assert second.agent_of_pid is None

    def test_no_paired_candidate_stays_plain(self) -> None:
        agent = _teammate()
        other = _teammate(pid=10)
        link_agent_sessions([agent, other], _starts(agent, other), _NOW)
        assert agent.agent_of_pid is None
        assert other.agent_of_pid is None

    def test_generic_title_never_links(self) -> None:
        parent = _parent(task="Claude Code")
        agent = _teammate(task="Claude Code")
        link_agent_sessions([parent, agent], _starts(parent, agent), _NOW)
        assert agent.agent_of_pid is None

    def test_empty_title_never_links(self) -> None:
        parent = _parent()
        agent = _teammate()
        agent.window_title = ""
        link_agent_sessions([parent, agent], _starts(parent, agent), _NOW)
        assert agent.agent_of_pid is None

    def test_earliest_started_parent_wins(self) -> None:
        late = _parent(pid=1)
        early = _parent(pid=2)
        agent = _teammate()
        link_agent_sessions([late, early, agent], {1: _NOW - 500, 2: _NOW - 900, agent.pid: _NOW - 100}, _NOW)
        assert agent.agent_of_pid == early.pid
        assert late.agent_of_pid == early.pid
        assert early.agent_of_pid is None

    def test_pid_breaks_start_tie(self) -> None:
        low = _parent(pid=1)
        high = _parent(pid=2)
        agent = _teammate()
        link_agent_sessions([low, high, agent], {1: _NOW - 900, 2: _NOW - 900, agent.pid: _NOW - 100}, _NOW)
        assert agent.agent_of_pid == low.pid

    def test_unknown_start_times_fall_back_to_pid(self) -> None:
        low = _parent(pid=1)
        high = _parent(pid=2)
        link_agent_sessions([low, high], {1: 0.0, 2: 0.0}, _NOW)
        assert low.agent_of_pid is None
        assert high.agent_of_pid == low.pid


class TestDetectLinksAgents:
    def _detect(self, tmp_path, *, teammate_title: str):
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
                "/dev/ttys002": (teammate_title, 2),
            },
        )
        try:
            return {s.pid: s for s in svc.detect()}
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_detect_links_working_teammate_with_no_jsonl(self, tmp_path) -> None:
        by_pid = self._detect(tmp_path, teammate_title=f"otherrepo — ⠋ {_TASK} — node ◂ claude")
        assert by_pid[200].agent_of_pid == 100
        assert by_pid[100].agent_of_pid is None
        assert by_pid[200].session_id == ""
        assert by_pid[200].permission_mode == ""
        assert by_pid[200].just_finished is False

    def test_detect_leaves_idle_unpaired_teammate_plain(self, tmp_path) -> None:
        by_pid = self._detect(tmp_path, teammate_title=f"otherrepo — ✳ {_TASK} — node ◂ claude")
        assert by_pid[200].status == SessionStatus.IDLE
        assert by_pid[200].agent_of_pid is None

"""Tests for recency ordering of detected sessions."""

from claudewatch.backend.core.models import ClaudeSession, HostApp
from claudewatch.backend.detection.service import sort_by_last_activity


def _session(pid: int, last_activity: float) -> ClaudeSession:
    return ClaudeSession(
        pid=pid,
        tty=f"ttys{pid:03d}",
        project="proj",
        cwd="/tmp/proj",
        host_app=HostApp.TERMINAL,
        last_activity=last_activity,
    )


class TestSortByLastActivity:
    def test_newest_first(self) -> None:
        sessions = [_session(1, 100.0), _session(2, 700.0), _session(3, 400.0)]
        sort_by_last_activity(sessions)
        assert [s.pid for s in sessions] == [2, 3, 1]

    def test_unpaired_sessions_sink_last(self) -> None:
        sessions = [_session(1, 0.0), _session(2, 500.0)]
        sort_by_last_activity(sessions)
        assert [s.pid for s in sessions] == [2, 1]

    def test_same_bucket_keeps_pid_order(self) -> None:
        sessions = [_session(9, 95.0), _session(4, 92.0), _session(7, 90.0)]
        sort_by_last_activity(sessions)
        assert [s.pid for s in sessions] == [4, 7, 9]

    def test_distinct_buckets_beat_pid_order(self) -> None:
        sessions = [_session(1, 90.0), _session(2, 150.0)]
        sort_by_last_activity(sessions)
        assert [s.pid for s in sessions] == [2, 1]

    def test_empty_list(self) -> None:
        sessions: list[ClaudeSession] = []
        sort_by_last_activity(sessions)
        assert sessions == []

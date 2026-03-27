"""Tests for ProcessService — delegation and child PID registry."""

from unittest.mock import patch

from claudewatch.backend.core.process.models import ProcessEntry, ProcessInfo
from claudewatch.backend.core.process.service import ProcessService


class TestProcessServiceDelegation:
    """Verify that ProcessService methods delegate to procinfo functions."""

    def setup_method(self) -> None:
        self.svc = ProcessService()

    @patch("claudewatch.backend.core.process.service.procinfo.list_all_processes")
    def test_list_all(self, mock_list_all):
        mock_list_all.return_value = [ProcessEntry(pid=1, tty="??", ppid=0, comm="/sbin/launchd")]
        result = self.svc.list_all()
        assert result == [ProcessEntry(pid=1, tty="??", ppid=0, comm="/sbin/launchd")]
        mock_list_all.assert_called_once()

    @patch("claudewatch.backend.core.process.service.procinfo.get_process_info")
    def test_get_info(self, mock_get_info):
        mock_get_info.return_value = {42: ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")}
        result = self.svc.get_info([42])
        assert result == {42: ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")}
        mock_get_info.assert_called_once_with([42])

    @patch("claudewatch.backend.core.process.service.procinfo.get_process_info")
    def test_get_info_empty(self, mock_get_info):
        mock_get_info.return_value = {}
        assert self.svc.get_info([]) == {}
        mock_get_info.assert_called_once_with([])

    @patch("claudewatch.backend.core.process.service.procinfo.get_cwds")
    def test_get_cwds(self, mock_get_cwds):
        mock_get_cwds.return_value = {42: "/Users/test/project"}
        result = self.svc.get_cwds([42])
        assert result == {42: "/Users/test/project"}
        mock_get_cwds.assert_called_once_with([42])

    @patch("claudewatch.backend.core.process.service.procinfo.get_cwds")
    def test_get_cwds_empty(self, mock_get_cwds):
        mock_get_cwds.return_value = {}
        assert self.svc.get_cwds([]) == {}

    @patch("claudewatch.backend.core.process.service.procinfo.get_ppid")
    def test_get_ppid(self, mock_get_ppid):
        mock_get_ppid.return_value = 1
        assert self.svc.get_ppid(42) == 1
        mock_get_ppid.assert_called_once_with(42)

    @patch("claudewatch.backend.core.process.service.procinfo.get_ppid")
    def test_get_ppid_failure(self, mock_get_ppid):
        mock_get_ppid.return_value = 0
        assert self.svc.get_ppid(99999) == 0

    @patch("claudewatch.backend.core.process.service.procinfo.get_single_process_info")
    def test_get_single_info(self, mock_single):
        mock_single.return_value = ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")
        result = self.svc.get_single_info(42)
        assert result == ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")
        mock_single.assert_called_once_with(42)

    @patch("claudewatch.backend.core.process.service.procinfo.get_single_process_info")
    def test_get_single_info_failure(self, mock_single):
        mock_single.return_value = None
        assert self.svc.get_single_info(99999) is None


class TestChildPidRegistry:
    """Tests for the child PID registry (register, unregister, get)."""

    def setup_method(self) -> None:
        self.svc = ProcessService()

    def test_initially_empty(self):
        assert self.svc.get_child_pids() == set()

    def test_register_child(self):
        self.svc.register_child(100)
        assert self.svc.get_child_pids() == {100}

    def test_register_multiple(self):
        self.svc.register_child(100)
        self.svc.register_child(200)
        self.svc.register_child(300)
        assert self.svc.get_child_pids() == {100, 200, 300}

    def test_register_duplicate(self):
        self.svc.register_child(100)
        self.svc.register_child(100)
        assert self.svc.get_child_pids() == {100}

    def test_unregister_child(self):
        self.svc.register_child(100)
        self.svc.register_child(200)
        self.svc.unregister_child(100)
        assert self.svc.get_child_pids() == {200}

    def test_unregister_nonexistent(self):
        # Should not raise
        self.svc.unregister_child(999)
        assert self.svc.get_child_pids() == set()

    def test_get_child_pids_returns_copy(self):
        self.svc.register_child(100)
        pids = self.svc.get_child_pids()
        pids.add(999)  # mutate the returned set
        assert 999 not in self.svc.get_child_pids()

    def test_register_unregister_all(self):
        self.svc.register_child(100)
        self.svc.register_child(200)
        self.svc.unregister_child(100)
        self.svc.unregister_child(200)
        assert self.svc.get_child_pids() == set()

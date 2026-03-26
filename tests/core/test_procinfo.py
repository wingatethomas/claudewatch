"""Tests for claudewatch.backend.procinfo — native libproc bindings."""

from unittest.mock import patch

from claudewatch.backend.core.process.procinfo import (
    _dev_to_tty,
    get_cwds,
    get_ppid,
    get_process_info,
    get_single_process_info,
    list_all_processes,
)


class TestDevToTty:
    """Tests for _dev_to_tty() device number conversion."""

    def test_pty_device(self):
        # major=16, minor=1 → "ttys001"
        dev = (16 << 24) | 1
        assert _dev_to_tty(dev) == "ttys001"

    def test_pty_device_high_minor(self):
        # major=16, minor=42 → "ttys042"
        dev = (16 << 24) | 42
        assert _dev_to_tty(dev) == "ttys042"

    def test_zero_dev(self):
        assert _dev_to_tty(0) == "??"

    def test_invalid_dev(self):
        assert _dev_to_tty(-1) == "??"
        assert _dev_to_tty(0xFFFFFFFF) == "??"

    def test_non_pty_major(self):
        # major=5 (console), not a PTY
        dev = (5 << 24) | 0
        assert _dev_to_tty(dev) == "??"


class TestGetProcessInfo:
    """Tests for get_process_info()."""

    def test_empty_pids(self):
        assert get_process_info([]) == {}


class TestGetCwds:
    """Tests for get_cwds()."""

    def test_empty_pids(self):
        assert get_cwds([]) == {}


class TestGetPpid:
    """Tests for get_ppid()."""

    @patch("claudewatch.backend.core.process.procinfo._libproc")
    def test_returns_zero_on_failure(self, mock_libproc):
        mock_libproc.proc_pidinfo.return_value = 0
        assert get_ppid(99999) == 0


class TestGetSingleProcessInfo:
    """Tests for get_single_process_info()."""

    @patch("claudewatch.backend.core.process.procinfo._libproc")
    def test_returns_none_on_failure(self, mock_libproc):
        mock_libproc.proc_pidinfo.return_value = 0
        assert get_single_process_info(99999) is None


class TestListAllProcesses:
    """Tests for list_all_processes()."""

    @patch("claudewatch.backend.core.process.procinfo._list_all_pids")
    @patch("claudewatch.backend.core.process.procinfo._libproc")
    def test_returns_empty_for_no_pids(self, mock_libproc, mock_list_all):
        mock_list_all.return_value = []
        assert list_all_processes() == []

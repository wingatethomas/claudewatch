"""Tests for process info typed models."""

import pytest

from claudewatch.backend.core.process.models import ProcessEntry, ProcessInfo


class TestProcessInfo:
    def test_construction(self):
        info = ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")
        assert info.tty == "ttys001"
        assert info.ppid == 1
        assert info.comm == "/bin/zsh"

    def test_frozen(self):
        info = ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")
        with pytest.raises(AttributeError):
            info.tty = "ttys002"  # type: ignore[misc]

    def test_equality(self):
        a = ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")
        b = ProcessInfo(tty="ttys001", ppid=1, comm="/bin/zsh")
        assert a == b


class TestProcessEntry:
    def test_construction(self):
        entry = ProcessEntry(pid=42, tty="ttys001", ppid=1, comm="/bin/zsh")
        assert entry.pid == 42
        assert entry.tty == "ttys001"

    def test_frozen(self):
        entry = ProcessEntry(pid=42, tty="ttys001", ppid=1, comm="/bin/zsh")
        with pytest.raises(AttributeError):
            entry.pid = 99  # type: ignore[misc]

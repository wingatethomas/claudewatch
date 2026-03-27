"""Tests for summary domain typed models."""

import pytest

from claudewatch.backend.summary.models import SummaryEntry


class TestSummaryEntry:
    def test_construction(self):
        entry = SummaryEntry(title="Refactoring auth", summary="- Updated login flow", mtime=1234567890.0)
        assert entry.title == "Refactoring auth"
        assert entry.summary == "- Updated login flow"
        assert entry.mtime == 1234567890.0

    def test_frozen(self):
        entry = SummaryEntry(title="x", summary="y", mtime=1.0)
        with pytest.raises(AttributeError):
            entry.title = "z"  # type: ignore[misc]

    def test_equality(self):
        a = SummaryEntry(title="x", summary="y", mtime=1.0)
        b = SummaryEntry(title="x", summary="y", mtime=1.0)
        assert a == b

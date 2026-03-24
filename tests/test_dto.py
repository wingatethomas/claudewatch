"""Tests for DTO construction and immutability."""

import pytest

from claudewatch.backend.core.dto import (
    ActivityEventDTO,
    BaseDTO,
    HistoryEntryDTO,
    PinDTO,
    SessionDTO,
    TokenUsageDTO,
    UpdateInfoDTO,
)
from claudewatch.backend.core.models import HostApp, SessionStatus


class TestBaseDTO:
    def test_to_dict(self):
        class SimpleDTO(BaseDTO):
            pass

        dto = SimpleDTO()
        assert dto.to_dict() == {}


class TestSessionDTO:
    def test_construction(self):
        dto = SessionDTO(
            pid=123, project="test", cwd="/tmp/test", status=SessionStatus.WORKING,
            host_app=HostApp.TERMINAL, session_id="abc-123", tty="/dev/ttys001",
            window_id=42, menu_label="test", detail_line="doing stuff",
            task_summary="testing", last_output="done", needs_attention=False,
        )
        assert dto.pid == 123
        assert dto.status == SessionStatus.WORKING

    def test_frozen(self):
        dto = SessionDTO(
            pid=1, project="x", cwd="/x", status=SessionStatus.IDLE,
            host_app=HostApp.TERMINAL, session_id="", tty="", window_id=None,
            menu_label="", detail_line="", task_summary="", last_output="",
            needs_attention=False,
        )
        with pytest.raises(AttributeError):
            dto.pid = 999  # type: ignore[misc]

    def test_to_dict(self):
        dto = SessionDTO(
            pid=1, project="x", cwd="/x", status=SessionStatus.IDLE,
            host_app=HostApp.TERMINAL, session_id="", tty="", window_id=None,
            menu_label="", detail_line="", task_summary="", last_output="",
            needs_attention=False,
        )
        d = dto.to_dict()
        assert d["pid"] == 1
        assert d["project"] == "x"


class TestPinDTO:
    def test_construction(self):
        dto = PinDTO(session_id="abc", project="proj", cwd="/tmp", note="hi", timestamp="2026-01-01")
        assert dto.project == "proj"


class TestHistoryEntryDTO:
    def test_construction(self):
        dto = HistoryEntryDTO(
            session_id="abc", project="proj", cwd="/tmp",
            model="opus", host_app="Terminal", ended_at="2026-01-01",
        )
        assert dto.model == "opus"


class TestUpdateInfoDTO:
    def test_construction(self):
        dto = UpdateInfoDTO(tag="v1.0.0", download_url="https://example.com")
        assert dto.tag == "v1.0.0"


class TestActivityEventDTO:
    def test_construction(self):
        dto = ActivityEventDTO(kind="tool_use", summary="Read file", detail="foo.py", timestamp="12:00")
        assert dto.kind == "tool_use"


class TestTokenUsageDTO:
    def test_construction(self):
        dto = TokenUsageDTO(
            input_tokens=100, output_tokens=50, cache_read=10, cache_write=5,
            model="opus", breakdown_lines=("In: 100", "Out: 50"),
        )
        assert dto.input_tokens == 100
        assert isinstance(dto.breakdown_lines, tuple)

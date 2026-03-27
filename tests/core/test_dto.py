"""Tests for DTO construction and immutability."""

import pytest

from claudewatch.backend.core.dto import (
    ActivityEventDTO,
    BaseDTO,
    BookmarkDTO,
    ChangelogEntryDTO,
    HistoryEntryDTO,
    TokenUsageDTO,
    UpdateInfoDTO,
)


class TestBaseDTO:
    def test_to_dict(self):
        class SimpleDTO(BaseDTO):
            pass

        dto = SimpleDTO()
        assert dto.to_dict() == {}


class TestBookmarkDTO:
    def test_construction(self):
        dto = BookmarkDTO(session_id="abc", project="proj", cwd="/tmp", note="hi", timestamp="2026-01-01")
        assert dto.project == "proj"

    def test_frozen(self):
        dto = BookmarkDTO(session_id="abc", project="proj", cwd="/tmp", note="hi", timestamp="2026-01-01")
        with pytest.raises(AttributeError):
            dto.project = "new"  # type: ignore[misc]

    def test_to_dict(self):
        dto = BookmarkDTO(session_id="abc", project="proj", cwd="/tmp", note="hi", timestamp="2026-01-01")
        d = dto.to_dict()
        assert d["project"] == "proj"
        assert d["cwd"] == "/tmp"


class TestHistoryEntryDTO:
    def test_construction(self):
        dto = HistoryEntryDTO(
            session_id="abc",
            project="proj",
            cwd="/tmp",
            model="opus",
            host_app="Terminal",
            ended_at="2026-01-01",
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
        dto = TokenUsageDTO(input=100, output=50, cache_create=200, cache_read=300)
        assert dto.input == 100
        assert dto.output == 50

    def test_total_property(self):
        dto = TokenUsageDTO(input=100, output=50, cache_create=200, cache_read=300)
        assert dto.total == 650

    def test_total_zero(self):
        dto = TokenUsageDTO(input=0, output=0, cache_create=0, cache_read=0)
        assert dto.total == 0

    def test_frozen(self):
        dto = TokenUsageDTO(input=100, output=50, cache_create=0, cache_read=0)
        with pytest.raises(AttributeError):
            dto.input = 999  # type: ignore[misc]

    def test_to_dict(self):
        dto = TokenUsageDTO(input=100, output=50, cache_create=200, cache_read=300)
        d = dto.to_dict()
        assert d["input"] == 100
        assert d["cache_create"] == 200


class TestChangelogEntryDTO:
    def test_construction(self):
        dto = ChangelogEntryDTO(tag="v1.0.0", body="- Added feature\n- Fixed bug")
        assert dto.tag == "v1.0.0"
        assert "feature" in dto.body

    def test_frozen(self):
        dto = ChangelogEntryDTO(tag="v1.0.0", body="notes")
        with pytest.raises(AttributeError):
            dto.tag = "v2.0.0"  # type: ignore[misc]

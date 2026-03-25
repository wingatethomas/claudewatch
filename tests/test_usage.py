"""Tests for claudewatch.backend.usage.service."""

import json
from unittest.mock import MagicMock

from claudewatch.backend.usage.service import MODEL_DISPLAY_NAMES, UsageService


def _make_service(
    find_most_recent: str | None = None,
    read_tail: str = "",
    read_full: list[str] | None = None,
) -> UsageService:
    """Create a UsageService with a mocked SessionLogService."""
    mock_log = MagicMock()
    mock_log.find_most_recent.return_value = find_most_recent
    mock_log.read_tail.return_value = read_tail
    mock_log.read_full.return_value = read_full or []
    return UsageService(mock_log)


class TestModelDisplayNames:
    """MODEL_DISPLAY_NAMES mapping tests."""

    def test_known_models_have_display_names(self):
        assert MODEL_DISPLAY_NAMES["claude-opus-4-6"] == "o4.6"
        assert MODEL_DISPLAY_NAMES["claude-sonnet-4-6"] == "s4.6"
        assert MODEL_DISPLAY_NAMES["claude-haiku-4-5"] == "h4.5"


class TestUsageServiceGetModel:
    """Tests for UsageService.get_model."""

    def test_returns_empty_when_no_jsonl_found(self):
        svc = _make_service(find_most_recent=None)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_when_tail_empty(self):
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail="")
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_display_name_for_known_model(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "o4.6"

    def test_returns_raw_model_for_unknown(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-future-99"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-future-99"

    def test_uses_last_model_in_file(self):
        tail = (
            json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}}) + "\n"
            + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        )
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "o4.6"

    def test_handles_invalid_json_lines(self):
        tail = (
            "not json\n"
            + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        )
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "o4.6"

    def test_handles_non_dict_message(self):
        tail = json.dumps({"type": "assistant", "message": "string"}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_for_no_model_field(self):
        tail = json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""



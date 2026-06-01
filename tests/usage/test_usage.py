"""Tests for claudewatch.backend.usage.service."""

import json
from unittest.mock import MagicMock

from claudewatch.backend.usage.service import UsageService, model_display_name


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


class TestModelDisplayName:
    """model_display_name derives a human label from a raw model id."""

    def test_opus_with_minor(self):
        assert model_display_name("claude-opus-4-7") == "opus 4.7"
        assert model_display_name("claude-opus-4-6") == "opus 4.6"

    def test_sonnet_with_minor(self):
        assert model_display_name("claude-sonnet-4-6") == "sonnet 4.6"

    def test_haiku_with_minor(self):
        assert model_display_name("claude-haiku-4-5") == "haiku 4.5"

    def test_date_suffix_stripped(self):
        # 8+ digit release date trailing the version is dropped.
        assert model_display_name("claude-haiku-4-5-20251001") == "haiku 4.5"
        assert model_display_name("claude-sonnet-4-5-20250514") == "sonnet 4.5"

    def test_no_minor_with_date(self):
        # Family + major + date with no minor: keep just family + major.
        assert model_display_name("claude-opus-4-20250512") == "opus 4"

    def test_unrecognized_id_passes_through(self):
        # Unknown patterns are returned unchanged so the user still sees something.
        assert model_display_name("claude-future-99") == "claude-future-99"
        assert model_display_name("gpt-4") == "gpt-4"

    def test_empty_input(self):
        assert model_display_name("") == ""

    def test_future_minor_versions_handled(self):
        # New models should derive without code changes.
        assert model_display_name("claude-opus-5-0") == "opus 5.0"
        assert model_display_name("claude-sonnet-5-2") == "sonnet 5.2"


class TestUsageServiceGetModel:
    """Tests for UsageService.get_model — returns raw model ids."""

    def test_returns_empty_when_no_jsonl_found(self):
        svc = _make_service(find_most_recent=None)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_when_tail_empty(self):
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail="")
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_raw_id_for_known_model(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_returns_raw_model_for_unknown(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-future-99"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-future-99"

    def test_uses_last_model_in_file(self):
        tail = (
            json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}})
            + "\n"
            + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}})
            + "\n"
        )
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_skips_synthetic_placeholder(self):
        # Claude Code sometimes emits "<synthetic>" as a model value on internal
        # entries — we must not let that leak into history/display.
        tail = (
            json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}})
            + "\n"
            + json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}})
            + "\n"
        )
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_returns_empty_when_only_synthetic(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_handles_invalid_json_lines(self):
        tail = "not json\n" + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_handles_non_dict_message(self):
        tail = json.dumps({"type": "assistant", "message": "string"}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_for_no_model_field(self):
        tail = json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
        svc = _make_service(find_most_recent="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

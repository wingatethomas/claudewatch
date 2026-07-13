"""Tests for claudewatch.backend.usage.service."""

import json
import os
import time
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.usage.service import UsageService, model_display_name


def _make_service(
    resolve_jsonl: str | None = None,
    read_tail: str = "",
    read_full: list[str] | None = None,
) -> UsageService:
    """Create a UsageService with a mocked SessionLogService."""
    mock_log = MagicMock()
    mock_log.resolve_jsonl.return_value = resolve_jsonl
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

    def test_new_family_derives_without_code_changes(self):
        assert model_display_name("claude-fable-5") == "fable 5"
        assert model_display_name("claude-future-99") == "future 99"

    def test_unrecognized_id_passes_through(self):
        # Non-Claude / unparseable ids are returned unchanged.
        assert model_display_name("gpt-4") == "gpt-4"
        assert model_display_name("claude-fable-5[1m]") == "claude-fable-5[1m]"

    def test_empty_input(self):
        assert model_display_name("") == ""

    def test_future_minor_versions_handled(self):
        # New models should derive without code changes.
        assert model_display_name("claude-opus-5-0") == "opus 5.0"
        assert model_display_name("claude-sonnet-5-2") == "sonnet 5.2"


class TestUsageServiceGetModel:
    """Tests for UsageService.get_model — returns raw model ids."""

    def test_returns_empty_when_no_jsonl_found(self):
        svc = _make_service(resolve_jsonl=None)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_when_tail_empty(self):
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail="")
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_raw_id_for_known_model(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_returns_raw_model_for_unknown(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "claude-future-99"}}) + "\n"
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-future-99"

    def test_uses_last_model_in_file(self):
        tail = (
            json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}})
            + "\n"
            + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}})
            + "\n"
        )
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
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
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_returns_empty_when_only_synthetic(self):
        tail = json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}) + "\n"
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_handles_invalid_json_lines(self):
        tail = "not json\n" + json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n"
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == "claude-opus-4-6"

    def test_handles_non_dict_message(self):
        tail = json.dumps({"type": "assistant", "message": "string"}) + "\n"
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_returns_empty_for_no_model_field(self):
        tail = json.dumps({"type": "user", "message": {"content": "hello"}}) + "\n"
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail=tail)
        assert svc.get_model("/Users/dev/myapp") == ""

    def test_no_session_id_resolves_most_recent(self):
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail="")
        svc.get_model("/Users/dev/myapp")
        svc._session_log_service.resolve_jsonl.assert_called_once_with("/Users/dev/myapp", "")

    def test_session_id_passed_through(self):
        svc = _make_service(resolve_jsonl="/fake/path.jsonl", read_tail="")
        svc.get_model("/Users/dev/myapp", "sid-a")
        svc._session_log_service.resolve_jsonl.assert_called_once_with("/Users/dev/myapp", "sid-a")


def _write_session(path, model: str, input_tokens: int, output_tokens: int, mtime: float) -> None:
    """Write a one-message session JSONL and pin its mtime."""
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}},
        }
    )
    path.write_text(line + "\n")
    os.utime(path, (mtime, mtime))


class TestUsageServiceSharedCwd:
    """Two sessions sharing one cwd must not read each other's JSONL."""

    def test_session_id_wins_over_newer_sibling(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        now = time.time()
        _write_session(proj_dir / "sid-a.jsonl", "claude-opus-4-6", 100, 50, now - 100)
        _write_session(proj_dir / "sid-b.jsonl", "claude-sonnet-4-6", 7, 3, now)

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc = UsageService(SessionLogService())
            assert svc.get_model("/Users/dev/myapp", "sid-a") == "claude-opus-4-6"
            tokens_a = svc.get_tokens("/Users/dev/myapp", "sid-a")
            assert (tokens_a.input, tokens_a.output) == (100, 50)
            # No session_id still falls back to the most recent file.
            assert svc.get_model("/Users/dev/myapp") == "claude-sonnet-4-6"
            tokens_recent = svc.get_tokens("/Users/dev/myapp")
            assert (tokens_recent.input, tokens_recent.output) == (7, 3)

    def test_gone_session_returns_empty_not_sibling(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        _write_session(proj_dir / "sid-b.jsonl", "claude-sonnet-4-6", 7, 3, time.time())

        with patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            svc = UsageService(SessionLogService())
            assert svc.get_model("/Users/dev/myapp", "sid-gone") == ""
            assert svc.get_tokens("/Users/dev/myapp", "sid-gone").total == 0

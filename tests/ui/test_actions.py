"""Tests for preferences action handlers — activity payload parsing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from claudewatch.ui.preferences.handlers.actions import handle_view_activity


def _sender(payload: str) -> MagicMock:
    sender = MagicMock()
    sender.representedObject.return_value = payload
    return sender


class TestHandleViewActivity:
    def test_three_part_payload_passes_session_id(self) -> None:
        sid = "11111111-1111-1111-1111-111111111111"
        with patch("claudewatch.ui.preferences.handlers.actions.show_activity") as show:
            handle_view_activity(None, _sender(f"myapp|/Users/dev/myapp|{sid}"))
        show.assert_called_once_with("myapp", "/Users/dev/myapp", sid)

    def test_legacy_two_part_payload_empty_session_id(self) -> None:
        with patch("claudewatch.ui.preferences.handlers.actions.show_activity") as show:
            handle_view_activity(None, _sender("myapp|/Users/dev/myapp"))
        show.assert_called_once_with("myapp", "/Users/dev/myapp", "")

    def test_three_part_payload_with_empty_session_id(self) -> None:
        with patch("claudewatch.ui.preferences.handlers.actions.show_activity") as show:
            handle_view_activity(None, _sender("myapp|/Users/dev/myapp|"))
        show.assert_called_once_with("myapp", "/Users/dev/myapp", "")

    def test_no_pipe_payload_ignored(self) -> None:
        with patch("claudewatch.ui.preferences.handlers.actions.show_activity") as show:
            handle_view_activity(None, _sender("garbage"))
        show.assert_not_called()

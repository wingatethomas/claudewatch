"""Tests for SessionRow composite."""

from AppKit import NSButton, NSView

from claudewatch.ui.components.composites.session_row import build_session_row


def _find_all(view: NSView, cls: type) -> list:
    found = []
    for sub in view.subviews():
        if isinstance(sub, cls):
            found.append(sub)
        found.extend(_find_all(sub, cls))
    return found


class TestSessionRow:
    def test_returns_view(self) -> None:
        view = build_session_row(
            project="myproject",
            cwd="/tmp/myproject",
            model="o4.6",
            ended_at="2026-03-27T12:00:00",
            bookmarked=False,
            width=400,
            height=54,
        )
        assert isinstance(view, NSView)

    def test_has_bookmark_button(self) -> None:
        view = build_session_row(
            project="myproject",
            cwd="/tmp/myproject",
            model="o4.6",
            ended_at="",
            bookmarked=True,
            width=400,
            height=54,
        )
        buttons = _find_all(view, NSButton)
        assert len(buttons) >= 1

    def test_unbookmarked_has_button(self) -> None:
        view = build_session_row(
            project="myproject",
            cwd="/tmp/myproject",
            model="",
            ended_at="",
            bookmarked=False,
            width=400,
            height=54,
        )
        buttons = _find_all(view, NSButton)
        assert len(buttons) >= 1

    def test_with_summary(self) -> None:
        view = build_session_row(
            project="myproject",
            cwd="/tmp/myproject",
            model="o4.6",
            ended_at="2026-03-27",
            bookmarked=False,
            width=400,
            height=54,
            summary_title="Fixing the login bug",
        )
        assert view is not None

    def test_with_token_info(self) -> None:
        view = build_session_row(
            project="myproject",
            cwd="/tmp/myproject",
            model="o4.6",
            ended_at="2026-03-27",
            bookmarked=False,
            width=400,
            height=54,
            token_compact="45K in · 200K out",  # noqa: S106
        )
        assert view is not None

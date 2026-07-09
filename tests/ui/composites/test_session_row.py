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


def _label_texts(view: NSView) -> list[str]:
    return [str(v.stringValue()) for v in view.subviews() if hasattr(v, "stringValue") and str(v.stringValue())]


class TestSessionRowMetaLine:
    """The meta line renders the caller's display-ready values verbatim."""

    def test_relative_time_shown_without_leading_separator(self) -> None:
        # Regression: short relative times ('2h ago') were blanked by a
        # date reformatter, leaving every meta line with a leading '·'.
        view = build_session_row(
            project="myproject",
            model="fable 5",
            ended_at="2h ago",
            token_compact="5K in · 3K out",  # noqa: S106
            width=400,
            height=60,
        )
        meta = next(t for t in _label_texts(view) if "fable 5" in t)
        assert meta == "2h ago · fable 5 · 5K in · 3K out"

    def test_time_only_row_still_shows_meta(self) -> None:
        view = build_session_row(project="myproject", ended_at="Yesterday", width=400, height=60)
        assert "Yesterday" in _label_texts(view)

    def test_no_meta_line_when_everything_empty(self) -> None:
        view = build_session_row(project="myproject", width=400, height=60)
        assert not any("·" in t for t in _label_texts(view))

    def test_stale_row_notes_missing_logs(self) -> None:
        view = build_session_row(project="myproject", ended_at="3d ago", stale=True, width=400, height=60)
        meta = next(t for t in _label_texts(view) if "3d ago" in t)
        assert meta == "3d ago · logs removed"

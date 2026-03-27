"""About pane — version info and dynamic changelog."""

from __future__ import annotations

import threading

import objc
from AppKit import NSButton, NSColor, NSFont, NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch import __version__
from claudewatch.backend.updates.dependencies import get_update_service
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, create_pane_stack
from claudewatch.ui.safety import dispatch_to_main_thread

_PAD = 24


def build_about_pane(delegate: object, w: float, h: float) -> NSView:  # noqa: PLR0915
    """Build the About pane with version, buttons, and changelog."""
    card_w = w - CONTENT_PADDING * 2
    stack = create_pane_stack("About", w)

    # Version + buttons row
    version_label = label(f"ClaudeWatch v{__version__}", size=14.0, bold=True)
    stack.add(version_label, height=18)

    button_row = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 24))
    audit_log_button = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 24))
    audit_log_button.setTitle_("Audit Log")
    audit_log_button.setBezelStyle_(1)
    audit_log_button.setFont_(NSFont.systemFontOfSize_(11.0))
    audit_log_button.setTarget_(delegate)
    audit_log_button.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    button_row.addSubview_(audit_log_button)

    github_button = NSButton.alloc().initWithFrame_(NSMakeRect(108, 0, 80, 24))
    github_button.setTitle_("GitHub")
    github_button.setBezelStyle_(1)
    github_button.setFont_(NSFont.systemFontOfSize_(11.0))
    github_button.setTarget_(delegate)
    github_button.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    button_row.addSubview_(github_button)
    stack.add(button_row, height=24)

    # Changelog header
    stack.gap(8)
    changelog_header = label("WHAT'S NEW", size=10.0, color=NSColor.tertiaryLabelColor())
    stack.add(changelog_header, height=14)

    # Changelog scroll area — fills remaining space
    # Calculate remaining height after stack content so far
    changelog_h = h - stack.content_height - 20
    changelog_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, changelog_h))
    changelog_scroll.setHasVerticalScroller_(True)
    changelog_scroll.setAutohidesScrollers_(True)
    changelog_scroll.setDrawsBackground_(False)

    loading_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, changelog_h))
    loading_label = secondary_label("Loading changelog...", size=11.0)
    loading_label.setFrame_(NSMakeRect(10, changelog_h // 2, card_w - 20, 18))
    loading_view.addSubview_(loading_label)
    changelog_scroll.setDocumentView_(loading_view)
    stack.add(changelog_scroll, height=changelog_h)

    # Fetch in background, build views on main thread
    def _fetch() -> None:
        releases = get_update_service().fetch_changelog()
        changelog: list[tuple[str, list[str]]] = []
        for tag, body in releases:
            items = _parse_notes(body)
            if items:
                changelog.append((tag, items))
            elif body:
                changelog.append((tag, [body[:100]]))
            else:
                changelog.append((tag, ["No release notes"]))

        def _render() -> None:
            from claudewatch.ui.components.composites.changelog import build_changelog

            inner = build_changelog(releases=changelog, width=card_w, height=changelog_h)
            changelog_scroll.setDocumentView_(inner)

        dispatch_to_main_thread(_render)

    threading.Thread(target=_fetch, daemon=True).start()

    return stack.to_view(min_height=h)


def _parse_notes(body: str) -> list[str]:
    """Extract bullet points from GitHub release notes markdown."""
    items = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("* ", "- ", "\u2022 ")):
            text = stripped.lstrip("*-\u2022 ").strip()
            if not text:
                continue
            by_idx = text.find(" by @")
            if by_idx > 0:
                text = text[:by_idx]
            if text.startswith(("**Full Changelog", "Full Changelog", "## ")):
                continue
            if text:
                items.append(text)
    return items

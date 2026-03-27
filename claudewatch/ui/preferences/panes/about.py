"""About pane — version info and dynamic changelog."""

from __future__ import annotations

import threading

import objc
from AppKit import NSButton, NSFont, NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch import __version__
from claudewatch.backend.updates.dependencies import get_update_service
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, pane_title, secondary_label
from claudewatch.ui.safety import dispatch_to_main_thread

_PAD = 24
_CARD_PAD = 16
_REPO_URL = "https://github.com/wingatethomas/claudewatch"


def build_about_pane(delegate: object, w: float, h: float) -> NSView:  # noqa: PLR0915
    """Build the About pane with version, buttons, and changelog."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    card_w = w - _PAD * 2

    y = h - 12 - 24
    title = pane_title("About")
    title.setFrame_(NSMakeRect(_PAD, y, w - _PAD * 2, 24))
    view.addSubview_(title)
    y -= 8

    # Version card
    version_card_h = 80
    version_card = card(card_w, version_card_h)
    version_card.setFrame_(NSMakeRect(_PAD, y - version_card_h, card_w, version_card_h))
    view.addSubview_(version_card)
    version_content = version_card.contentView()

    version_label = label(f"ClaudeWatch v{__version__}", size=14.0, bold=True)
    version_label.setFrame_(NSMakeRect(_CARD_PAD, version_card_h - _CARD_PAD - 18, 300, 18))
    version_content.addSubview_(version_label)

    button_y = _CARD_PAD
    audit_log_button = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, button_y, 100, 24))
    audit_log_button.setTitle_("Audit Log")
    audit_log_button.setBezelStyle_(1)
    audit_log_button.setFont_(NSFont.systemFontOfSize_(11.0))
    audit_log_button.setTarget_(delegate)
    audit_log_button.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    version_content.addSubview_(audit_log_button)

    github_button = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD + 108, button_y, 80, 24))
    github_button.setTitle_("GitHub")
    github_button.setBezelStyle_(1)
    github_button.setFont_(NSFont.systemFontOfSize_(11.0))
    github_button.setTarget_(delegate)
    github_button.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    version_content.addSubview_(github_button)

    y -= version_card_h + 24

    # Changelog
    y -= 12
    from AppKit import NSColor

    changelog_header = secondary_label("WHAT'S NEW", size=10.0)
    changelog_header.setTextColor_(NSColor.tertiaryLabelColor())
    changelog_header.setFrame_(NSMakeRect(_PAD, y, 200, 14))
    view.addSubview_(changelog_header)
    y -= 6

    changelog_card_h = y - 20
    changelog_card = card(card_w, changelog_card_h)
    changelog_card.setFrame_(NSMakeRect(_PAD, y - changelog_card_h, card_w, changelog_card_h))
    changelog_card.setWantsLayer_(True)
    changelog_card.layer().setMasksToBounds_(True)
    view.addSubview_(changelog_card)

    changelog_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, changelog_card_h))
    changelog_scroll.setHasVerticalScroller_(True)
    changelog_scroll.setAutohidesScrollers_(True)
    changelog_scroll.setDrawsBackground_(False)

    # Loading placeholder
    loading_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, changelog_card_h))
    loading_label = secondary_label("Loading changelog...", size=11.0)
    loading_label.setFrame_(NSMakeRect(10, changelog_card_h // 2, card_w - 20, 18))
    loading_view.addSubview_(loading_label)
    changelog_scroll.setDocumentView_(loading_view)
    changelog_card.contentView().addSubview_(changelog_scroll)

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

            inner = build_changelog(releases=changelog, width=card_w, height=changelog_card_h)
            changelog_scroll.setDocumentView_(inner)

        dispatch_to_main_thread(_render)

    threading.Thread(target=_fetch, daemon=True).start()

    return view


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

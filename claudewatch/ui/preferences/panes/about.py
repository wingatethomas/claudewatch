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
    ver_card_h = 80
    vc = card(card_w, ver_card_h)
    vc.setFrame_(NSMakeRect(_PAD, y - ver_card_h, card_w, ver_card_h))
    view.addSubview_(vc)
    vcc = vc.contentView()

    ver_lbl = label(f"ClaudeWatch v{__version__}", size=14.0, bold=True)
    ver_lbl.setFrame_(NSMakeRect(_CARD_PAD, ver_card_h - _CARD_PAD - 18, 300, 18))
    vcc.addSubview_(ver_lbl)

    btn_y = _CARD_PAD
    log_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD, btn_y, 100, 24))
    log_btn.setTitle_("Audit Log")
    log_btn.setBezelStyle_(1)
    log_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    log_btn.setTarget_(delegate)
    log_btn.setAction_(objc.selector(delegate.viewAuditLog_, signature=b"v@:@"))
    vcc.addSubview_(log_btn)

    repo_btn = NSButton.alloc().initWithFrame_(NSMakeRect(_CARD_PAD + 108, btn_y, 80, 24))
    repo_btn.setTitle_("GitHub")
    repo_btn.setBezelStyle_(1)
    repo_btn.setFont_(NSFont.systemFontOfSize_(11.0))
    repo_btn.setTarget_(delegate)
    repo_btn.setAction_(objc.selector(delegate.openRepo_, signature=b"v@:@"))
    vcc.addSubview_(repo_btn)

    y -= ver_card_h + 24

    # Changelog
    y -= 12
    cl_header = secondary_label("WHAT'S NEW", size=10.0)
    from AppKit import NSColor

    cl_header.setTextColor_(NSColor.tertiaryLabelColor())
    cl_header.setFrame_(NSMakeRect(_PAD, y, 200, 14))
    view.addSubview_(cl_header)
    y -= 6

    cl_card_h = y - 20
    cl_card = card(card_w, cl_card_h)
    cl_card.setFrame_(NSMakeRect(_PAD, y - cl_card_h, card_w, cl_card_h))
    cl_card.setWantsLayer_(True)
    cl_card.layer().setMasksToBounds_(True)
    view.addSubview_(cl_card)

    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, cl_card_h))
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    scroll.setDrawsBackground_(False)

    # Loading placeholder
    loading = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, card_w, cl_card_h))
    loading_lbl = secondary_label("Loading changelog...", size=11.0)
    loading_lbl.setFrame_(NSMakeRect(10, cl_card_h // 2, card_w - 20, 18))
    loading.addSubview_(loading_lbl)
    scroll.setDocumentView_(loading)
    cl_card.contentView().addSubview_(scroll)

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

            inner = build_changelog(releases=changelog, width=card_w, height=cl_card_h)
            scroll.setDocumentView_(inner)

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

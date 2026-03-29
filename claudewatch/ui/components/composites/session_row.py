"""SessionRow composite — renders a single session history row.

Presentational only — receives data + optional callbacks, never imports services.
"""

from __future__ import annotations

from AppKit import NSButton, NSFont, NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.icons import sf_icon
from claudewatch.ui.theme import theme

_BOOKMARK_COL = Spacing.XL
_NAME_COL = _BOOKMARK_COL + 18
_SCROLLBAR_W = 15


def build_session_row(  # noqa: PLR0913
    *,
    project: str,
    cwd: str = "",  # noqa: ARG001
    model: str = "",
    ended_at: str = "",
    bookmarked: bool = False,
    width: float,
    height: float,
    summary_title: str = "",
    token_compact: str = "",
    # Optional callbacks — if None, elements are non-interactive
    on_bookmark_toggle: object | None = None,
    on_menu_click: object | None = None,
    bookmark_represented_object: str = "",
    menu: object | None = None,
    delegate: object | None = None,
) -> NSView:
    """Build a single session row. Pure presentational."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    usable_w = width - _SCROLLBAR_W

    # Line 1: bookmark icon + project name + ··· menu
    name_y = height - 20

    # Bookmark toggle button
    bookmark_icon_name = "bookmark.fill" if bookmarked else "bookmark"
    bookmark_icon = sf_icon(bookmark_icon_name, size=11.0)
    if bookmark_icon:
        bookmark_button = NSButton.alloc().initWithFrame_(NSMakeRect(_BOOKMARK_COL, name_y - 1, 18, 18))
        bookmark_button.setImage_(bookmark_icon)
        bookmark_button.setBordered_(False)
        if delegate and on_bookmark_toggle:
            bookmark_button.setTarget_(delegate)
            bookmark_button.setAction_(on_bookmark_toggle)
            if bookmark_represented_object:
                bookmark_button.cell().setRepresentedObject_(bookmark_represented_object)
        view.addSubview_(bookmark_button)

    # Project name
    project_label = label(project, size=Font.BODY, bold=True)
    project_label.setFrame_(NSMakeRect(_NAME_COL, name_y, usable_w - _NAME_COL - 30, 18))
    view.addSubview_(project_label)

    # Context menu button (···)
    if menu:
        menu_button = NSButton.alloc().initWithFrame_(NSMakeRect(usable_w - 30, name_y, 22, 18))
        menu_button.setTitle_("···")
        menu_button.setBezelStyle_(0)
        menu_button.setBordered_(False)
        menu_button.setFont_(NSFont.boldSystemFontOfSize_(Font.SMALL))
        menu_button.setMenu_(menu)
        if delegate and on_menu_click:
            menu_button.setTarget_(delegate)
            menu_button.setAction_(on_menu_click)
        view.addSubview_(menu_button)

    # Line 2: meta (time · model · tokens)
    meta_y = name_y - 17
    meta_parts = []
    if ended_at:
        meta_parts.append(_format_date(ended_at))
    if model:
        meta_parts.append(model)
    if token_compact:
        meta_parts.append(token_compact)
    if meta_parts:
        meta_text = " · ".join(meta_parts)
        meta_label = secondary_label(meta_text, size=Font.SMALL)
        meta_label.setFrame_(NSMakeRect(_NAME_COL, meta_y, usable_w - _NAME_COL - 10, 14))
        view.addSubview_(meta_label)

    # Line 3: summary one-liner
    if summary_title:
        summary_y = meta_y - 16
        summary_label = label(summary_title[:50], size=Font.SMALL, color=theme.tertiary)
        summary_label.setFrame_(NSMakeRect(_NAME_COL, summary_y, usable_w - _NAME_COL - 10, 14))
        view.addSubview_(summary_label)

    return view


def _format_date(ended_at: str) -> str:
    """Pass through the display date. Caller provides either relative time or formatted date."""
    return ended_at or ""

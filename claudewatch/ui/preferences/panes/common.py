"""Shared base class and constants for preference panes.

All panes inherit from BasePane, which provides consistent header layout
and the standard interface that window.py calls.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from AppKit import NSView
from Foundation import NSMakeRect

from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.labels import pane_title, secondary_label
from claudewatch.ui.theme import theme

log = logging.getLogger("claudewatch")

# Standard pane layout — derived from design tokens
PANE_PADDING = Spacing.MD  # 12 — top/bottom padding inside pane
PANE_SPACING = Spacing.SM  # 8 — gap between header and content
CONTENT_PADDING = Spacing.XL  # 24 — horizontal padding for content

# Title height (fixed)
_TITLE_H = 24


class BasePane(ABC):
    """Base class for all preference panes.

    Subclass and implement `title`, `subtitle` (optional), and `build_content`.
    The base class handles header rendering and consistent layout.

    Usage in window.py::

        pane = SettingsPane(delegate, width, height)
        view = pane.build()
    """

    def __init__(self, delegate: object, width: float, height: float) -> None:
        self.delegate = delegate
        self.width = width
        self.height = height

    @property
    @abstractmethod
    def title(self) -> str:
        """Pane header title."""

    @property
    def subtitle(self) -> str:
        """Optional subtitle below the title. Override to provide one."""
        return ""

    def build(self) -> NSView:
        """Build the complete pane view with header + content."""
        view, content_top = self._build_header()
        try:
            self.build_content(view, content_top)
        except Exception:
            log.exception("pane '%s' failed to build", self.title)
            err = secondary_label(
                f"Failed to load {self.title}. Check the audit log for details.",
                size=Font.SECONDARY,
            )
            err.setTextColor_(theme.danger)
            err.setFrame_(NSMakeRect(CONTENT_PADDING, content_top - 30, self.card_width, 18))
            view.addSubview_(err)
        return view

    @abstractmethod
    def build_content(self, view: NSView, content_top: float) -> None:
        """Build pane content below the header. Subclasses implement this."""

    def _build_header(self) -> tuple[NSView, float]:
        """Build the standard pane header. Returns (view, content_top_y)."""
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, self.height))
        header_y = self.height - PANE_PADDING - _TITLE_H
        title_label = pane_title(self.title)
        title_label.setFrame_(NSMakeRect(CONTENT_PADDING, header_y, self.width - CONTENT_PADDING * 2, _TITLE_H))
        view.addSubview_(title_label)

        content_y = header_y - PANE_SPACING
        if self.subtitle:
            _sub_h = 14
            content_y -= _sub_h
            sub = secondary_label(self.subtitle, size=Font.SMALL)
            sub.setTextColor_(theme.tertiary)
            sub.setFrame_(NSMakeRect(CONTENT_PADDING, content_y, self.width - CONTENT_PADDING * 2, _sub_h))
            view.addSubview_(sub)
            content_y -= PANE_SPACING

        return view, content_y

    @property
    def card_width(self) -> float:
        """Width available for cards inside the pane."""
        return self.width - CONTENT_PADDING * 2

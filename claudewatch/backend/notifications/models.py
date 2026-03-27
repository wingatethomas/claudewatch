"""Typed models for notification-internal data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrontmostWindow:
    """The frontmost macOS window."""

    app_name: str
    window_title: str

"""Typed models for summary cache entries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SummaryEntry:
    """Cached summary for a CWD."""

    title: str
    summary: str
    mtime: float

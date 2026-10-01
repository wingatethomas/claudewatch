"""Session filter model — hides menu rows in place so the open menu never rebuilds."""

from __future__ import annotations

from dataclasses import dataclass, field

from AppKit import NSMenuItem


def build_haystack(project: str, task_summary: str, summary: str | None) -> str:
    """Join the searchable text for one session, lowercased."""
    parts = [project, task_summary, summary or ""]
    return " ".join(part for part in parts if part).lower()


def matches_query(query: str, haystack: str) -> bool:
    """Case-insensitive substring match; an empty query matches everything."""
    trimmed = query.strip().lower()
    return not trimmed or trimmed in haystack


@dataclass
class FilterRow:
    item: NSMenuItem
    detail_item: NSMenuItem | None
    haystack: str


@dataclass
class FilterSection:
    header: NSMenuItem
    rows: list[FilterRow] = field(default_factory=list)
    trailing_separator: NSMenuItem | None = None
    leading_separator: NSMenuItem | None = None
    only_when_searching: bool = False


def apply_filter(sections: list[FilterSection], no_match_item: NSMenuItem | None, query: str) -> None:
    """Show/hide session rows, headers, and separators to match the query."""
    searching = bool(query.strip())
    section_visible: list[bool] = []
    for section in sections:
        any_visible = False
        for row in section.rows:
            hidden = (section.only_when_searching and not searching) or not matches_query(query, row.haystack)
            row.item.setHidden_(hidden)
            if row.detail_item is not None:
                row.detail_item.setHidden_(hidden)
            any_visible = any_visible or not hidden
        section.header.setHidden_(not any_visible)
        section_visible.append(any_visible)

    def _regular_visible(indices: range) -> bool:
        return any(section_visible[i] for i in indices if not sections[i].only_when_searching)

    for index, section in enumerate(sections):
        if section.trailing_separator is not None:
            later_visible = _regular_visible(range(index + 1, len(sections)))
            section.trailing_separator.setHidden_(not (section_visible[index] and later_visible))
        if section.leading_separator is not None:
            earlier_visible = _regular_visible(range(index))
            section.leading_separator.setHidden_(not (section_visible[index] and earlier_visible))

    if no_match_item is not None:
        show_no_match = searching and bool(sections) and not any(section_visible)
        no_match_item.setHidden_(not show_no_match)

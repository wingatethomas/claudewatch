"""Tests for the session menu filter model."""

from AppKit import NSMenuItem

from claudewatch.ui.menu.filtering import (
    FilterRow,
    FilterSection,
    apply_filter,
    build_haystack,
    matches_query,
)


def _item(title: str = "") -> NSMenuItem:
    return NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")


def _row(haystack: str, *, with_detail: bool = True) -> FilterRow:
    return FilterRow(item=_item(), detail_item=_item() if with_detail else None, haystack=haystack)


class TestMatchesQuery:
    def test_empty_query_matches_all(self) -> None:
        assert matches_query("", "anything")
        assert matches_query("   ", "anything")

    def test_case_insensitive(self) -> None:
        assert matches_query("PARSER", "fix the parser")
        assert matches_query("Parser", "FIX THE PARSER".lower())

    def test_substring(self) -> None:
        assert matches_query("pars", "fix the parser")

    def test_non_match(self) -> None:
        assert not matches_query("docs", "fix the parser")

    def test_query_whitespace_stripped(self) -> None:
        assert matches_query("  parser  ", "fix the parser")


class TestBuildHaystack:
    def test_includes_all_parts(self) -> None:
        haystack = build_haystack("alpha", "fix parser", "rewrote tokenizer")
        assert "alpha" in haystack
        assert "fix parser" in haystack
        assert "rewrote tokenizer" in haystack

    def test_none_summary(self) -> None:
        assert build_haystack("alpha", "fix parser", None) == "alpha fix parser"

    def test_lowercased(self) -> None:
        assert build_haystack("Alpha", "Fix Parser", "Tokenizer") == "alpha fix parser tokenizer"

    def test_empty_parts_skipped(self) -> None:
        assert build_haystack("alpha", "", None) == "alpha"


class TestApplyFilter:
    def test_empty_query_shows_everything(self) -> None:
        section = FilterSection(header=_item(), rows=[_row("alpha fix parser"), _row("beta write docs")])
        no_match = _item()
        no_match.setHidden_(True)
        apply_filter([section], no_match, "")
        assert not section.header.isHidden()
        assert all(not r.item.isHidden() for r in section.rows)
        assert no_match.isHidden()

    def test_partial_match_hides_non_matching_row_and_detail(self) -> None:
        matching = _row("alpha fix parser")
        other = _row("beta write docs")
        section = FilterSection(header=_item(), rows=[matching, other])
        apply_filter([section], None, "parser")
        assert not matching.item.isHidden()
        assert not matching.detail_item.isHidden()
        assert other.item.isHidden()
        assert other.detail_item.isHidden()
        assert not section.header.isHidden()

    def test_matches_summary_text(self) -> None:
        row = _row(build_haystack("alpha", "fix parser", "rewrote the tokenizer"))
        section = FilterSection(header=_item(), rows=[row])
        apply_filter([section], None, "tokenizer")
        assert not row.item.isHidden()

    def test_fully_hidden_section_hides_header_and_separator(self) -> None:
        separator = NSMenuItem.separatorItem()
        hidden_section = FilterSection(header=_item(), rows=[_row("beta docs")], trailing_separator=separator)
        visible_section = FilterSection(header=_item(), rows=[_row("alpha parser")])
        apply_filter([hidden_section, visible_section], None, "parser")
        assert hidden_section.header.isHidden()
        assert separator.isHidden()
        assert not visible_section.header.isHidden()

    def test_separator_hidden_when_no_later_section_visible(self) -> None:
        separator = NSMenuItem.separatorItem()
        first = FilterSection(header=_item(), rows=[_row("alpha parser")], trailing_separator=separator)
        second = FilterSection(header=_item(), rows=[_row("beta docs")])
        apply_filter([first, second], None, "parser")
        assert not first.header.isHidden()
        assert second.header.isHidden()
        assert separator.isHidden()

    def test_separator_visible_between_visible_sections(self) -> None:
        separator = NSMenuItem.separatorItem()
        first = FilterSection(header=_item(), rows=[_row("alpha parser")], trailing_separator=separator)
        second = FilterSection(header=_item(), rows=[_row("parser two")])
        apply_filter([first, second], None, "parser")
        assert not separator.isHidden()

    def test_no_match_item_shown_when_all_hidden(self) -> None:
        section = FilterSection(header=_item(), rows=[_row("alpha parser")])
        no_match = _item()
        no_match.setHidden_(True)
        apply_filter([section], no_match, "zzz")
        assert section.header.isHidden()
        assert no_match.isHidden() is False

    def test_no_match_item_hidden_without_query(self) -> None:
        section = FilterSection(header=_item(), rows=[_row("alpha parser")])
        no_match = _item()
        apply_filter([section], no_match, "")
        assert no_match.isHidden()

    def test_reapply_empty_query_restores(self) -> None:
        rows = [_row("alpha parser"), _row("beta docs")]
        section = FilterSection(header=_item(), rows=rows)
        no_match = _item()
        apply_filter([section], no_match, "zzz")
        apply_filter([section], no_match, "")
        assert not section.header.isHidden()
        assert all(not r.item.isHidden() for r in rows)
        assert all(not r.detail_item.isHidden() for r in rows)
        assert no_match.isHidden()

    def test_row_without_detail_item(self) -> None:
        row = _row("alpha parser", with_detail=False)
        section = FilterSection(header=_item(), rows=[row])
        apply_filter([section], None, "docs")
        assert row.item.isHidden()

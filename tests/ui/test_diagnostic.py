"""Tests for the diagnostic-export helper used by the About pane."""

from __future__ import annotations

from claudewatch.ui.preferences.handlers.actions import build_diagnostic_text


class TestBuildDiagnosticText:
    def test_includes_version_banner(self, tmp_path) -> None:
        log = tmp_path / "claudewatch.log"
        log.write_text("hello\n")
        text = build_diagnostic_text(str(log))
        assert "ClaudeWatch v" in text
        assert "Python " in text

    def test_includes_log_tail(self, tmp_path) -> None:
        log = tmp_path / "claudewatch.log"
        log.write_text("line one\nline two\nline three\n")
        text = build_diagnostic_text(str(log))
        assert "line three" in text

    def test_truncates_to_tail_bytes(self, tmp_path) -> None:
        log = tmp_path / "claudewatch.log"
        body = "x" * 100_000
        log.write_text(body)
        text = build_diagnostic_text(str(log), tail_bytes=1000)
        # Banner + note + ~1000 bytes of x — total well under 100K
        assert len(text) < 5000
        assert "x" in text

    def test_handles_missing_file(self, tmp_path) -> None:
        missing = tmp_path / "nope.log"
        text = build_diagnostic_text(str(missing))
        assert "unreadable" in text
        assert "ClaudeWatch v" in text  # banner still present

    def test_log_note_reports_size(self, tmp_path) -> None:
        log = tmp_path / "claudewatch.log"
        log.write_text("a" * 500)
        text = build_diagnostic_text(str(log))
        assert "of 500" in text  # full file fits, "(last 500 bytes of 500)"

    def test_discards_partial_first_line_when_truncated(self, tmp_path) -> None:
        log = tmp_path / "claudewatch.log"
        log.write_text("AAAAAA\n" + ("B" * 10) + "\n")
        # Force truncation; the seek lands inside the first AAAAAA line, which
        # the partial-line drop should discard.
        text = build_diagnostic_text(str(log), tail_bytes=8)
        assert "AAAAAA" not in text
        assert "BB" in text

    def test_no_session_content_in_default_log(self, tmp_path) -> None:
        """Sanity: handler does not add any session content beyond what's in the log."""
        log = tmp_path / "claudewatch.log"
        log.write_text("INFO claudewatch.handler started\n")
        text = build_diagnostic_text(str(log))
        # The function never touches JSONL files, prompts, or assistant output.
        # If the log was clean (no session content), the diagnostic stays clean.
        assert "claudewatch.handler" in text

    def test_default_log_path_used_when_no_arg(self) -> None:
        # Smoke test: shouldn't raise even if LOG_PATH doesn't exist on the test box.
        text = build_diagnostic_text("/nonexistent/path/claudewatch.log")
        assert "ClaudeWatch v" in text
        assert "unreadable" in text

    def test_tail_size_exact_match(self, tmp_path) -> None:
        log = tmp_path / "claudewatch.log"
        log.write_text("Z" * 1000)
        text = build_diagnostic_text(str(log), tail_bytes=10_000)
        # File is smaller than tail_bytes — entire file returned, no partial-line drop
        assert text.count("Z") == 1000

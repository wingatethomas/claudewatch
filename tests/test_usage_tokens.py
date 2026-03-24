"""Tests for token usage parsing and formatting in usage.py."""

import json
from unittest.mock import MagicMock, patch

from claudewatch.backend.services.usage import (
    UsageService,
    _fmt_tokens,
    _token_cache,
    format_tokens,
    format_tokens_breakdown,
    get_session_tokens,
)


def _make_service(
    find_most_recent: str | None = None,
    read_full: list[str] | None = None,
) -> UsageService:
    """Create a UsageService with a mocked SessionLogService."""
    mock_log = MagicMock()
    mock_log.find_most_recent.return_value = find_most_recent
    mock_log.read_full.return_value = read_full or []
    return UsageService(mock_log)


class TestFmtTokens:
    def test_millions(self):
        assert _fmt_tokens(1_500_000) == "1.5M"

    def test_thousands(self):
        assert _fmt_tokens(42_000) == "42K"

    def test_small(self):
        assert _fmt_tokens(500) == "500"

    def test_zero(self):
        assert _fmt_tokens(0) == "0"

    def test_exact_million(self):
        assert _fmt_tokens(1_000_000) == "1.0M"

    def test_exact_thousand(self):
        assert _fmt_tokens(1000) == "1K"


class TestFormatTokens:
    def test_normal(self):
        tokens = {"input": 10000, "output": 3000, "cache_create": 5000, "cache_read": 20000}
        result = format_tokens(tokens)
        assert "35K in" in result
        assert "3K out" in result

    def test_zeros(self):
        tokens = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
        assert format_tokens(tokens) == ""


class TestFormatTokensBreakdown:
    def test_full_breakdown(self):
        tokens = {"input": 5000, "output": 2000, "cache_create": 3000, "cache_read": 10000}
        lines = format_tokens_breakdown(tokens)
        assert any("Input" in ln for ln in lines)
        assert any("Output" in ln for ln in lines)
        assert any("Cache write" in ln for ln in lines)
        assert any("Cache read" in ln for ln in lines)
        assert any("Total" in ln for ln in lines)

    def test_no_cache(self):
        tokens = {"input": 5000, "output": 2000, "cache_create": 0, "cache_read": 0}
        lines = format_tokens_breakdown(tokens)
        assert not any("Cache" in ln for ln in lines)
        assert any("Total" in ln for ln in lines)

    def test_zeros(self):
        tokens = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
        assert format_tokens_breakdown(tokens) == []


class TestUsageServiceGetTokens:
    """Tests for UsageService.get_tokens."""

    def test_returns_empty_when_no_jsonl(self):
        svc = _make_service(find_most_recent=None)
        result = svc.get_tokens("/Users/dev/myapp")
        assert result == {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}

    def test_returns_empty_when_file_gone(self, tmp_path):
        svc = _make_service(find_most_recent=str(tmp_path / "gone.jsonl"))
        result = svc.get_tokens("/Users/dev/myapp")
        assert result == {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}

    def test_parses_usage_from_lines(self, tmp_path):
        # Need a real file for os.path.getmtime
        jsonl_file = tmp_path / "session.jsonl"
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 200,
                        "cache_read_input_tokens": 300,
                    }
                },
            }),
            json.dumps({
                "type": "assistant",
                "message": {"usage": {"input_tokens": 10, "output_tokens": 5}},
            }),
        ]
        jsonl_file.write_text("\n".join(lines) + "\n")

        svc = _make_service(find_most_recent=str(jsonl_file), read_full=lines)
        result = svc.get_tokens("/Users/dev/myapp")
        assert result["input"] == 110
        assert result["output"] == 55
        assert result["cache_create"] == 200
        assert result["cache_read"] == 300

    def test_caches_by_mtime(self, tmp_path):
        jsonl_file = tmp_path / "session.jsonl"
        line = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 42, "output_tokens": 10}}})
        jsonl_file.write_text(line + "\n")

        svc = _make_service(find_most_recent=str(jsonl_file), read_full=[line])
        r1 = svc.get_tokens("/Users/dev/myapp")
        r2 = svc.get_tokens("/Users/dev/myapp")
        assert r1 == r2
        assert r1["input"] == 42
        # read_full should only be called once (second call uses cache)
        assert svc._session_log_service.read_full.call_count == 1

    def test_skips_invalid_json(self, tmp_path):
        jsonl_file = tmp_path / "session.jsonl"
        lines = [
            "not json",
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5, "output_tokens": 3}}}),
        ]
        jsonl_file.write_text("\n".join(lines) + "\n")

        svc = _make_service(find_most_recent=str(jsonl_file), read_full=lines)
        result = svc.get_tokens("/Users/dev/myapp")
        assert result["input"] == 5

    def test_instance_cache_is_isolated(self, tmp_path):
        """Each UsageService instance has its own cache."""
        jsonl_file = tmp_path / "session.jsonl"
        line = json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 7, "output_tokens": 2}}})
        jsonl_file.write_text(line + "\n")

        svc1 = _make_service(find_most_recent=str(jsonl_file), read_full=[line])
        svc2 = _make_service(find_most_recent=str(jsonl_file), read_full=[line])
        svc1.get_tokens("/Users/dev/myapp")
        assert len(svc1._token_cache) == 1
        assert len(svc2._token_cache) == 0


class TestGetSessionTokens:
    """Tests for legacy get_session_tokens function."""

    def test_parses_usage_from_jsonl(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 200,
                        "cache_read_input_tokens": 300,
                    }
                },
            },
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                    }
                },
            },
        ]
        with open(jsonl, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        _token_cache.clear()

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_tokens("/Users/dev/myapp")
        assert result["input"] == 110
        assert result["output"] == 55
        assert result["cache_create"] == 200
        assert result["cache_read"] == 300

    def test_returns_empty_for_missing(self, tmp_path):
        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = get_session_tokens("/Users/dev/myapp")
        assert result == {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}

    def test_caches_by_mtime(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        jsonl.write_text(
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 42, "output_tokens": 10}}}) + "\n"
        )

        _token_cache.clear()

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            r1 = get_session_tokens("/Users/dev/myapp")
            r2 = get_session_tokens("/Users/dev/myapp")
        assert r1 == r2
        assert r1["input"] == 42

    def test_skips_invalid_json(self, tmp_path):
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write("not json\n")
            f.write(
                json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 5, "output_tokens": 3}}}) + "\n"
            )

        _token_cache.clear()

        with patch("claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")):
            result = get_session_tokens("/Users/dev/myapp")
        assert result["input"] == 5

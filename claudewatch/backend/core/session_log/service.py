"""SessionLogService — JSONL discovery, symlink validation, reading."""

from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log import jsonl


class SessionLogService(BaseService):
    """Wraps JSONL file operations for Claude Code session logs."""

    def find_most_recent(self, cwd: str) -> str | None:
        """Find the most recently modified JSONL file for a CWD.

        Returns the full path, or None if not found or symlink traversal detected.
        """
        return jsonl.find_most_recent_jsonl(cwd)

    def list_in_cwd(self, cwd: str) -> list[str]:
        """List all JSONL paths in a CWD's project dir, mtime descending."""
        return jsonl.list_jsonls_in_cwd(cwd)

    def read_ai_title(self, path: str) -> str:
        """Return the latest aiTitle recorded in a JSONL, or "" if none."""
        return jsonl.read_ai_title(path)

    def is_safe_path(self, path: str) -> bool:
        """Check that a JSONL path resolves to within CLAUDE_PROJECTS_DIR."""
        return jsonl.is_safe_jsonl_path(path)

    def read_tail(self, path: str, tail_bytes: int = 10240) -> str:
        """Read the last N bytes of a JSONL file as UTF-8 text."""
        return jsonl.read_jsonl_tail(path, tail_bytes=tail_bytes)

    def read_full(self, path: str) -> list[str]:
        """Read all lines from a JSONL file."""
        return jsonl.read_jsonl_full(path)

    def get_session_id(self, path: str) -> str:
        """Extract the session ID (UUID) from a JSONL filename."""
        return jsonl.get_session_id_from_path(path)

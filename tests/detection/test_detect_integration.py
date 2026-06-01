"""Integration tests for DetectionService.detect() — full orchestration.

These tests exercise the entire detect() flow with realistic inputs:
- Multiple PIDs with different TTYs and CWDs
- Real JSONL files on disk (for accurate mtime/age behavior)
- Mocked pgrep, libproc, and AppleScript

The goal is to catch regressions in the exact bugs fixed by PRs #194 and #195:
- Stale sessions ending on user message classified IDLE (not WORKING)
- Multiple sessions sharing a CWD each classified by their own window title
"""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.models import SessionStatus
from claudewatch.backend.core.process.models import ProcessInfo
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.service import DetectionService


def _write_jsonl(path: str, entries: list[dict], *, age_seconds: float = 0) -> None:
    """Write JSONL entries to a path, optionally backdating mtime."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    if age_seconds > 0:
        past = time.time() - age_seconds
        os.utime(path, (past, past))


def _cwd_to_proj_dir(projects_root: str, cwd: str) -> str:
    """Mirror cwd_to_proj_key: /Users/dev/myapp -> -Users-dev-myapp."""
    return os.path.join(projects_root, cwd.replace("/", "-"))


def _build_service(  # noqa: PLR0913
    projects_root: str,
    pids: list[int],
    *,
    pid_info: dict[int, ProcessInfo] | None = None,
    pid_cwds: dict[int, str] | None = None,
    child_pids: set[int] | None = None,
    terminal_titles: dict[str, tuple[str, int]] | None = None,
) -> DetectionService:
    """Build a DetectionService with mocked externals pointing at real tmp JSONLs."""
    process_service = MagicMock()
    process_service.get_info.return_value = pid_info or {}
    process_service.get_cwds.return_value = pid_cwds or {}
    process_service.get_child_pids.return_value = child_pids or set()
    process_service.get_single_info.return_value = None
    process_service.list_all.return_value = []

    session_log = SessionLogService()
    service = DetectionService(process_service, session_log)

    # Mock the terminal lookup to skip AppleScript entirely
    service._get_terminal_windows = MagicMock(return_value=terminal_titles or {})  # type: ignore[method-assign]

    # Patch CLAUDE_PROJECTS_DIR so find_most_recent / read_tail hit the tmp dir
    patcher = patch(
        "claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR",
        projects_root,
    )
    patcher.start()

    # Mock pgrep via subprocess
    pgrep_result = MagicMock()
    pgrep_result.stdout = "\n".join(str(p) for p in pids) + "\n"
    subprocess_patcher = patch(
        "claudewatch.backend.detection.service.subprocess.run",
        return_value=pgrep_result,
    )
    subprocess_patcher.start()

    # Store patchers so tests can stop them (though tmp_path teardown will clean up)
    service._test_patchers = [patcher, subprocess_patcher]  # type: ignore[attr-defined]
    return service


class TestDetectEmpty:
    def test_no_claude_processes(self, tmp_path):
        svc = _build_service(str(tmp_path), [])
        try:
            assert svc.detect() == []
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_excludes_child_pids(self, tmp_path):
        svc = _build_service(
            str(tmp_path),
            [100, 200, 300],
            pid_info={
                100: ProcessInfo(tty="ttys001", ppid=1, comm="claude"),
                300: ProcessInfo(tty="ttys003", ppid=1, comm="claude"),
            },
            pid_cwds={100: "/proj", 300: "/proj"},
            child_pids={200},  # 200 is excluded
        )
        try:
            sessions = svc.detect()
            pids = {s.pid for s in sessions}
            assert 200 not in pids
        finally:
            for p in svc._test_patchers:
                p.stop()


class TestDetectSingleSession:
    def test_idle_title_stale_jsonl(self, tmp_path):
        """Single session with ✳ title and 3-day-old JSONL → IDLE."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}],
            age_seconds=3 * 86400,
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — ✳ Claude Code", 1)},
        )
        try:
            sessions = svc.detect()
            assert len(sessions) == 1
            assert sessions[0].status == SessionStatus.IDLE
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_braille_title_trumps_stale_jsonl(self, tmp_path):
        """Active streaming (braille in title) is WORKING even if JSONL is old."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}],
            age_seconds=120,
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — ⠂ streaming", 1)},
        )
        try:
            sessions = svc.detect()
            assert len(sessions) == 1
            assert sessions[0].status == SessionStatus.WORKING
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_fresh_jsonl_is_working(self, tmp_path):
        """Fresh JSONL (< 5s) means actively streaming — WORKING."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}],
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — no indicator", 1)},
        )
        try:
            sessions = svc.detect()
            assert len(sessions) == 1
            assert sessions[0].status == SessionStatus.WORKING
        finally:
            for p in svc._test_patchers:
                p.stop()


class TestDetectStaleUserMessage:
    """Regression: PR #194 — stale JSONL ending on user message should be IDLE."""

    def test_stale_jsonl_last_user_message_is_idle(self, tmp_path):
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
                {"type": "user", "message": {"content": "follow up"}},
            ],
            age_seconds=3 * 86400,
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — other", 1)},  # no ✳ no braille
        )
        try:
            sessions = svc.detect()
            assert len(sessions) == 1
            # Title has no indicator, JSONL is 3 days old with last=user → IDLE
            assert sessions[0].status == SessionStatus.IDLE
        finally:
            for p in svc._test_patchers:
                p.stop()


class TestDetectSharedCwd:
    """Regression: PR #195 — sessions sharing a CWD classified by their own titles."""

    def test_three_sessions_one_working_two_idle(self, tmp_path):
        """One active session with fresh JSONL should not flip sibling IDLE titles to WORKING."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        # Only the fresh JSONL — it's the one find_most_recent will return
        _write_jsonl(
            os.path.join(proj_dir, "active.jsonl"),
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}],
        )
        svc = _build_service(
            str(tmp_path),
            [100, 200, 300],
            pid_info={
                100: ProcessInfo(tty="ttys001", ppid=1, comm="claude"),
                200: ProcessInfo(tty="ttys002", ppid=1, comm="claude"),
                300: ProcessInfo(tty="ttys003", ppid=1, comm="claude"),
            },
            pid_cwds={100: cwd, 200: cwd, 300: cwd},
            terminal_titles={
                "/dev/ttys001": ("myapp — ⠂ working", 1),  # braille = WORKING
                "/dev/ttys002": ("myapp — ✳ Claude Code", 2),  # ✳ = IDLE
                "/dev/ttys003": ("myapp — ✳ Claude Code", 3),  # ✳ = IDLE
            },
        )
        try:
            sessions = svc.detect()
            by_pid = {s.pid: s for s in sessions}
            assert by_pid[100].status == SessionStatus.WORKING
            assert by_pid[200].status == SessionStatus.IDLE
            assert by_pid[300].status == SessionStatus.IDLE
        finally:
            for p in svc._test_patchers:
                p.stop()


class TestDetectPendingTool:
    def test_pending_tool_use_is_attention(self, tmp_path):
        """Unresolved tool_use in JSONL + non-streaming title → ATTENTION."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf /"}}]},
                },
            ],
            age_seconds=30,
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — ✳ idle prompt", 1)},
        )
        try:
            sessions = svc.detect()
            assert len(sessions) == 1
            assert sessions[0].status == SessionStatus.ATTENTION
            assert "Bash" in sessions[0].prompt_text
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_resolved_tool_is_not_attention(self, tmp_path):
        """tool_use followed by tool_result → normal flow, not ATTENTION."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
                },
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "1", "content": "ok"}]},
                },
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
            ],
            age_seconds=120,
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — ✳ idle", 1)},
        )
        try:
            sessions = svc.detect()
            assert sessions[0].status == SessionStatus.IDLE
        finally:
            for p in svc._test_patchers:
                p.stop()


class TestDetectSharedCwdAttention:
    """Regression: shared-CWD ATTENTION must use each session's own JSONL.

    Bug: find_most_recent(cwd) returns the most recently modified JSONL in the
    project dir. When sibling sessions are actively streaming, the idle session
    waiting for tool approval reads the wrong file and never reaches ATTENTION.
    Fix matches each session to its own JSONL via the aiTitle in the window title.
    """

    def test_idle_session_with_pending_tool_gets_attention(self, tmp_path):
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)

        # Session A: actively streaming, fresh JSONL. Looks like the most-recent.
        _write_jsonl(
            os.path.join(proj_dir, "active.jsonl"),
            [
                {"type": "ai-title", "aiTitle": "Wire up search filter"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
            ],
        )
        # Session B: idle, JSONL has unresolved tool_use, older mtime.
        _write_jsonl(
            os.path.join(proj_dir, "pending.jsonl"),
            [
                {"type": "ai-title", "aiTitle": "Investigate stale cache"},
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "/x/README.md"}}]
                    },
                },
            ],
            age_seconds=30,
        )
        # Session C: idle, no pending tool, oldest mtime.
        _write_jsonl(
            os.path.join(proj_dir, "old.jsonl"),
            [
                {"type": "ai-title", "aiTitle": "Tidy log formatting"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
            ],
            age_seconds=300,
        )

        svc = _build_service(
            str(tmp_path),
            [100, 200, 300],
            pid_info={
                100: ProcessInfo(tty="ttys001", ppid=1, comm="claude"),
                200: ProcessInfo(tty="ttys002", ppid=1, comm="claude"),
                300: ProcessInfo(tty="ttys003", ppid=1, comm="claude"),
            },
            pid_cwds={100: cwd, 200: cwd, 300: cwd},
            terminal_titles={
                "/dev/ttys001": ("myapp — ⠂ Wire up search filter — node ◂ claude", 1),
                "/dev/ttys002": ("myapp — ✳ Investigate stale cache — node ◂ claude", 2),
                "/dev/ttys003": ("myapp — ✳ Tidy log formatting — node ◂ claude", 3),
            },
        )
        try:
            sessions = svc.detect()
            by_pid = {s.pid: s for s in sessions}
            assert by_pid[100].status == SessionStatus.WORKING
            assert by_pid[200].status == SessionStatus.ATTENTION
            assert "Write" in by_pid[200].prompt_text
            assert by_pid[300].status == SessionStatus.IDLE
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_brand_new_session_no_ai_title_falls_back(self, tmp_path):
        """Session with no aiTitle in window title falls back to most-recent JSONL."""
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]},
                },
            ],
            age_seconds=30,
        )
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": ("myapp — ✳ claude", 1)},
        )
        try:
            sessions = svc.detect()
            assert sessions[0].status == SessionStatus.ATTENTION
        finally:
            for p in svc._test_patchers:
                p.stop()


class TestDetectIdeSession:
    """IDE sessions have no title indicator — JSONL is the only signal."""

    def test_ide_pending_tool_is_attention(self, tmp_path):
        cwd = "/Users/dev/myapp"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(
            os.path.join(proj_dir, "s1.jsonl"),
            [
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/x"}}]},
                },
            ],
            age_seconds=30,
        )
        # No tty match for IDE — we set host_app via _detect_host_app which walks PPID.
        # Simpler: provide tty that matches IDE comm chain.
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={
                100: ProcessInfo(tty="ttys001", ppid=2, comm="claude"),
                2: ProcessInfo(tty="??", ppid=1, comm="code"),  # VSCode parent
            },
            pid_cwds={100: cwd},
            terminal_titles={},  # no terminal match — won't be TERMINAL host
        )
        try:
            sessions = svc.detect()
            # Session should be detected with a host app, pending tool → ATTENTION
            assert len(sessions) == 1
            assert sessions[0].status == SessionStatus.ATTENTION
        finally:
            for p in svc._test_patchers:
                p.stop()

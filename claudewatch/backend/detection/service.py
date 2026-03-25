import json
import logging
import os
import subprocess
import time

from claudewatch.backend.core.helpers import run_applescript
from claudewatch.backend.core.models import (
    ClaudeSession,
    HostApp,
    SessionStatus,
)
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.constants import HOST_PROCESS_NAMES, IDLE_INDICATOR, PROMPT_KEYWORDS

log = logging.getLogger("claudewatch")

# Module-level constants
_MAX_SESSIONS = 50
_TEXT_MAX_LEN = 80
_JSONL_MAX_AGE = 300  # 5 min — Claude can wait for approval a long time
_JSONL_MIN_AGE = 1
_WIN_SPLIT_FIELDS = 3
_TERMINAL_CACHE_TTL = 3  # seconds between AppleScript refreshes


class DetectionService(BaseService):
    """Finds running Claude Code processes and builds session objects.

    Dependencies are injected via constructor. Module-level caches from the
    old detection module are now instance state.
    """

    def __init__(
        self,
        process_service: ProcessService,
        session_log_service: SessionLogService,
    ) -> None:
        super().__init__()
        self._process_service = process_service
        self._session_log_service = session_log_service

        # PID -> HostApp cache (host app doesn't change for a session's lifetime)
        self._host_app_cache: dict[int, HostApp] = {}

        # Cached terminal window info to avoid expensive AppleScript every poll
        self._terminal_cache: dict[str, tuple[str, int]] | None = None
        self._terminal_cache_time: float = 0

    # -- Process info helpers -----------------------------------------------

    def _batch_ps_info(self, pids: list[int]) -> dict[int, dict]:
        """Get tty + ppid + comm for all PIDs via native libproc calls."""
        return self._process_service.get_info(pids)

    def _batch_lsof_cwds(self, pids: list[int]) -> dict[int, str]:
        """Get CWD for all PIDs via native libproc calls."""
        return self._process_service.get_cwds(pids)

    # -- Terminal window helpers --------------------------------------------

    def _get_terminal_windows(self) -> dict[str, tuple[str, int]]:
        """Get Terminal.app tab TTYs, window titles, and IDs.

        Cached for _TERMINAL_CACHE_TTL seconds to avoid expensive AppleScript on every poll.
        Returns {tty: (title, window_id)}.
        """
        now = time.time()
        if self._terminal_cache is not None and now - self._terminal_cache_time < _TERMINAL_CACHE_TTL:
            return self._terminal_cache

        result = run_applescript("""
        if application "Terminal" is running then
            tell application "Terminal"
                set output to ""
                repeat with w in windows
                    set wid to id of w
                    repeat with t in tabs of w
                        set output to output & (tty of t) & "|" & wid & "|" & (name of w) & linefeed
                    end repeat
                end repeat
                return output
            end tell
        end if
        return ""
        """)

        windows: dict[str, tuple[str, int]] = {}
        for line in result.splitlines():
            p = line.split("|", 2)
            if len(p) == _WIN_SPLIT_FIELDS and p[1].isdigit():
                windows[p[0]] = (p[2], int(p[1]))

        self._terminal_cache = windows
        self._terminal_cache_time = now
        return windows

    # -- Host app detection -------------------------------------------------

    def _detect_host_app(self, pid: int, all_ps: dict[int, dict]) -> HostApp:
        """Walk PPID chain to find the host app. Results are cached by PID."""
        if pid in self._host_app_cache:
            return self._host_app_cache[pid]

        current = pid
        for _ in range(20):
            info = all_ps.get(current)
            ppid = info["ppid"] if info else 0

            if not ppid:
                ppid = self._process_service.get_ppid(current)

            if ppid <= 1:
                break

            if ppid in all_ps:
                comm = os.path.basename(all_ps[ppid]["comm"])
            else:
                pinfo = self._process_service.get_single_info(ppid)
                if pinfo:
                    parent_ppid = pinfo["ppid"]
                    raw_comm = pinfo["comm"]
                else:
                    parent_ppid = 0
                    raw_comm = ""
                comm = os.path.basename(raw_comm)
                all_ps[ppid] = {"tty": "", "ppid": parent_ppid, "comm": raw_comm}

            comm_lower = comm.lower()
            if comm_lower.startswith("tmux"):
                self._host_app_cache[pid] = HostApp.TMUX
                return HostApp.TMUX
            for name, app in HOST_PROCESS_NAMES.items():
                if name in comm_lower:
                    self._host_app_cache[pid] = app
                    return app
            current = ppid

        self._host_app_cache[pid] = HostApp.OTHER
        return HostApp.OTHER

    # -- IDE tab indices ----------------------------------------------------

    def _get_ide_tab_indices(self, sessions: list[ClaudeSession], all_ps: dict[int, dict]) -> None:  # noqa: PLR0912
        """Map IDE terminal sessions to their tab indices using the process tree."""
        ide_sessions = [s for s in sessions if s.host_app in (HostApp.PYCHARM, HostApp.VSCODE)]
        if not ide_sessions:
            return

        ide_pids: set[int] = set()
        for s in ide_sessions:
            current = s.pid
            for _ in range(20):
                info = all_ps.get(current)
                ppid = info["ppid"] if info else 0
                if ppid <= 1:
                    break
                if ppid in all_ps:
                    comm = os.path.basename(all_ps[ppid]["comm"]).lower()
                else:
                    pinfo = self._process_service.get_single_info(ppid)
                    comm = os.path.basename(pinfo["comm"]).lower() if pinfo else ""
                if "pycharm" in comm or "idea" in comm or comm == "code" or "electron" in comm:
                    ide_pids.add(ppid)
                    break
                current = ppid

        if not ide_pids:
            return

        all_procs = self._process_service.list_all()
        shell_names = {"sh", "bash", "zsh", "fish", "dash", "tcsh", "ksh"}
        ide_shells: list[tuple[int, str]] = []
        for proc in all_procs:
            child_ppid = proc["ppid"]
            child_tty = proc["tty"]
            child_comm = os.path.basename(proc["comm"])
            if child_ppid in ide_pids and child_tty != "??" and child_comm in shell_names:
                ide_shells.append((proc["pid"], child_tty))

        ide_shells.sort(key=lambda x: x[0])
        tty_to_index = {tty: i for i, (_, tty) in enumerate(ide_shells)}

        for s in ide_sessions:
            s.tab_index = tty_to_index.get(s.tty)

    # -- JSONL status helpers -----------------------------------------------

    def _check_jsonl_for_idle(self, cwd: str) -> SessionStatus:
        """Determine idle/working status from JSONL."""
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return SessionStatus.WORKING

        _active_threshold = 5
        try:
            age = time.time() - os.path.getmtime(path)
            if age < _active_threshold:
                return SessionStatus.WORKING
        except OSError:
            pass

        tail = self._session_log_service.read_tail(path, tail_bytes=5120)
        if not tail:
            return SessionStatus.WORKING

        last_type = ""
        for line in tail.strip().splitlines():
            try:
                d = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            dtype = d.get("type", "")
            if dtype in ("user", "assistant"):
                last_type = dtype

        if last_type == "assistant":
            return SessionStatus.IDLE
        return SessionStatus.WORKING

    def _get_session_id(self, cwd: str) -> str:
        """Get the most recent session ID for a CWD from the JSONL filename."""
        path = self._session_log_service.find_most_recent(cwd)
        return self._session_log_service.get_session_id(path) if path else ""

    def _check_jsonl_for_pending_tool(self, cwd: str) -> tuple[bool, str, str]:  # noqa: PLR0911, PLR0912
        """Check if the most recent JSONL for this CWD has a pending tool_use."""
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return False, "", ""

        try:
            age = time.time() - os.path.getmtime(path)
            if age > _JSONL_MAX_AGE or age < _JSONL_MIN_AGE:
                return False, "", ""
        except OSError:
            return False, "", ""

        tail = self._session_log_service.read_tail(path)
        if not tail:
            return False, "", ""

        lines = tail.strip().splitlines()
        for line in reversed(lines[-20:]):
            try:
                d = json.loads(line)
                dtype = d.get("type")

                if dtype in ("system", "last-prompt", "pr-link", "queue-operation", "file-history-snapshot"):
                    continue

                if dtype == "user":
                    return False, "", ""

                if dtype == "assistant":
                    content = d.get("message", {}).get("content", [])
                    tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                    if tool_uses:
                        one_line, ctx = _format_tool_use(tool_uses[-1])
                        return True, one_line, ctx
                    return False, "", ""

                if dtype == "progress":
                    msg = d["data"]["message"]
                    if msg.get("type") == "user":
                        return False, "", ""
                    if msg.get("type") == "assistant":
                        content = msg.get("message", {}).get("content", [])
                        tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                        if tool_uses:
                            one_line, ctx = _format_tool_use(tool_uses[-1])
                            return True, one_line, ctx
                        return False, "", ""

            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return False, "", ""

    # -- Main detection entry point -----------------------------------------

    def detect(self) -> list[ClaudeSession]:  # noqa: PLR0912, PLR0915
        """Detect all running Claude Code sessions."""
        try:
            r = subprocess.run(  # noqa: S603, S607
                ["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=5, check=False,
            )
            pids_out = r.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pids_out = ""
        raw_pids = [int(p) for p in pids_out.splitlines() if p.strip().isdigit()]
        child_pids = self._process_service.get_child_pids()
        pids = [p for p in raw_pids if p not in child_pids][:_MAX_SESSIONS]
        log.debug("detect: found %d claude processes", len(pids))
        if not pids:
            self._host_app_cache.clear()
            return []

        all_ps = self._batch_ps_info(pids)
        cwds = self._batch_lsof_cwds(pids)
        terminal_windows: dict[str, tuple[str, int]] | None = None

        # Evict stale cache entries
        live_pids = set(pids)
        for stale in list(self._host_app_cache.keys()):
            if stale not in live_pids:
                del self._host_app_cache[stale]

        sessions = []
        for pid in pids:
            info = all_ps.get(pid)
            if not info:
                continue
            tty = info["tty"]
            if tty == "??":
                walk_pid = info["ppid"]
                for _ in range(5):
                    if walk_pid <= 1:
                        break
                    parent = self._process_service.get_single_info(walk_pid)
                    if not parent:
                        break
                    if parent["tty"] != "??":
                        tty = parent["tty"]
                        break
                    walk_pid = parent["ppid"]
            cwd = cwds.get(pid, "")
            project = os.path.basename(cwd) if cwd else ""
            if not project:
                continue

            host_app = self._detect_host_app(pid, all_ps)

            if (not tty or tty == "??") and host_app not in (HostApp.VSCODE, HostApp.PYCHARM):
                continue
            window_title = host_app.value
            window_id = None

            if host_app in (HostApp.TERMINAL, HostApp.TMUX, HostApp.OTHER):
                if terminal_windows is None:
                    terminal_windows = self._get_terminal_windows()
                window_title, window_id, host_app = _match_terminal_window(
                    tty,
                    project,
                    host_app,
                    terminal_windows,
                )

            status = _determine_status(window_title)

            sessions.append(
                ClaudeSession(
                    pid=pid,
                    tty=tty,
                    project=project,
                    cwd=cwd,
                    host_app=host_app,
                    window_title=window_title,
                    window_id=window_id,
                    status=status,
                    session_id=self._get_session_id(cwd),
                )
            )

        self._get_ide_tab_indices(sessions, all_ps)

        checked_cwds: set[str] = set()
        for s in sessions:
            if s.cwd and s.cwd not in checked_cwds:
                pending, one_line, context = self._check_jsonl_for_pending_tool(s.cwd)
                if pending:
                    s.status = SessionStatus.ATTENTION
                    s.prompt_text = one_line
                    s.prompt_context = context
                elif s.status != SessionStatus.IDLE:
                    s.status = self._check_jsonl_for_idle(s.cwd)
                checked_cwds.add(s.cwd)

        return sessions


# ── Module-level pure functions (no state, used by tests) ─────────────


def _extract_last_output(buffer: str) -> str:
    """Extract the last meaningful Claude output line from terminal buffer.
    Only looks for ⏺-prefixed lines (Claude's actual output)."""
    lines = buffer.splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("⏺"):
            text = stripped.lstrip("⏺").strip()
            if text:
                if len(text) > _TEXT_MAX_LEN:
                    text = text[:77] + "..."
                return text
    return ""


def _extract_prompt_info(buffer: str) -> tuple[str, str]:
    """Extract permission prompt context from the terminal buffer.
    Returns (one_line_summary, full_context) for menu and alert respectively."""
    lines = buffer.splitlines()
    prompt_line_idx = None

    for i in range(len(lines) - 1, -1, -1):
        lower = lines[i].strip().lower()
        if any(kw in lower for kw in PROMPT_KEYWORDS):
            prompt_line_idx = i
            break

    if prompt_line_idx is None:
        return "", ""

    block_start = prompt_line_idx
    one_line = ""
    for j in range(prompt_line_idx - 1, max(prompt_line_idx - 30, -1), -1):
        stripped = lines[j].strip()
        if stripped.startswith("⏺"):
            block_start = j
            one_line = stripped.lstrip("⏺").strip()
            break
        if stripped.startswith("─") or stripped.startswith("❯"):
            block_start = j + 1
            break

    context_lines = []
    for k in range(block_start, min(prompt_line_idx + 2, len(lines))):
        stripped = lines[k].strip()
        if stripped:
            context_lines.append(stripped)

    full_context = "\n".join(context_lines)

    if one_line and len(one_line) > _TEXT_MAX_LEN:
        one_line = one_line[:77] + "..."

    return one_line, full_context


def _format_tool_use(tool: dict) -> tuple[str, str]:
    """Format a tool_use block into (one_line, full_context)."""
    name = tool.get("name", "Unknown")
    inp = tool.get("input", {})
    one_line = name
    context_parts = [f"Tool: {name}"]
    if isinstance(inp, dict):
        if "command" in inp:
            one_line = f"{name}: {inp['command'][:60]}"
            context_parts.append(f"Command: {inp['command']}")
        elif "file_path" in inp:
            one_line = f"{name}: {os.path.basename(inp['file_path'])}"
            context_parts.append(f"File: {inp['file_path']}")
        elif "pattern" in inp:
            one_line = f"{name}: {inp['pattern'][:40]}"
            context_parts.append(f"Pattern: {inp['pattern']}")
    if len(one_line) > _TEXT_MAX_LEN:
        one_line = one_line[:77] + "..."
    return one_line, "\n".join(context_parts)


def _determine_status(window_title: str) -> SessionStatus:
    """Determine session status from window title indicators."""
    if IDLE_INDICATOR in window_title:
        return SessionStatus.IDLE
    return SessionStatus.WORKING


def _match_terminal_window(
    tty: str,
    project: str,
    host_app: HostApp,
    terminal_windows: dict[str, tuple[str, int]],
) -> tuple[str, int | None, HostApp]:
    """Try to match a session to a Terminal.app window by TTY or project name.
    Returns (window_title, window_id, possibly-updated host_app)."""
    full_tty = tty if tty.startswith("/dev/") else f"/dev/{tty}"

    if full_tty in terminal_windows:
        title, wid = terminal_windows[full_tty]
        if host_app == HostApp.OTHER:
            host_app = HostApp.TERMINAL
        return title, wid, host_app

    if host_app == HostApp.TMUX:
        for _, (tw_title, tw_wid) in terminal_windows.items():
            if project in tw_title:
                return tw_title, tw_wid, host_app

    return host_app.value, None, host_app

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
from claudewatch.backend.core.process.models import ProcessInfo
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.constants import HOST_PROCESS_NAMES, IDLE_INDICATOR
from claudewatch.backend.detection.models import PendingToolResult, TerminalMatch, ToolUseInfo

log = logging.getLogger("claudewatch")

# Module-level constants
_MAX_SESSIONS = 50
_TEXT_MAX_LEN = 80
_WIN_SPLIT_FIELDS = 3
_TERMINAL_CACHE_TTL = 3  # seconds between AppleScript refreshes
_JSONL_STREAMING_THRESHOLD = 5  # JSONL modified within this → actively streaming
_JSONL_IDLE_THRESHOLD = 60  # JSONL not modified within this → definitely idle


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

        # NOTE: These caches are NOT thread-safe. detect() must only be called
        # from the single-worker ThreadPoolExecutor in menubar.py. If detection
        # is ever parallelized, these need locks.
        self._host_app_cache: dict[int, HostApp] = {}
        self._terminal_cache: dict[str, tuple[str, int]] | None = None
        self._terminal_cache_time: float = 0

    # -- Process info helpers -----------------------------------------------

    def _batch_ps_info(self, pids: list[int]) -> dict[int, ProcessInfo]:
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

    def _detect_host_app(self, pid: int, all_ps: dict[int, ProcessInfo]) -> HostApp:
        """Walk PPID chain to find the host app. Results are cached by PID."""
        if pid in self._host_app_cache:
            return self._host_app_cache[pid]

        current = pid
        for _ in range(20):
            info = all_ps.get(current)
            ppid = info.ppid if info else 0

            if not ppid:
                ppid = self._process_service.get_ppid(current)

            if ppid <= 1:
                break

            if ppid in all_ps:
                comm = os.path.basename(all_ps[ppid].comm)
            else:
                pinfo = self._process_service.get_single_info(ppid)
                if pinfo:
                    parent_ppid = pinfo.ppid
                    raw_comm = pinfo.comm
                else:
                    parent_ppid = 0
                    raw_comm = ""
                comm = os.path.basename(raw_comm)
                all_ps[ppid] = ProcessInfo(tty="", ppid=parent_ppid, comm=raw_comm)

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

    def _get_ide_tab_indices(self, sessions: list[ClaudeSession], all_ps: dict[int, ProcessInfo]) -> None:  # noqa: PLR0912
        """Map IDE terminal sessions to their tab indices using the process tree."""
        ide_sessions = [s for s in sessions if s.host_app in (HostApp.PYCHARM, HostApp.VSCODE)]
        if not ide_sessions:
            return

        ide_pids: set[int] = set()
        for s in ide_sessions:
            current = s.pid
            for _ in range(20):
                info = all_ps.get(current)
                ppid = info.ppid if info else 0
                if ppid <= 1:
                    break
                if ppid in all_ps:
                    comm = os.path.basename(all_ps[ppid].comm).lower()
                else:
                    pinfo = self._process_service.get_single_info(ppid)
                    comm = os.path.basename(pinfo.comm).lower() if pinfo else ""
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
            child_ppid = proc.ppid
            child_tty = proc.tty
            child_comm = os.path.basename(proc.comm)
            if child_ppid in ide_pids and child_tty != "??" and child_comm in shell_names:
                ide_shells.append((proc.pid, child_tty))

        ide_shells.sort(key=lambda x: x[0])
        tty_to_index = {tty: i for i, (_, tty) in enumerate(ide_shells)}

        for s in ide_sessions:
            s.tab_index = tty_to_index.get(s.tty)

    # -- JSONL status helpers -----------------------------------------------

    def _read_jsonl_tail(self, jsonl_path: str | None) -> tuple[str, float]:
        """Read the JSONL tail and return (tail_text, age_seconds).

        Age is -1 when the file can't be stat'd. Shared by idle and
        pending-tool checks to avoid duplicate file reads.
        """
        if not jsonl_path:
            return ("", -1.0)
        try:
            age = time.time() - os.path.getmtime(jsonl_path)
        except OSError:
            age = -1.0
        tail = self._session_log_service.read_tail(jsonl_path)
        return (tail, age)

    def _check_jsonl_for_idle(self, tail: str) -> SessionStatus:
        """Determine idle/working status from a pre-read JSONL tail."""
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

    def _get_session_id(self, cwd: str, jsonl_path: str | None = None) -> str:
        """Get the most recent session ID for a CWD from the JSONL filename."""
        path = jsonl_path or self._session_log_service.find_most_recent(cwd)
        return self._session_log_service.get_session_id(path) if path else ""

    def _check_jsonl_for_pending_tool(self, tail: str) -> PendingToolResult:  # noqa: PLR0911, PLR0912
        """Check if a pre-read JSONL tail has a pending tool_use."""
        _empty = PendingToolResult(has_pending=False, one_line="", context="")
        if not tail:
            return _empty

        lines = tail.strip().splitlines()

        # Scan in reverse. Track whether we've seen a tool_result (user entry)
        # AFTER the most recent assistant tool_use. If yes, the tool completed.
        seen_tool_result = False

        for line in reversed(lines[-20:]):
            try:
                d = json.loads(line)
                dtype = d.get("type")

                if dtype in ("system", "last-prompt", "pr-link", "queue-operation", "file-history-snapshot"):
                    continue

                if dtype == "user":
                    content = d.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                        if has_tool_result:
                            seen_tool_result = True
                            continue
                    return _empty

                if dtype == "assistant":
                    content = d.get("message", {}).get("content", [])
                    tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                    if tool_uses:
                        if seen_tool_result:
                            return _empty
                        info = _format_tool_use(tool_uses[-1])
                        return PendingToolResult(has_pending=True, one_line=info.one_line, context=info.context)
                    return _empty

                if dtype == "progress":
                    msg = d["data"]["message"]
                    if msg.get("type") == "user":
                        return _empty
                    if msg.get("type") == "assistant":
                        content = msg.get("message", {}).get("content", [])
                        tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                        if tool_uses:
                            if seen_tool_result:
                                return _empty
                            info = _format_tool_use(tool_uses[-1])
                            return PendingToolResult(has_pending=True, one_line=info.one_line, context=info.context)
                        return _empty

            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return _empty

    # -- Main detection entry point -----------------------------------------

    def detect(self) -> list[ClaudeSession]:  # noqa: PLR0912, PLR0915
        """Detect all running Claude Code sessions."""
        try:
            r = subprocess.run(  # noqa: S603, S607
                ["pgrep", "-x", "claude"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
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

        # Cache JSONL path per CWD — avoids repeated directory scans
        jsonl_path_cache: dict[str, str | None] = {}

        sessions = []
        for pid in pids:
            info = all_ps.get(pid)
            if not info:
                continue
            tty = info.tty
            if tty == "??":
                walk_pid = info.ppid
                for _ in range(5):
                    if walk_pid <= 1:
                        break
                    parent = self._process_service.get_single_info(walk_pid)
                    if not parent:
                        break
                    if parent.tty != "??":
                        tty = parent.tty
                        break
                    walk_pid = parent.ppid
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
                match = _match_terminal_window(
                    tty,
                    project,
                    host_app,
                    terminal_windows,
                )
                window_title = match.window_title
                window_id = match.window_id
                host_app = match.host_app

            status = _determine_status(window_title)

            if cwd not in jsonl_path_cache:
                jsonl_path_cache[cwd] = self._session_log_service.find_most_recent(cwd)

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
                    session_id=self._get_session_id(cwd, jsonl_path_cache[cwd]),
                )
            )

        self._get_ide_tab_indices(sessions, all_ps)

        # JSONL-based status refinement.
        # The window title is the real-time signal. If it shows a working indicator
        # (braille spinner), Claude is actively streaming — trust it over JSONL.
        # For IDE sessions (no title indicators), JSONL is the only signal.
        cwd_status_cache: dict[str, tuple[PendingToolResult, SessionStatus]] = {}
        for s in sessions:
            if not s.cwd:
                continue
            if s.cwd not in cwd_status_cache:
                jpath = jsonl_path_cache.get(s.cwd)
                tail, age = self._read_jsonl_tail(jpath)
                if 0 <= age < _JSONL_STREAMING_THRESHOLD:
                    # JSONL modified < 5s ago — Claude is actively streaming
                    tool_result = PendingToolResult(has_pending=False, one_line="", context="")
                    jsonl_status = SessionStatus.WORKING
                else:
                    tool_result = self._check_jsonl_for_pending_tool(tail)
                    if tool_result.has_pending:
                        jsonl_status = s.status
                    elif age >= _JSONL_IDLE_THRESHOLD:
                        # Not modified in 60s+ — definitely idle. The last-message
                        # heuristic is unreliable for abandoned sessions that ended on a user message.
                        jsonl_status = SessionStatus.IDLE
                    else:
                        jsonl_status = self._check_jsonl_for_idle(tail)
                cwd_status_cache[s.cwd] = (tool_result, jsonl_status)

            tool_result, jsonl_status = cwd_status_cache[s.cwd]
            title_confirms_working = _has_working_indicator(s.window_title)
            title_confirms_idle = IDLE_INDICATOR in s.window_title

            if tool_result.has_pending and not title_confirms_working:
                # JSONL has unresolved tool_use, and window title doesn't show active work.
                # This covers: IDLE sessions, IDE sessions (no indicators), unknown hosts.
                s.status = SessionStatus.ATTENTION
                s.prompt_text = tool_result.one_line
                s.prompt_context = tool_result.context
            elif not tool_result.has_pending and not title_confirms_working and not title_confirms_idle:
                # Title has no indicator (IDE session or unknown host) — use JSONL status.
                # Note: JSONL status is shared across all sessions with the same CWD, so
                # we only apply it when the title gives no signal.
                s.status = jsonl_status
            # else: title confirms IDLE or WORKING — trust it over the shared-CWD JSONL

        return sessions


# ── Module-level pure functions ─────────────


def _format_tool_use(tool: dict) -> ToolUseInfo:
    """Format a tool_use block into ToolUseInfo with one_line and context."""
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
    return ToolUseInfo(one_line=one_line, context="\n".join(context_parts))


def _has_working_indicator(window_title: str) -> bool:
    """Check if the window title contains a known working indicator (braille spinner or ●).

    Returns False for generic titles like "VS Code", "PyCharm", "Terminal" — these
    don't tell us whether Claude is actively streaming. JSONL is authoritative for those.
    """
    # Braille characters (U+2800..U+28FF) are Claude's spinner frames
    return any("\u2800" <= ch <= "\u28ff" or ch == "●" for ch in window_title)


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
) -> TerminalMatch:
    """Try to match a session to a Terminal.app window by TTY or project name.
    Returns TerminalMatch with window_title, window_id, and possibly-updated host_app."""
    full_tty = tty if tty.startswith("/dev/") else f"/dev/{tty}"

    if full_tty in terminal_windows:
        title, wid = terminal_windows[full_tty]
        if host_app == HostApp.OTHER:
            host_app = HostApp.TERMINAL
        return TerminalMatch(window_title=title, window_id=wid, host_app=host_app)

    if host_app == HostApp.TMUX:
        for _, (tw_title, tw_wid) in terminal_windows.items():
            if project in tw_title:
                return TerminalMatch(window_title=tw_title, window_id=tw_wid, host_app=host_app)

    return TerminalMatch(window_title=host_app.value, window_id=None, host_app=host_app)

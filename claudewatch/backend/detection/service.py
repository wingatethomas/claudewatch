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
from claudewatch.backend.detection.constants import HOST_PROCESS_NAMES, IDLE_INDICATOR, PROMPT_KEYWORDS
from claudewatch.backend.detection.models import PendingToolResult, PromptInfo, TerminalMatch, ToolUseInfo

log = logging.getLogger("claudewatch")

# Module-level constants
_MAX_SESSIONS = 50
_TEXT_MAX_LEN = 80
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

    def _check_jsonl_for_pending_tool(self, cwd: str) -> PendingToolResult:  # noqa: PLR0911, PLR0912
        """Check if the most recent JSONL for this CWD has a pending tool_use.

        No age cutoffs — a tool waiting for approval stays pending regardless
        of how long ago the file was modified. Users can step away for hours.
        """
        _empty = PendingToolResult(has_pending=False, one_line="", context="")
        path = self._session_log_service.find_most_recent(cwd)
        if not path:
            return _empty

        if not os.path.isfile(path):
            return _empty

        tail = self._session_log_service.read_tail(path)
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
                    # Check if this is a tool_result (tool completed) or actual user input
                    content = d.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                        if has_tool_result:
                            seen_tool_result = True
                            continue  # keep scanning — the assistant tool_use before this is resolved
                    # Actual user input — tool approval given or new message
                    return _empty

                if dtype == "assistant":
                    content = d.get("message", {}).get("content", [])
                    tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                    if tool_uses:
                        if seen_tool_result:
                            # This tool_use was already resolved by a subsequent tool_result
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

        # JSONL-based status refinement.
        # Priority: ATTENTION (pending tool) > IDLE/WORKING from JSONL > window title.
        # Cache results per CWD so we don't re-read for sessions sharing a CWD.
        cwd_status_cache: dict[str, tuple[PendingToolResult, SessionStatus]] = {}
        for s in sessions:
            if not s.cwd:
                continue
            if s.cwd not in cwd_status_cache:
                tool_result = self._check_jsonl_for_pending_tool(s.cwd)
                jsonl_status = self._check_jsonl_for_idle(s.cwd) if not tool_result.has_pending else s.status
                cwd_status_cache[s.cwd] = (tool_result, jsonl_status)

            tool_result, jsonl_status = cwd_status_cache[s.cwd]
            if tool_result.has_pending:
                s.status = SessionStatus.ATTENTION
                s.prompt_text = tool_result.one_line
                s.prompt_context = tool_result.context
            else:
                # JSONL status takes precedence over window title
                s.status = jsonl_status

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


def _extract_prompt_info(buffer: str) -> PromptInfo:
    """Extract permission prompt context from the terminal buffer.
    Returns PromptInfo with one_line summary and full context."""
    lines = buffer.splitlines()
    prompt_line_idx = None

    for i in range(len(lines) - 1, -1, -1):
        lower = lines[i].strip().lower()
        if any(kw in lower for kw in PROMPT_KEYWORDS):
            prompt_line_idx = i
            break

    if prompt_line_idx is None:
        return PromptInfo(one_line="", context="")

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

    return PromptInfo(one_line=one_line, context=full_context)


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

import json
import logging
import os
import time

from claudewatch.backend.helpers import _shell, run_applescript
from claudewatch.backend.models import (
    HOST_PROCESS_NAMES,
    IDLE_INDICATOR,
    PROMPT_KEYWORDS,
    ClaudeSession,
    HostApp,
    SessionStatus,
)
from claudewatch.backend.services.jsonl import (
    find_most_recent_jsonl,
    get_session_id_from_path,
    read_jsonl_tail,
)
from claudewatch.backend.services.procinfo import (
    get_cwds,
    get_ppid,
    get_process_info,
    get_single_process_info,
    list_all_processes,
)
from claudewatch.backend.services.summarize import get_our_pids

log = logging.getLogger("claudewatch")

# PID → HostApp cache (host app doesn't change for a session's lifetime)
_host_app_cache: dict[int, HostApp] = {}

_MAX_SESSIONS = 50
_TEXT_MAX_LEN = 80
_JSONL_MAX_AGE = 60
_JSONL_MIN_AGE = 3
_WIN_SPLIT_FIELDS = 3


def _batch_ps_info(pids: list[int]) -> dict[int, dict]:
    """Get tty + ppid + comm for all PIDs via native libproc calls."""
    return get_process_info(pids)


def _batch_lsof_cwds(pids: list[int]) -> dict[int, str]:
    """Get CWD for all PIDs via native libproc calls."""
    return get_cwds(pids)


def _get_terminal_windows_and_buffers(
    tail_chars: int = 2000,
) -> tuple[dict[str, tuple[str, int]], dict[int, str]]:
    """Single AppleScript call: get all Terminal tab TTYs, titles, IDs, AND buffers.
    Returns ({tty: (title, window_id)}, {window_id: buffer_tail})."""
    result = run_applescript(f"""
    set winOutput to ""
    set bufOutput to ""
    if application "Terminal" is running then
        tell application "Terminal"
            repeat with w in windows
                set wid to id of w
                repeat with t in tabs of w
                    set winOutput to winOutput & (tty of t) & "|" & wid & "|" & (name of w) & linefeed
                end repeat
                try
                    set t to selected tab of w
                    set h to history of t
                    set n to length of h
                    if n > {tail_chars} then
                        set h to text (n - {tail_chars}) thru n of h
                    end if
                    set bufOutput to bufOutput & wid & "|" & h & linefeed & "---ENDWIN---" & linefeed
                end try
            end repeat
        end tell
    end if
    return winOutput & "===SPLIT===" & bufOutput
    """)

    parts = result.split("===SPLIT===", 1)
    win_raw = parts[0] if parts else ""
    buf_raw = parts[1] if len(parts) > 1 else ""

    windows = {}
    for line in win_raw.splitlines():
        p = line.split("|", 2)
        if len(p) == _WIN_SPLIT_FIELDS and p[1].isdigit():
            windows[p[0]] = (p[2], int(p[1]))

    buffers = {}
    for raw_block in buf_raw.split("---ENDWIN---"):
        block = raw_block.strip()
        if "|" in block:
            wid_str, content = block.split("|", 1)
            if wid_str.strip().isdigit():
                buffers[int(wid_str.strip())] = content

    return windows, buffers


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

    # Find the permission prompt line
    for i in range(len(lines) - 1, -1, -1):
        lower = lines[i].strip().lower()
        if any(kw in lower for kw in PROMPT_KEYWORDS):
            prompt_line_idx = i
            break

    if prompt_line_idx is None:
        return "", ""

    # Walk backwards from the prompt to find the ⏺ block start
    block_start = prompt_line_idx
    one_line = ""
    for j in range(prompt_line_idx - 1, max(prompt_line_idx - 30, -1), -1):
        stripped = lines[j].strip()
        if stripped.startswith("⏺"):
            block_start = j
            one_line = stripped.lstrip("⏺").strip()
            break
        # Stop at separators or user input
        if stripped.startswith("─") or stripped.startswith("❯"):
            block_start = j + 1
            break

    # Collect full context block from ⏺ line through prompt line
    context_lines = []
    for k in range(block_start, min(prompt_line_idx + 2, len(lines))):
        stripped = lines[k].strip()
        if stripped:
            context_lines.append(stripped)

    full_context = "\n".join(context_lines)

    if one_line and len(one_line) > _TEXT_MAX_LEN:
        one_line = one_line[:77] + "..."

    return one_line, full_context


def _check_jsonl_for_idle(cwd: str) -> SessionStatus:
    """Determine idle/working status from JSONL for sessions without window titles.

    If the last meaningful message is from the assistant (no pending tool_use),
    the session is idle — Claude finished and is waiting for user input.
    """
    path = find_most_recent_jsonl(cwd)
    if not path:
        return SessionStatus.WORKING

    tail = read_jsonl_tail(path, tail_bytes=5120)
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

    # If the last message is from the assistant, Claude is done — session is idle
    if last_type == "assistant":
        return SessionStatus.IDLE
    return SessionStatus.WORKING


def _get_session_id(cwd: str) -> str:
    """Get the most recent session ID for a CWD from the JSONL filename."""
    path = find_most_recent_jsonl(cwd)
    return get_session_id_from_path(path) if path else ""


def _check_jsonl_for_pending_tool(cwd: str) -> tuple[bool, str, str]:  # noqa: PLR0911, PLR0912
    """Check if the most recent JSONL for this CWD has a pending tool_use.
    Returns (is_pending, one_line_summary, full_context)."""
    path = find_most_recent_jsonl(cwd)
    if not path:
        return False, "", ""

    # Check file age: must be recent enough to be relevant (< 60s)
    # but stale enough that Claude has stopped writing (> 3s)
    try:
        age = time.time() - os.path.getmtime(path)
        if age > _JSONL_MAX_AGE or age < _JSONL_MIN_AGE:
            return False, "", ""
    except OSError:
        return False, "", ""

    tail = read_jsonl_tail(path)
    if not tail:
        return False, "", ""

    lines = tail.strip().splitlines()
    for line in reversed(lines[-20:]):
        try:
            d = json.loads(line)
            dtype = d.get("type")

            # Skip non-message types
            if dtype in ("system", "last-prompt", "pr-link", "queue-operation", "file-history-snapshot"):
                continue

            # Top-level user message or tool_result → not blocked
            if dtype == "user":
                return False, "", ""

            # Top-level assistant message with tool_use → blocked
            if dtype == "assistant":
                content = d.get("message", {}).get("content", [])
                tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                if tool_uses:
                    one_line, ctx = _format_tool_use(tool_uses[-1])
                    return True, one_line, ctx
                return False, "", ""

            # Progress messages
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


def _detect_host_app(pid: int, all_ps: dict[int, dict]) -> HostApp:
    """Walk PPID chain to find the host app. Results are cached by PID."""
    if pid in _host_app_cache:
        return _host_app_cache[pid]

    current = pid
    for _ in range(20):
        info = all_ps.get(current)
        ppid = info["ppid"] if info else 0

        if not ppid:
            ppid = get_ppid(current)

        if ppid <= 1:
            break

        if ppid in all_ps:
            comm = os.path.basename(all_ps[ppid]["comm"])
        else:
            pinfo = get_single_process_info(ppid)
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
            _host_app_cache[pid] = HostApp.TMUX
            return HostApp.TMUX
        for name, app in HOST_PROCESS_NAMES.items():
            if name in comm_lower:
                _host_app_cache[pid] = app
                return app
        current = ppid

    _host_app_cache[pid] = HostApp.OTHER
    return HostApp.OTHER


def _match_terminal_window(
    tty: str,
    project: str,
    host_app: HostApp,
    terminal_windows: dict[str, tuple[str, int]],
) -> tuple[str, int | None, HostApp]:
    """Try to match a session to a Terminal.app window by TTY or project name.
    Returns (window_title, window_id, possibly-updated host_app)."""
    full_tty = tty if tty.startswith("/dev/") else f"/dev/{tty}"

    # Direct TTY match (works for Terminal.app sessions)
    if full_tty in terminal_windows:
        title, wid = terminal_windows[full_tty]
        if host_app == HostApp.OTHER:
            host_app = HostApp.TERMINAL
        return title, wid, host_app

    # tmux: claude's PTY is server-side, doesn't match client TTY.
    # Fall back to matching project name in window title.
    if host_app == HostApp.TMUX:
        for _, (tw_title, tw_wid) in terminal_windows.items():
            if project in tw_title:
                return tw_title, tw_wid, host_app

    return host_app.value, None, host_app


def _get_ide_tab_indices(sessions: list[ClaudeSession], all_ps: dict[int, dict]) -> None:  # noqa: PLR0912
    """Map IDE terminal sessions to their tab indices using the process tree.
    PyCharm/VS Code terminal tabs are shell children of the IDE process, with unique TTYs.
    Tab order corresponds to PID order (oldest PID = first tab)."""
    # Group sessions by host app parent PID
    ide_sessions = [s for s in sessions if s.host_app in (HostApp.PYCHARM, HostApp.VSCODE)]
    if not ide_sessions:
        return

    # Find the IDE parent PIDs from the host app cache
    ide_pids: set[int] = set()
    for s in ide_sessions:
        # Walk PPID chain from claude PID to find the IDE process
        current = s.pid
        for _ in range(20):
            info = all_ps.get(current)
            ppid = info["ppid"] if info else 0
            if ppid <= 1:
                break
            if ppid in all_ps:
                comm = os.path.basename(all_ps[ppid]["comm"]).lower()
            else:
                pinfo = get_single_process_info(ppid)
                comm = os.path.basename(pinfo["comm"]).lower() if pinfo else ""
            if "pycharm" in comm or "idea" in comm or comm == "code" or "electron" in comm:
                ide_pids.add(ppid)
                break
            current = ppid

    if not ide_pids:
        return

    # Get all processes and filter for shell children of IDE processes
    all_procs = list_all_processes()
    shell_names = {"sh", "bash", "zsh", "fish", "dash", "tcsh", "ksh"}
    ide_shells: list[tuple[int, str]] = []  # (pid, tty)
    for proc in all_procs:
        child_ppid = proc["ppid"]
        child_tty = proc["tty"]
        child_comm = os.path.basename(proc["comm"])
        if child_ppid in ide_pids and child_tty != "??" and child_comm in shell_names:
            ide_shells.append((proc["pid"], child_tty))

    # Sort by PID (oldest first = first tab)
    ide_shells.sort(key=lambda x: x[0])

    # Build TTY → tab index map
    tty_to_index = {tty: i for i, (_, tty) in enumerate(ide_shells)}

    # Assign tab indices to sessions
    for s in ide_sessions:
        s.tab_index = tty_to_index.get(s.tty)


def _determine_status(window_title: str) -> SessionStatus:
    """Determine session status from window title indicators."""
    if IDLE_INDICATOR in window_title:
        return SessionStatus.IDLE
    return SessionStatus.WORKING


def detect_sessions() -> list[ClaudeSession]:  # noqa: PLR0912, PLR0915
    # Use pgrep for PID discovery — proc_name/proc_pidpath can't match argv[0]
    # which Claude Code rewrites from "node" to "claude"
    pids_out = _shell("pgrep -x claude")
    raw_pids = [int(p) for p in pids_out.splitlines() if p.strip().isdigit()]
    # Filter out ClaudeWatch's own summary subprocess PIDs
    our_pids = get_our_pids()
    pids = [p for p in raw_pids if p not in our_pids][:_MAX_SESSIONS]
    log.debug("detect: found %d claude processes", len(pids))
    if not pids:
        _host_app_cache.clear()
        return []

    all_ps = _batch_ps_info(pids)
    cwds = _batch_lsof_cwds(pids)
    terminal_windows: dict[str, tuple[str, int]] | None = None
    terminal_buffers: dict[int, str] | None = None

    # Evict stale cache entries
    live_pids = set(pids)
    for stale in list(_host_app_cache.keys()):
        if stale not in live_pids:
            del _host_app_cache[stale]

    sessions = []
    for pid in pids:
        info = all_ps.get(pid)
        if not info:
            continue
        tty = info["tty"]
        # Claude processes often have no direct TTY — walk PPID chain to find it
        if tty == "??":
            walk_pid = info["ppid"]
            for _ in range(5):
                if walk_pid <= 1:
                    break
                parent = get_single_process_info(walk_pid)
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

        host_app = _detect_host_app(pid, all_ps)

        # Allow TTY-less sessions for IDE host apps (VS Code extension, PyCharm plugin).
        # These spawn Claude as a direct subprocess without a terminal emulator.
        if (not tty or tty == "??") and host_app not in (HostApp.VSCODE, HostApp.PYCHARM):
            continue
        window_title = host_app.value
        window_id = None

        if host_app in (HostApp.TERMINAL, HostApp.TMUX, HostApp.OTHER):
            if terminal_windows is None:
                terminal_windows, terminal_buffers = _get_terminal_windows_and_buffers()
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
                session_id=_get_session_id(cwd),
            )
        )

    # Process terminal buffers (already fetched in the combined AppleScript call)
    buffers = terminal_buffers or {}
    if buffers:
        for s in sessions:
            if s.window_id in buffers:
                buf = buffers[s.window_id]
                # Extract latest output for all sessions
                s.last_output = _extract_last_output(buf)
                # Check for permission prompts in ALL sessions
                lower = buf.lower()
                if any(kw in lower for kw in PROMPT_KEYWORDS):
                    s.status = SessionStatus.ATTENTION
                    s.prompt_text, s.prompt_context = _extract_prompt_info(buf)

    # Determine terminal tab indices for IDE sessions
    _get_ide_tab_indices(sessions, all_ps)

    # For sessions without window IDs (PyCharm, VS Code), determine status from JSONL
    # since we can't read terminal window titles for these sessions
    checked_cwds: set[str] = set()
    for s in sessions:
        if s.window_id is None and s.cwd and s.cwd not in checked_cwds:
            pending, one_line, context = _check_jsonl_for_pending_tool(s.cwd)
            if pending:
                s.status = SessionStatus.ATTENTION
                s.prompt_text = one_line
                s.prompt_context = context
            else:
                s.status = _check_jsonl_for_idle(s.cwd)
            checked_cwds.add(s.cwd)

    return sessions

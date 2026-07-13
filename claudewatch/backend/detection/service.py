import json
import logging
import os
import re
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
from claudewatch.backend.core.session_log.schema import BlockType, EntryType
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.core.worktree import WorktreeInfo, resolve_worktree
from claudewatch.backend.detection.constants import HOST_PROCESS_NAMES, IDLE_INDICATOR
from claudewatch.backend.detection.models import PendingToolResult, TerminalMatch, ToolUseInfo

log = logging.getLogger("claudewatch")

# Module-level constants
_MAX_SESSIONS = 50
_TEXT_MAX_LEN = 80
_WIN_SPLIT_FIELDS = 3
_TERMINAL_CACHE_TTL = 3  # seconds between AppleScript refreshes
_AI_TITLE_CACHE_TTL = 3  # seconds between per-CWD ai-title scans
_WORKTREE_CACHE_TTL = 30  # seconds between per-CWD worktree re-resolution
_JSONL_STREAMING_THRESHOLD = 5  # JSONL modified within this → actively streaming
_BIRTHTIME_SLACK = 5.0  # clock slack when comparing file birth to process start
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
        # (requested ttys key, {tty: visible screen}, timestamp)
        self._buffer_cache: tuple[str, dict[str, str], float] | None = None
        # cwd → ({ai_title: jsonl_path}, timestamp). Lets each session in a shared
        # CWD read its own JSONL instead of the most-recent one for the project.
        self._ai_title_cache: dict[str, tuple[dict[str, str], float]] = {}
        # path → last known aiTitle. Long sessions push their ai-title entry out
        # of the tail window; this remembers it so the full-file scan runs at
        # most once per path. Tail scans still pick up newer titles.
        self._ai_title_by_path: dict[str, str] = {}
        # cwd → (WorktreeInfo | None, timestamp). Branch switches are rare, so
        # a longer TTL than the title caches.
        self._worktree_cache: dict[str, tuple[WorktreeInfo | None, float]] = {}

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
                    try
                        set wid to id of w
                        repeat with t in tabs of w
                            set output to output & (tty of t) & "|" & wid & "|" & (name of w) & linefeed
                        end repeat
                    end try
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

    def _get_terminal_buffers(self, targets: list[tuple[str, int]]) -> dict[str, str]:
        """Visible screen contents for (tty, window_id) Terminal.app tabs.

        One AppleScript pass, cached for _TERMINAL_CACHE_TTL seconds. Only
        inline reference chains are used — stored tab references fail to
        dereference their properties — and addressing by window id skips
        ghost windows entirely. TTY names are validated (ttysNNN only) and
        window ids are ints, so the script receives no untrusted input.
        """
        now = time.time()
        wanted = sorted(
            {(t, int(w)) for t, w in targets if re.fullmatch(r"ttys[0-9]+", t or "")},
        )
        if not wanted:
            return {}
        cache_key = ",".join(f"{t}:{w}" for t, w in wanted)
        if (
            self._buffer_cache is not None
            and self._buffer_cache[0] == cache_key
            and now - self._buffer_cache[2] < _TERMINAL_CACHE_TTL
        ):
            return self._buffer_cache[1]

        tty_list = ", ".join(f'"/dev/{t}"' for t, _ in wanted)
        wid_list = ", ".join(str(w) for w in sorted({w for _, w in wanted}))
        result = run_applescript(f"""
        if application "Terminal" is running then
            tell application "Terminal"
                set wantedTtys to {{{tty_list}}}
                set output to ""
                repeat with wid in {{{wid_list}}}
                    try
                        set tabCount to count of tabs of window id wid
                        repeat with i from 1 to tabCount
                            if wantedTtys contains (tty of tab i of window id wid) then
                                set output to output & "<<TTY:" & (tty of tab i of window id wid) & ">>" & (contents of tab i of window id wid)
                            end if
                        end repeat
                    end try
                end repeat
                return output
            end tell
        end if
        return ""
        """)

        buffers: dict[str, str] = {}
        for chunk in result.split("<<TTY:/dev/")[1:]:
            name, _, body = chunk.partition(">>")
            buffers[name] = body
        self._buffer_cache = (cache_key, buffers, now)
        return buffers

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

    # -- Per-session JSONL matching ----------------------------------------

    def _get_ai_title_map(self, cwd: str) -> dict[str, str]:
        """Return {aiTitle: jsonl_path} for all JSONLs in a CWD.

        Multiple Claude sessions can share a CWD; each writes its own JSONL.
        Matching a session's window title against this map lets us read the
        JSONL that actually belongs to that session — not just the most-recent
        one for the project.

        Cached per cwd with _AI_TITLE_CACHE_TTL.
        """
        now = time.time()
        cached = self._ai_title_cache.get(cwd)
        if cached is not None and now - cached[1] < _AI_TITLE_CACHE_TTL:
            return cached[0]

        mapping: dict[str, str] = {}
        for path in self._session_log_service.list_in_cwd(cwd):
            title = self._read_ai_title(path)
            if not title:
                continue
            # If two JSONLs share an ai-title (rare, e.g. after a session
            # restart), the more-recently-modified one wins because list_in_cwd
            # returns mtime-desc and we keep the first writer.
            mapping.setdefault(title, path)

        self._ai_title_cache[cwd] = (mapping, now)
        return mapping

    def _get_worktree(self, cwd: str) -> WorktreeInfo | None:
        now = time.time()
        cached = self._worktree_cache.get(cwd)
        if cached is not None and now - cached[1] < _WORKTREE_CACHE_TTL:
            return cached[0]
        info = resolve_worktree(cwd)
        self._worktree_cache[cwd] = (info, now)
        return info

    def _read_ai_title(self, path: str) -> str:
        """Read a JSONL's aiTitle: cheap tail scan first, full scan once as fallback."""
        title = self._session_log_service.read_ai_title(path)
        if title:
            self._ai_title_by_path[path] = title
            return title
        if path in self._ai_title_by_path:
            return self._ai_title_by_path[path]
        title = self._session_log_service.read_ai_title_full(path)
        self._ai_title_by_path[path] = title
        return title

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
            if dtype in (EntryType.USER, EntryType.ASSISTANT):
                last_type = dtype

        if last_type == EntryType.ASSISTANT:
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
        # Scan the whole tail: Claude Code writes many trailing bookkeeping
        # entries — mode, permission-mode, attachment, queue-operation — that
        # would push a pending tool_use past any fixed line window. The loop
        # terminates at the first user, assistant, or progress entry anyway.
        seen_tool_result = False

        for line in reversed(lines):
            try:
                d = json.loads(line)
                dtype = d.get("type")

                if dtype in (EntryType.SYSTEM, "last-prompt", "pr-link", "queue-operation", "file-history-snapshot"):
                    continue

                if dtype == EntryType.USER:
                    content = d.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                        if has_tool_result:
                            seen_tool_result = True
                            continue
                    return _empty

                if dtype == EntryType.ASSISTANT:
                    content = d.get("message", {}).get("content", [])
                    tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == BlockType.TOOL_USE]
                    if tool_uses:
                        if seen_tool_result:
                            return _empty
                        info = _format_tool_use(tool_uses[-1])
                        return PendingToolResult(has_pending=True, one_line=info.one_line, context=info.context)
                    return _empty

                if dtype == EntryType.PROGRESS:
                    msg = d["data"]["message"]
                    if msg.get("type") == EntryType.USER:
                        return _empty
                    if msg.get("type") == EntryType.ASSISTANT:
                        content = msg.get("message", {}).get("content", [])
                        tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == BlockType.TOOL_USE]
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
        # pgrep matches argv[0] and misses native-installer processes whose
        # kernel name is the version string (~/.local/share/claude/versions/X).
        # Union with a libproc scan on executable path so neither source alone
        # has to be complete.
        pgrep_pids = set(raw_pids)
        for proc in self._process_service.list_all():
            if proc.pid not in pgrep_pids and _is_claude_cli(proc.comm):
                raw_pids.append(proc.pid)
        child_pids = self._process_service.get_child_pids()
        pids = [p for p in raw_pids if p not in child_pids][:_MAX_SESSIONS]
        log.debug("detect: found %d claude processes", len(pids))
        if not pids:
            self._host_app_cache.clear()
            self._ai_title_cache.clear()
            return []

        all_ps = self._batch_ps_info(pids)
        cwds = self._batch_lsof_cwds(pids)
        terminal_windows: dict[str, tuple[str, int]] | None = None

        # Evict stale cache entries
        live_pids = set(pids)
        for stale in list(self._host_app_cache.keys()):
            if stale not in live_pids:
                del self._host_app_cache[stale]
        live_cwds = set(cwds.values())
        for stale_cwd in list(self._ai_title_cache.keys()):
            if stale_cwd not in live_cwds:
                del self._ai_title_cache[stale_cwd]
        for stale_cwd in list(self._worktree_cache.keys()):
            if stale_cwd not in live_cwds:
                del self._worktree_cache[stale_cwd]

        # Per-session JSONL path — keyed by PID. With shared-CWD setups the
        # most-recent file in the project dir often belongs to a sibling
        # session, so we match on aiTitle from the window title first and
        # pair the rest by process start time vs file birth time below.
        session_jsonl: dict[int, str | None] = {}

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

            jpath, title_matched = _match_jsonl_by_title(window_title, self._get_ai_title_map(cwd), None)
            session_jsonl[pid] = jpath if title_matched else None
            worktree = self._get_worktree(cwd)

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
                    session_id=self._get_session_id(cwd, jpath) if title_matched and jpath else "",
                    ai_title=self._ai_title_by_path.get(jpath, "") if title_matched and jpath else "",
                    worktree_repo=worktree.repo if worktree else "",
                    worktree_branch=worktree.branch if worktree else "",
                )
            )

        # Pair unmatched sessions with logs they could actually own. A session's
        # JSONL is created when the session starts, so files born before the
        # process belong to someone else — including dead sessions whose
        # unresolved tool_use would otherwise read as phantom ATTENTION on
        # every unmatched session. Each file is claimed at most once; newest
        # sessions pick first so fresh sessions pair with fresh logs.
        claimed_paths = {p for p in session_jsonl.values() if p}
        unmatched = [s for s in sessions if not session_jsonl.get(s.pid)]
        starts = {s.pid: self._process_service.get_start_time(s.pid) for s in unmatched}
        for s in sorted(unmatched, key=lambda x: starts[x.pid], reverse=True):
            candidate = None
            for path in self._session_log_service.list_in_cwd(s.cwd):
                if path in claimed_paths:
                    continue
                start = starts[s.pid]
                if start and _file_birthtime(path) < start - _BIRTHTIME_SLACK and _file_mtime(path) < start:
                    # Born before this process and untouched since it started —
                    # someone else's log. (A resumed session appends to a file
                    # born earlier, so a fresh mtime still qualifies it.)
                    continue
                candidate = path
                break
            if candidate:
                claimed_paths.add(candidate)
                session_jsonl[s.pid] = candidate
                s.session_id = self._get_session_id(s.cwd, candidate)
                s.ai_title = self._ai_title_by_path.get(candidate, "")

        self._get_ide_tab_indices(sessions, all_ps)

        # JSONL-based status refinement. Each session reads its own JSONL
        # (matched by aiTitle); two sessions in the same CWD won't share state.
        # The window title is the real-time signal — if it shows a working
        # indicator (braille spinner) we trust it over JSONL. For IDE sessions
        # (no title indicators) JSONL is the only signal.
        path_status_cache: dict[str, tuple[PendingToolResult, SessionStatus]] = {}
        for s in sessions:
            if not s.cwd:
                continue
            jpath = session_jsonl.get(s.pid)
            cache_key = jpath or ""
            if jpath is None:
                # No log evidence at all (nothing pairable) — that's idle,
                # not working. Title indicators still override below.
                path_status_cache.setdefault(
                    cache_key,
                    (PendingToolResult(has_pending=False, one_line="", context=""), SessionStatus.IDLE),
                )
            if cache_key not in path_status_cache:
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
                path_status_cache[cache_key] = (tool_result, jsonl_status)

            tool_result, jsonl_status = path_status_cache[cache_key]
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
                s.status = jsonl_status
            # else: title confirms IDLE or WORKING — trust it

        # Claude Code no longer writes the pending tool_use to the JSONL until
        # the permission decision is made, so the JSONL alone can't see a
        # waiting dialog. For Terminal sessions the dialog is on the visible
        # screen — read it and upgrade to ATTENTION.
        idle_terminal = [
            s
            for s in sessions
            if s.host_app == HostApp.TERMINAL and s.status != SessionStatus.WORKING and s.tty and s.window_id
        ]
        if idle_terminal:
            buffers = self._get_terminal_buffers([(s.tty, s.window_id) for s in idle_terminal])
            for s in idle_terminal:
                prompt = _buffer_prompt_line(buffers.get(s.tty, ""))
                if prompt:
                    s.status = SessionStatus.ATTENTION
                    s.prompt_text = prompt

        return sessions


_DIALOG_QUESTION_RE = re.compile(r"(?m)^\s*(.*Do you (?:want|trust).*?)\s*$")
_DIALOG_OPTION_RE = re.compile(r"(?m)^\s*❯?\s*1\.\s")
_DIALOG_TOOL_RE = re.compile(r"(?m)^\s*⏺\s*(\S.*?)\s*$")


def _buffer_prompt_line(buffer_text: str) -> str:
    """One-line description when the visible screen shows an input dialog.

    Matches permission prompts, edit confirmations, trust prompts, and
    numbered-choice dialogs. Returns "" when the screen shows no dialog.
    """
    if not buffer_text:
        return ""
    question = _DIALOG_QUESTION_RE.search(buffer_text)
    has_choices = _DIALOG_OPTION_RE.search(buffer_text) and "2." in buffer_text and "sc to" in buffer_text
    if not question and not has_choices:
        return ""
    tool_lines = _DIALOG_TOOL_RE.findall(buffer_text)
    line = tool_lines[-1] if tool_lines else (question.group(1) if question else "Waiting for your input")
    if len(line) > _TEXT_MAX_LEN:
        line = line[: _TEXT_MAX_LEN - 3] + "..."
    return line


def _file_birthtime(path: str) -> float:
    """File creation time (mtime fallback). Returns 0.0 when unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return 0.0
    return getattr(st, "st_birthtime", st.st_mtime)


def _file_mtime(path: str) -> float:
    """File modification time. Returns 0.0 when unreadable."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _is_claude_cli(comm: str) -> bool:
    """Match Claude Code CLI executables by path.

    Covers the native installer (~/.local/share/claude/versions/<x.y.z>) and
    installs whose binary is named exactly 'claude'. Case-sensitive so Claude
    Desktop ('Claude', 'Claude Helper') doesn't match.
    """
    return os.path.basename(comm) == "claude" or "/claude/versions/" in comm


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


def _match_jsonl_by_title(
    window_title: str,
    ai_title_map: dict[str, str],
    fallback: str | None,
) -> tuple[str | None, bool]:
    """Find the JSONL whose aiTitle appears as a substring of the window title.

    Used to disambiguate multiple Claude sessions sharing a CWD. Longest match
    wins so a substring title doesn't shadow a more specific one. Returns
    (path, matched_by_title); the path is `fallback` when nothing matches —
    which preserves prior behavior for brand-new sessions (no ai-title yet)
    and IDE sessions (no terminal title).
    """
    if not window_title or not ai_title_map:
        return (fallback, False)
    best_title = ""
    best_path = fallback
    for title, path in ai_title_map.items():
        if title and title in window_title and len(title) > len(best_title):
            best_title = title
            best_path = path
    return (best_path, bool(best_title))


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

"""Live smoke checks against the real machine — run before cutting a release.

The unit suite mocks every system boundary (AppleScript, libproc, Claude's
JSONL writes), so it stays green while the outside world drifts: CLI log
format changes, Terminal scripting quirks, ghost windows, permission-dialog
rendering. These checks exercise the real thing and fail on drift.

Usage:
    uv run python scripts/live_smoke.py          # passive checks only
    uv run python scripts/live_smoke.py --pty    # also drive a scratch claude
                                                 # session into a permission
                                                 # dialog (uses your account)
"""

from __future__ import annotations

import fcntl
import glob
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time

import claudewatch.backend.detection.service as detection_service
from claudewatch.backend.core.process.service import ProcessService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.service import DetectionService

_PASS = 0
_FAIL = 0


def _report(ok: bool, name: str, detail: str = "") -> None:
    global _PASS, _FAIL  # noqa: PLW0603
    if ok:
        _PASS += 1
    else:
        _FAIL += 1
    suffix = f" — {detail}" if detail else ""
    print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")


def _osascript(source: str, *, timeout: float = 30.0) -> str:
    """Shell out to osascript so the check runs under the terminal's automation grant."""
    result = subprocess.run(  # noqa: S603, S607
        ["osascript", "-e", source],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result.stdout.rstrip("\n")


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Z0-9]|\x1b\][^\x07]*\x07", "", text)


def check_detection() -> list:
    """detect() against live processes: sessions found, identities distinct."""
    detection_service.run_applescript = _osascript
    svc = DetectionService(ProcessService(), SessionLogService())
    sessions = svc.detect()

    _report(len(sessions) > 0, "detection finds live sessions", f"{len(sessions)} found")
    sids = [s.session_id for s in sessions if s.session_id]
    dupes = len(sids) - len(set(sids))
    _report(dupes == 0, "session identities are distinct", f"{dupes} duplicated" if dupes else "")

    terminal = [s for s in sessions if s.host_app.value == "Terminal"]
    titled = [s for s in terminal if s.window_id]
    _report(
        not terminal or len(titled) >= len(terminal) // 2,
        "terminal window titles resolve",
        f"{len(titled)}/{len(terminal)} matched (ghost windows tolerated)",
    )

    idle_terminal = [s for s in terminal if s.status.name != "WORKING" and s.window_id]
    if idle_terminal:
        svc._buffer_cache = None  # noqa: SLF001
        buffers = svc._get_terminal_buffers([(s.tty, s.window_id) for s in idle_terminal])  # noqa: SLF001
        _report(
            len(buffers) == len(idle_terminal),
            "screen buffers readable for idle terminals",
            f"{len(buffers)}/{len(idle_terminal)}",
        )
    else:
        _report(True, "screen buffers readable for idle terminals", "no idle terminal sessions to sample")

    attention = [s for s in sessions if s.status.name == "ATTENTION"]
    for s in attention:
        print(f"      note: ATTENTION on pid {s.pid}: {s.prompt_text[:60]}")
    return sessions


def _jsonl_has_tool_use(proj_dir: str) -> bool:
    files = sorted(glob.glob(proj_dir + "/*.jsonl"), key=os.path.getmtime, reverse=True)
    if not files:
        return False
    with open(files[0]) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if entry.get("type") == "assistant":
                content = entry.get("message", {}).get("content", [])
                if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                    return True
    return False


# TUI apps query the terminal and wait on replies a dumb PTY never sends —
# answer the common ones so input handling doesn't wedge.
_QUERY_REPLIES = (
    (b"\x1b[6n", b"\x1b[40;120R"),  # cursor position report
    (b"\x1b[>0q", b"\x1bP>|cw-smoke\x1b\\"),  # XTVERSION
    (b"\x1b[c", b"\x1b[?1;2c"),  # primary device attributes
)


def _drain(fd: int, seconds: float) -> bytes:
    out = b""
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            out += chunk
            for query, reply in _QUERY_REPLIES:
                if query in chunk:
                    os.write(fd, reply)
    return out


def check_pty_probe() -> None:
    """Drive a scratch claude session into a permission dialog and verify:

    1. our dialog signature still matches the CLI's real rendering, and
    2. whether the CLI writes the pending tool_use to the JSONL (it currently
       does NOT — the reason attention detection reads the screen).
    """
    # A subdir of the repo inherits its folder trust (no trust dialog to
    # automate) while still getting its own isolated JSONL project dir.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scratch = tempfile.mkdtemp(prefix=".smoke-", dir=repo_root)
    real = os.path.realpath(scratch)
    proj_dir = os.path.expanduser("~/.claude/projects/" + real.replace("/", "-"))
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.chdir(scratch)
        os.execvp("claude", ["claude"])  # noqa: S606

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    raw = b""

    def screen() -> str:
        return _strip_ansi(raw.decode("utf-8", errors="replace"))

    try:
        deadline = time.time() + 45
        while time.time() < deadline and "shortcuts" not in screen():
            raw += _drain(fd, 2)
        if "shortcuts" not in screen():
            _report(False, "probe session boots to input prompt", "screen tail: " + screen()[-120:])
            return

        for ch in b"use bash to create a file named probe.txt with touch":
            os.write(fd, bytes([ch]))
            time.sleep(0.02)
        time.sleep(1)
        os.write(fd, b"\r")

        # Poll until the dialog renders — model latency varies. The PTY
        # stream positions text via cursor escapes, so stripped output loses
        # inter-word spacing; the real app reads Terminal `contents of tab`,
        # which is properly spaced. Compare wording space-insensitively.
        deadline = time.time() + 90
        seen = False
        while time.time() < deadline and not seen:
            raw += _drain(fd, 3)
            squashed = re.sub(r"\s+", "", screen())
            seen = "Doyouwant" in squashed or "Doyoutrust" in squashed
        _report(seen, "permission dialog wording matches expected signature")
        if not seen:
            print("      screen tail:", screen()[-200:].replace("\n", " ⏎ "))

        _report(
            not _jsonl_has_tool_use(proj_dir),
            "CLI still defers tool_use until permission decision",
            "if this fails, the JSONL attention path works again — revisit buffer detection",
        )
    finally:
        os.kill(pid, signal.SIGKILL)
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(proj_dir, ignore_errors=True)


def main() -> int:
    print("== ClaudeWatch live smoke checks ==")
    check_detection()
    if "--pty" in sys.argv:
        check_pty_probe()
    else:
        print("      (skipping PTY probe — pass --pty to drive a real permission dialog)")
    print(f"== {_PASS} passed, {_FAIL} failed ==")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

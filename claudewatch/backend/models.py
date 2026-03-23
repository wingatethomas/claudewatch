import os
import re
from dataclasses import dataclass
from enum import Enum

CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def cwd_to_proj_key(cwd: str) -> str:
    """Convert a CWD path to a Claude projects directory key.

    Example: '/Users/dev/myapp' -> '-Users-dev-myapp'
    """
    return cwd.replace("/", "-")


def proj_key_to_cwd(proj_key: str) -> str:
    """Best-effort reverse of cwd_to_proj_key.

    Known limitation: ambiguous with hyphens in directory names.
    Example: '-Users-dev-myapp' -> '/Users/dev/myapp'
    """
    if proj_key.startswith("-"):
        return "/" + proj_key[1:].replace("-", "/")
    return proj_key.replace("-", "/", 1)


class HostApp(Enum):
    TERMINAL = "Terminal"
    PYCHARM = "PyCharm"
    VSCODE = "VS Code"
    TMUX = "tmux"
    OTHER = "Other"


HOST_APP_PATH = {
    HostApp.TERMINAL: "/System/Applications/Utilities/Terminal.app",
    HostApp.PYCHARM: "/Applications/PyCharm.app",
    HostApp.VSCODE: "/Applications/Visual Studio Code.app",
    HostApp.TMUX: None,
    HostApp.OTHER: None,
}


class SessionStatus(Enum):
    WORKING = "working"  # braille/● in title — actively streaming
    IDLE = "idle"  # ✳ in title — done, waiting for user
    ATTENTION = "attention"  # idle + permission prompt in buffer


STATUS_INDICATOR = {
    SessionStatus.WORKING: "✦",
    SessionStatus.IDLE: "⏸",
    SessionStatus.ATTENTION: "⚠",
}


# Permission prompt markers in the terminal buffer
PROMPT_KEYWORDS = [
    "do you want to proceed",
    "yes, allow",
    "esc to cancel",
    "allow once",
    "allow always",
    "yes, proceed",
    "approve this action",
]

# Claude Code sets ✳ in the title when idle (not actively streaming)
IDLE_INDICATOR = "✳"

# Process names → host app (matched case-insensitively against PPID chain)
HOST_PROCESS_NAMES = {
    "terminal": HostApp.TERMINAL,
    "pycharm": HostApp.PYCHARM,
    "idea": HostApp.PYCHARM,
    "electron": HostApp.VSCODE,
    "code helper": HostApp.VSCODE,
    "code": HostApp.VSCODE,
    "tmux": HostApp.TMUX,
}


@dataclass
class ClaudeSession:
    pid: int
    tty: str
    project: str
    cwd: str
    host_app: HostApp
    window_title: str = ""
    window_id: int | None = None
    status: SessionStatus = SessionStatus.WORKING
    last_output: str = ""
    prompt_text: str = ""  # one-line summary for menu
    prompt_context: str = ""  # full multi-line context for alert
    tab_index: int | None = None  # terminal tab index within IDE (0-based)
    session_id: str = ""  # Claude Code session UUID from JSONL filename

    @property
    def task_summary(self) -> str:
        """Extract the Claude task/status from the window title.
        Titles look like: 'project — ✳ Some Task — claude TMPDIR=...'"""
        # Match all braille spinner frames (U+2800..U+28FF) plus ✳ and ●
        for sep_re in (r"— ✳ ", r"— [⠀-⣿] ", r"— ● "):
            m = re.search(sep_re, self.window_title)
            if m:
                after = self.window_title[m.end() :]
                for end in (" — claude", " — caffeinate", " — npm"):
                    if end in after:
                        after = after.split(end, 1)[0]
                return after.strip()
        return ""

    @property
    def needs_attention(self) -> bool:
        return self.status == SessionStatus.ATTENTION

    @property
    def menu_label(self) -> str:
        _max_label = 40
        ind = STATUS_INDICATOR[self.status]
        task = self.task_summary
        tab = f" (tab {self.tab_index + 1})" if self.tab_index is not None else ""
        if task and task != "Claude Code":
            label = f"{ind} {self.project}{tab} — {task}"
        else:
            label = f"{ind} {self.project}{tab}"
        if len(label) > _max_label:
            return label[: _max_label - 1] + "…"
        return label

    @property
    def detail_line(self) -> str:
        """Secondary line shown under the session in the menu."""
        _max_detail = 35
        text = ""
        if self.status == SessionStatus.ATTENTION and self.prompt_text:
            text = self.prompt_text
        elif self.last_output:
            text = self.last_output
        if text:
            if len(text) > _max_detail:
                return text[: _max_detail - 1] + "…"
            return text
        if self.status == SessionStatus.WORKING:
            return "Working..."
        if self.status == SessionStatus.IDLE:
            return "Waiting for input"
        return ""

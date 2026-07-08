import re
from dataclasses import dataclass
from enum import Enum

# Raw outputs that shouldn't be shown to users as status text
_GARBAGE_PATTERNS = (
    "execution error",
    "error:",
    "traceback",
    "exception",
    "errno",
    "permission denied",
    "no such file",
    "command not found",
)


def _is_user_friendly(text: str) -> bool:
    """Check if text is suitable for display as a session status line."""
    lower = text.lower().strip()
    if not lower or len(lower) < 3:  # noqa: PLR2004
        return False
    return not any(pattern in lower for pattern in _GARBAGE_PATTERNS)


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
    agent_count: int = 0  # populated by analytics.enrich_sessions()
    ai_title: str = ""  # Claude-generated session title from the matched JSONL

    @property
    def task_summary(self) -> str:
        """The session's task: its aiTitle when known, else parsed from the window title.
        Titles look like: 'project — ✳ Some Task — node ◂ claude — 120×40'"""
        if self.ai_title:
            return self.ai_title
        # Match all braille spinner frames (U+2800..U+28FF) plus ✳ and ●
        for sep_re in (r"— ✳ ", r"— [⠀-⣿] ", r"— ● "):
            m = re.search(sep_re, self.window_title)
            if m:
                after = self.window_title[m.end() :]
                return after.split(" — ", 1)[0].strip()
        return ""

    @property
    def needs_attention(self) -> bool:
        return self.status == SessionStatus.ATTENTION

    @property
    def menu_label(self) -> str:
        _max_label = 50
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
        elif self.last_output and _is_user_friendly(self.last_output):
            text = self.last_output
        if text:
            if len(text) > _max_detail:
                return text[: _max_detail - 1] + "…"
            return text
        if self.status == SessionStatus.WORKING:
            return "Working..."
        if self.status == SessionStatus.IDLE:
            return "Idle"
        return ""

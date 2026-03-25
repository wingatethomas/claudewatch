from claudewatch.backend.core.models import HostApp

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

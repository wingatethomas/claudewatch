from claudewatch.backend.core.models import HostApp

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

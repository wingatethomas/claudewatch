# ClaudeWatch

macOS menu bar app that monitors all your running [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions and lets you switch between them with a click.

## Requirements

- macOS 13+
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)

## Install

```bash
git clone https://github.com/wingatethomas/claudewatch.git
cd claudewatch
uv sync
```

## Run

```bash
uv run claudewatch
```

## What it does

ClaudeWatch polls every 2 seconds and shows all active Claude Code sessions in your menu bar, grouped by status:

- **⚠ Attention** — session is waiting for permission (e.g. file edit, shell command)
- **✦ Working** — Claude is actively running
- **⏸ Idle** — session is waiting for user input

Click any session to focus its window. Works with:

- **Terminal.app** — focuses the exact window
- **PyCharm** — focuses the window and switches to the correct terminal tab
- **VS Code** — focuses the window and switches to the correct terminal tab
- **tmux** — matches sessions by project name in the window title

### Pinned Sessions

Pin sessions you want to come back to. Pinned sessions show 📌 in the dropdown when active, and appear in a separate "Pinned" section when paused. Click a pinned session to resume it in a new Terminal tab. Pins persist across app restarts with a 30-day TTL.

### Notifications

When a session needs attention, ClaudeWatch sends a macOS notification with the project name, task, and what Claude is asking for. Notifications are suppressed if the session's window is already in front, with a 30-second cooldown between alerts.

### How it works

1. Native `libproc` calls find running Claude processes, TTYs, CWDs, and parent process info (no subprocess forks)
2. PPID chain walking identifies the host app (Terminal, PyCharm, VS Code)
3. For Terminal.app: AppleScript reads window titles and terminal buffers to detect permission prompts
4. For IDEs: JSONL session logs (`~/.claude/projects/`) are checked for pending tool_use requests

### macOS Permissions

ClaudeWatch needs **Accessibility** access (System Settings → Privacy & Security → Accessibility) to:
- Read terminal window titles and content
- Focus and raise windows
- Click PyCharm/VS Code terminal tabs

### Audit Log

ClaudeWatch writes an audit log to `~/.claude/claudewatch.log` (owner-readable only). It records session starts/ends, status transitions, focus actions, and notifications — never terminal content or sensitive data. Rotates at 1MB with 3 backups.

```bash
tail -f ~/.claude/claudewatch.log
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[GPL-3.0](LICENSE)

# ClaudeWatch

macOS menu bar app that monitors all your running [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions and lets you switch between them with a click.

## Requirements

- macOS 13+
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [terminal-notifier](https://github.com/julienXX/terminal-notifier) (optional, for notifications): `brew install terminal-notifier`

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

ClaudeWatch polls every second and shows all active Claude Code sessions in your menu bar, grouped by status:

- **⚠ Attention** (red dot) — session is waiting for permission
- **✦ Working** (green dot) — Claude is actively running
- **⏸ Idle** (yellow dot) — session is waiting for user input

Each session shows its model (e.g. opus 4.6) and host app. Click any session to focus its window.

### Supported Environments

- **Terminal.app** — focuses the exact window
- **PyCharm** — focuses the window and switches to the correct terminal tab
- **VS Code** — focuses the window and switches to the correct terminal tab
- **tmux** — matches sessions by project name in the window title

### Activity Feed

Right-click any session and select **Activity** to see a timeline of what Claude did — user messages, assistant responses, and every tool call with inputs.

### Pinned Sessions

Pin sessions you want to come back to later. Pinned sessions show ★ when active, and appear in a separate "Pinned" section when paused. Click a pinned session to resume it in a new Terminal tab. Pins persist across app restarts with a 30-day TTL.

### Notifications

Native macOS notifications when a session needs attention. Shows the project name and what Claude is asking for. Notifications are suppressed if the session's window is already in front, with a 30-second cooldown.

### Preferences

Accessible from the dropdown menu. Configure notifications on/off and alert sound.

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

ClaudeWatch writes an audit log to `~/.claude/claudewatch.log` (owner-readable only). It records session starts/ends, status transitions, and notifications — never terminal content or sensitive data. Viewable from Preferences → Audit Log.

```bash
tail -f ~/.claude/claudewatch.log
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[GPL-3.0](LICENSE)

# ClaudeWatch

macOS menu bar app that monitors all your running [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions and lets you switch between them with a click.

## Install

### Homebrew (recommended)

```bash
brew tap wingatethomas/claudewatch
brew install --cask claudewatch
```

### Download Manually

Download the latest `.zip` from the [releases page](https://github.com/wingatethomas/claudewatch/releases/latest), unzip, and drag to `/Applications`.

The app is not notarized, so macOS will block it. Fix with:

```bash
xattr -cr /Applications/ClaudeWatch.app
```

### From Source

```bash
git clone https://github.com/wingatethomas/claudewatch.git
cd claudewatch
uv sync
uv run claudewatch
```

Requires macOS 13+, Python 3.13+, and [uv](https://docs.astral.sh/uv/).

## What It Does

ClaudeWatch shows all active Claude Code sessions in your menu bar, grouped by status:

- **⚠ Attention** (red) — session is waiting for permission or input
- **✦ Working** (green) — Claude is actively running
- **⏸ Idle** (yellow) — session is idle

Click any session to focus its window. Hover for actions: Activity log, Bookmark, Quit.

### Features

- **Multi-environment** — Terminal.app, PyCharm, VS Code, tmux
- **Activity feed** — timeline of user messages, assistant responses, and tool calls
- **Bookmarked sessions** — save sessions to resume later from the Bookmarks submenu
- **Notifications** — native macOS alerts when sessions need attention, with context about what's being asked
- **Session summaries** — auto-generated titles and bulleted action summaries
- **Token usage** — per-session and aggregated usage stats with top sessions breakdown
- **Self-update** — checks GitHub Releases periodically, one-click update from the menu
- **Preferences** — sidebar settings with feature toggles, session history with search/sort/filter, usage dashboard, changelog

### Permissions

ClaudeWatch needs two permissions (prompted on first launch):

| Permission | Why |
|-----------|-----|
| **Accessibility** | Focus terminal windows when you click a session |
| **Automation (Terminal)** | List Terminal.app windows, resume sessions, close tabs |

**Privacy:** ClaudeWatch only reads `~/.claude/` for session data and writes to `~/Library/Application Support/ClaudeWatch/`. It does not access Photos, Music, Documents, or any other personal files.

### How It Works

1. Native `libproc` calls find running Claude processes, TTYs, CWDs, and parent process info
2. PPID chain walking identifies the host app (Terminal, PyCharm, VS Code)
3. For Terminal.app: AppleScript reads window titles and buffers to detect permission prompts
4. For IDEs: JSONL session logs (`~/.claude/projects/`) are checked for pending tool_use requests

### Audit Log

ClaudeWatch writes a rotating audit log to `~/Library/Application Support/ClaudeWatch/claudewatch.log`. Viewable from Preferences.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

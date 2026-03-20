# Contributing to ClaudeWatch

## Setup

```bash
git clone https://github.com/wingatethomas/claudewatch.git
cd claudewatch
uv sync
uv run pre-commit install
```

## Run

```bash
uv run claudewatch
```

## Tests

```bash
uv run pytest -v
```

## Linting

```bash
uv run ruff check .
uv run ruff format .
```

Pre-commit hooks run ruff automatically on each commit.

## Architecture

```
claudewatch/
├── backend/
│   ├── models.py              # Data models: HostApp, SessionStatus, ClaudeSession
│   ├── helpers.py             # Shared utilities: AppleScript, escaping
│   ├── services/              # Business logic
│   │   ├── detection.py       # Session discovery via libproc + AppleScript
│   │   ├── notifications.py   # Native macOS notifications (NSUserNotification)
│   │   ├── procinfo.py        # Native macOS libproc bindings (ctypes)
│   │   ├── usage.py           # Session metadata from JSONL logs (model name)
│   │   └── activity.py        # Session activity timeline from JSONL
│   └── repositories/          # Data persistence
│       ├── config.py          # App settings (~/.claude/claudewatch.json)
│       └── bookmarks.py       # Pinned session bookmarks
└── ui/
    ├── menubar.py             # Menu bar view (rumps NSStatusItem)
    ├── focus.py               # Window focusing (AppleScript, CGEvent)
    ├── preferences.py         # Preferences window (PyObjC NSWindow)
    └── activity.py            # Activity feed window
```

**services/** = business logic (detection, notifications). **repositories/** = data persistence (config, bookmarks). **ui/** = presentation (menu bar, preferences, window focus). **models.py** and **helpers.py** are shared across layers.

## PR Guidelines

- Add tests for new pure-function logic
- Run `uv run ruff check .` before pushing
- Type hints on all new functions
- Keep commits focused — one logical change per commit

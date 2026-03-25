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
│   ├── core/                  # Shared infrastructure (no service/repo/UI imports)
│   │   ├── models.py          # Data models, enums, constants
│   │   ├── dto.py             # BaseDTO + all shared DTOs (*DTO suffix)
│   │   ├── helpers.py         # AppleScript runner, escaping
│   │   ├── paths.py           # Centralized file paths
│   │   ├── base_service.py    # BaseService with import constraint enforcement
│   │   └── services/          # Core services (process, session log)
│   ├── dependencies.py        # Service factory functions (get_*_service())
│   ├── services/              # Domain services (extend BaseService)
│   └── repositories/          # Data persistence
│       ├── config.py          # App settings (infrastructure)
│       ├── bookmarks.py       # Pinned session bookmarks
│       └── history.py         # Session history
└── ui/
    ├── menubar.py             # Menu bar view (AppKit NSStatusBar)
    ├── focus.py               # Window focusing (AppleScript, CGEvent)
    ├── preferences.py         # Preferences window (PyObjC NSWindow)
    ├── welcome.py             # First-launch permissions guide
    └── activity.py            # Activity feed window
```

**Layer rules:** `core/` has no imports from `services/`, `repositories/`, or `ui/`. `services/` can import from `core/` and `repositories/`. `ui/` imports from `services/` and `core/` (DTOs/models only), never `repositories/` (except config, which is infrastructure).

## PR Guidelines

- Add tests for new pure-function logic
- Run `uv run ruff check .` before pushing
- Type hints on all new functions
- Keep commits focused — one logical change per commit

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
│   ├── core/                      # Shared infrastructure — no domain/repo/UI imports
│   │   ├── models.py              # Data models, enums, constants
│   │   ├── dto.py                 # BaseDTO + shared DTOs (*DTO suffix)
│   │   ├── helpers.py             # AppleScript runner, escaping
│   │   ├── paths.py               # Centralized file paths
│   │   ├── base_service.py        # BaseService with import constraint enforcement
│   │   ├── process/               # ProcessService — PID lookup + child PID registry
│   │   │   ├── service.py
│   │   │   ├── dependencies.py
│   │   │   └── procinfo.py        # libproc ctypes bindings
│   │   └── session_log/           # SessionLogService — JSONL discovery/reading
│   │       ├── service.py
│   │       ├── dependencies.py
│   │       └── jsonl.py           # JSONL file operations
│   ├── repositories/              # Data persistence — can import from core/
│   │   ├── config.py              # App settings (infrastructure)
│   │   ├── bookmarks.py           # Pinned session bookmarks
│   │   └── history.py             # Session history
│   ├── detection/                 # DetectionService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── summary/                   # SummaryService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── notifications/             # NotificationService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── onboarding/                # OnboardingService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── updates/                   # UpdateService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── usage/                     # UsageService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── activity/                  # ActivityService
│   │   ├── service.py
│   │   └── dependencies.py
│   ├── bookmark/                  # BookmarkService
│   │   ├── service.py
│   │   └── dependencies.py
│   └── history/                   # HistoryService
│       ├── service.py
│       └── dependencies.py
└── ui/
    ├── menubar.py                 # Menu bar (AppKit NSStatusBar)
    ├── focus.py                   # Window focusing (AppleScript, CGEvent)
    ├── preferences.py             # Preferences window
    ├── welcome.py                 # First-launch permissions guide
    └── activity.py                # Activity feed window
```

Each domain is a package with `service.py` (class extending `BaseService`) and `dependencies.py` (`@lru_cache` factory function). **Layer rules:** `core/` has no imports from domains, repos, or UI. Domains can import from `core/` and `repositories/`. UI imports from domains (via `dependencies.py`) and `core/` (DTOs/models only), never `repositories/` directly (except config, which is infrastructure).

## PR Guidelines

- Add tests for new pure-function logic
- Run `uv run ruff check .` before pushing
- Type hints on all new functions
- Keep commits focused — one logical change per commit

## Layer Structure

```
backend/
├── core/               # Shared infrastructure — no imports from services/ or repositories/
│   ├── models.py       # Data structures, enums, constants (ClaudeSession, SessionStatus, HostApp)
│   ├── dto.py          # BaseDTO + all shared DTOs (frozen dataclasses, suffixed *DTO)
│   ├── helpers.py      # AppleScript runner, escaping, shell utilities
│   ├── paths.py        # Centralized file paths (~/Library/Application Support/ClaudeWatch/)
│   ├── base_service.py # BaseService with ImportConstraint enforcement
│   └── services/       # Core services — can import from core/ only
│       ├── process.py      # ProcessService — PID lookup + child PID registry
│       └── session_log.py  # SessionLogService — JSONL discovery/reading
├── repositories/       # Persistence — can import from core/
│   ├── config.py       # Settings (infrastructure, accessed directly by services)
│   ├── bookmarks.py    # Pinned session bookmarks
│   └── history.py      # Session history
└── services/           # Domain services — can import from core/ and repositories/
    ├── detection.py        # DetectionService
    ├── summary.py          # SummaryService
    ├── updates.py          # UpdateService
    ├── notifications.py    # NotificationService
    ├── onboarding.py       # OnboardingService
    ├── usage.py            # UsageService
    ├── activity.py         # ActivityService
    ├── bookmark.py         # BookmarkService (wraps bookmarks repo for UI)
    └── history.py          # HistoryService (wraps history repo for UI)
```

## Import Rules

| From \ To | core/ | core/services/ | repositories/ | services/ | ui/ |
|-----------|-------|----------------|---------------|-----------|-----|
| **core/** | self | NO | NO | NO | NO |
| **core/services/** | YES | self | NO | NO | NO |
| **repositories/** | YES | NO | self | NO | NO |
| **services/** | YES | YES | YES | self | NO |
| **ui/** | YES (DTOs/models) | NO | **NEVER** | YES | self |

- `BaseService` enforces import constraints at runtime via `ImportConstraint`.
- UI **never** imports from `repositories/` — always goes through a service.
- Config repo is infrastructure — services import it directly (no wrapper needed).

## DTO Convention

- All DTOs are frozen dataclasses inheriting `BaseDTO`, suffixed with `DTO` (e.g. `SessionDTO`, `PinDTO`, `HistoryEntryDTO`).
- DTOs flow across layer boundaries: service → UI, service → service.
- Models (e.g. `ClaudeSession`) live in `core/models.py` and are used internally by services.
- Services return DTOs to external consumers (UI), not raw models or dicts.

## Service Convention

- All services extend `BaseService`.
- Dependencies are injected via constructor (no global singletons).
- Service instances are wired in `main()` and passed to `ClaudeWatchApp`.
- Module-level state (caches, locks, threads) becomes instance state.

## Module Responsibilities

- **models.py** — data structures, enums, path mapping (`cwd_to_proj_key()` / `proj_key_to_cwd()`). Longest-match for hyphenated directory names.
- **paths.py** — centralized app data directory. Auto-migrates legacy files from `~/.claude/claudewatch-*`. Import paths from here, never hardcode.
- **helpers.py** — shared AppleScript runner, escaping, shell utilities.
- **DetectionService** — finds running Claude processes. Runs on background thread, results collected on main thread via `Future.result()`.
- **SummaryService** — conversation summaries via `claude -p`. Max 1 concurrent. Failures tracked per CWD — gives up after 3. Background thread refreshes every 60s.
- **UpdateService** — checks GitHub Releases every 6 hours. Downloads and applies self-updates.
- **NotificationService** — macOS notifications via terminal-notifier.
- **OnboardingService** — first-run tips. One tip per poll cycle.
- **ProcessService** — PID lookup via libproc + child PID registry (shared by detection and summary).
- **SessionLogService** — JSONL discovery, symlink validation, reading.
- **BookmarkService** — pin/unpin/list, wraps bookmarks repo.
- **HistoryService** — record/list/remove, wraps history repo, seeds from JSONL.

## Threading Rules

- All `self.sessions` access happens on the main thread.
- Set `_modal_active = True` during any modal dialog to pause polling. Reset in `finally`.
- Never generate summaries or do I/O during menu build — only read from caches.
- **Session status rule:** Only mark a session IDLE if there is NO action required from the user. If Claude is waiting for tool approval, input, or any response — that's ATTENTION, not IDLE.

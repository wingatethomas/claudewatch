## Layer Structure

```
backend/
├── core/                       # Shared infrastructure — no imports from domains or ui/
│   ├── models.py               # ClaudeSession, enums, constants
│   ├── dto.py                  # BaseDTO + shared DTOs (frozen dataclasses, *DTO suffix)
│   ├── helpers.py              # AppleScript runner, escaping
│   ├── paths.py                # Centralized file paths
│   ├── service.py              # BaseService with ImportConstraint
│   ├── settings.py             # App settings (config — replaces repositories/config.py)
│   ├── features.py             # Feature flags
│   ├── process/                # ProcessService — PID lookup + child PID registry
│   │   ├── service.py
│   │   ├── dependencies.py     # get_process_service()
│   │   └── procinfo.py         # libproc ctypes bindings (implementation detail)
│   └── session_log/            # SessionLogService — JSONL discovery/reading
│       ├── service.py
│       ├── dependencies.py     # get_session_log_service()
│       └── jsonl.py            # JSONL file operations (implementation detail)
├── detection/                  # DetectionService — find running Claude sessions
│   ├── service.py
│   ├── constants.py            # Detection-specific constants
│   └── dependencies.py         # get_detection_service()
├── summary/                    # SummaryService — generate/cache session summaries
│   ├── service.py
│   └── dependencies.py         # get_summary_service()
├── notifications/              # NotificationService — macOS notifications
│   ├── service.py
│   └── dependencies.py         # get_notification_service()
├── onboarding/                 # OnboardingService — first-run tips
│   ├── service.py
│   └── dependencies.py         # get_onboarding_service()
├── updates/                    # UpdateService — GitHub release checker + self-update
│   ├── service.py
│   └── dependencies.py         # get_update_service()
├── usage/                      # UsageService — token counts, model names
│   ├── service.py
│   └── dependencies.py         # get_usage_service()
├── activity/                   # ActivityService — session timeline from JSONL
│   ├── service.py
│   └── dependencies.py         # get_activity_service()
├── bookmark/                   # BookmarkService — pinned session bookmarks
│   ├── service.py
│   ├── repository.py           # Bookmark persistence
│   └── dependencies.py         # get_bookmark_service()
└── history/                    # HistoryService — session history
    ├── service.py
    ├── repository.py           # History persistence
    └── dependencies.py         # get_history_service()
```

## Import Rules

| From \ To | core/ | core/services | domains | ui/ |
|-----------|-------|---------------|---------|-----|
| **core/** | self | NO | NO | NO |
| **core/services** | YES | self | NO | NO |
| **domains** | YES | YES | peers (via deps) | NO |
| **ui/** | YES (DTOs/models) | NO | YES (via deps) | self |

- `BaseService` enforces import constraints at runtime via `ImportConstraint`.
- Config is now in `core/settings.py` — accessible to all layers including UI.
- UI imports services via `get_*_service()` factory functions from each domain's `dependencies.py`.

## Domain Package Convention

Each domain is a Python package with:
- `service.py` — service class extending `BaseService`, receives dependencies via constructor
- `dependencies.py` — `@lru_cache(maxsize=1)` factory function `get_*_service()` that wires dependencies

Dependencies flow through factory functions, not direct construction. Example:
```python
# detection/dependencies.py
@lru_cache(maxsize=1)
def get_detection_service() -> DetectionService:
    return DetectionService(get_process_service(), get_session_log_service())
```

## DTO Convention

- All DTOs inherit `BaseDTO` (frozen dataclass), suffixed with `DTO` (e.g. `PinDTO`, `HistoryEntryDTO`)
- DTOs flow from services to UI across layer boundaries
- `ClaudeSession` from `core/models.py` is the shared session model (not a DTO — it's mutable and used internally)
- Services that wrap repos return DTOs, not raw dicts

## Threading Rules

- All `self.sessions` access happens on the main thread.
- Set `_modal_active = True` during any modal dialog to pause polling. Reset in `finally`.
- Never generate summaries or do I/O during menu build — only read from caches.
- **Session status rule:** Only mark a session IDLE if there is NO action required from the user. If Claude is waiting for tool approval, input, or any response — that's ATTENTION, not IDLE.

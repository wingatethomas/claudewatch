# Service Class Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure backend into `core/` + `services/` with proper service classes, DTOs, a `BaseService` with import constraint enforcement, and strict layer boundaries.

**Architecture:** Three layers with one-way dependencies. `BaseService` enforces constraints at runtime — services cannot import repo internals or UI modules. DTOs (frozen dataclasses suffixed `DTO`) carry data across layer boundaries. Config repo is infrastructure, accessed directly by services. Bookmarks and history get service wrappers for UI consumption.

**Tech Stack:** Python dataclasses (frozen) for DTOs, `ImportConstraint` metaclass for layer enforcement, dependency injection via constructor.

---

## Layer Rules (to be codified in `.claude/rules/architecture.md` before implementation)

```
core/               → no imports from services/ or repositories/ or ui/
core/services/      → can import from core/ only
repositories/       → can import from core/
services/           → can import from core/, core/services/, and repositories/
                    → CANNOT import from ui/ (enforced by BaseService)
ui/                 → can import from services/ and core/ (DTOs/models only)
                    → NEVER imports from repositories/
```

**Enforced at runtime:** `BaseService.__import_constraints__` checks that no service module imports `repositories.*` internals (private functions, `_load`, `_save`) or `ui.*`. Services access repos through their public API only.

## Target Directory Structure

```
backend/
├── core/
│   ├── __init__.py
│   ├── models.py              # ClaudeSession, enums, constants
│   ├── dto.py                 # BaseDTO + all shared DTOs
│   ├── helpers.py             # AppleScript runner, escaping
│   ├── paths.py               # Centralized file paths
│   ├── base_service.py        # BaseService with ImportConstraint
│   └── services/
│       ├── __init__.py
│       ├── process.py         # ProcessService
│       └── session_log.py     # SessionLogService
├── repositories/
│   ├── __init__.py
│   ├── config.py              # Settings persistence (infrastructure, no service wrapper)
│   ├── bookmarks.py           # Pins persistence
│   └── history.py             # Session history persistence
└── services/
    ├── __init__.py
    ├── detection.py            # DetectionService
    ├── summary.py              # SummaryService
    ├── updates.py              # UpdateService
    ├── notifications.py        # NotificationService
    ├── onboarding.py           # OnboardingService
    ├── usage.py                # UsageService
    ├── activity.py             # ActivityService
    ├── bookmark.py             # BookmarkService (wraps bookmarks repo)
    └── history.py              # HistoryService (wraps history repo)
```

## Framework Classes

### BaseService (core/base_service.py)

Adapted from backend-api's `ImportConstraint` pattern. Enforces that service modules cannot import repo internals or UI code.

```python
import importlib

class ImportConstraint:
    __import_constraints__: tuple[str, ...] = ()
    _has_checked: bool = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._has_checked = False

    def __init__(self, *args, **kwargs):
        cls = type(self)
        if not cls._has_checked:
            module = importlib.import_module(cls.__module__)
            for obj in module.__dict__.values():
                if isinstance(obj, type):
                    for fqdn in cls.__import_constraints__:
                        mod_name, class_name = fqdn.rsplit(".", 1)
                        try:
                            constraint_mod = importlib.import_module(mod_name)
                            constraint_cls = getattr(constraint_mod, class_name)
                            if issubclass(obj, constraint_cls):
                                raise ImportError(
                                    f"Service {cls.__module__}.{cls.__name__} "
                                    f"cannot import {obj.__module__}.{obj.__name__}"
                                )
                        except (ModuleNotFoundError, AttributeError):
                            pass
            cls._has_checked = True
        super().__init__(*args, **kwargs)


class BaseService(ImportConstraint):
    """Base class for all services.

    Constraints:
        - Cannot import UI modules
        - View layer depends on services, never the reverse
        - Can depend on other services and repositories
    """
    __import_constraints__ = ()
```

### BaseDTO (core/dto.py)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class BaseDTO:
    """Base class for all DTOs. Immutable by default."""

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)
```

### DTOs

All suffixed with `DTO`:

```python
@dataclass(frozen=True)
class SessionDTO(BaseDTO):
    pid: int
    project: str
    cwd: str
    status: SessionStatus
    host_app: HostApp
    session_id: str
    tty: str
    window_id: int | None
    menu_label: str
    detail_line: str
    task_summary: str
    last_output: str
    needs_attention: bool

@dataclass(frozen=True)
class PinDTO(BaseDTO):
    session_id: str
    project: str
    cwd: str
    note: str
    timestamp: str

@dataclass(frozen=True)
class HistoryEntryDTO(BaseDTO):
    session_id: str
    project: str
    cwd: str
    model: str
    host_app: str
    ended_at: str

@dataclass(frozen=True)
class UpdateDTO(BaseDTO):
    tag: str
    download_url: str

@dataclass(frozen=True)
class ActivityEventDTO(BaseDTO):
    kind: str
    summary: str
    detail: str
    timestamp: str

@dataclass(frozen=True)
class TokenUsageDTO(BaseDTO):
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_write: int
    model: str
    breakdown_lines: tuple[str, ...]  # frozen=True needs immutable
```

## Dependency Graph (post-refactor)

```
ProcessService       → (nothing)
SessionLogService    → core/models
UsageService         → SessionLogService
ActivityService      → SessionLogService
SummaryService       → SessionLogService, ProcessService, config repo
NotificationService  → core/helpers, core/models, config repo
OnboardingService    → config repo, NotificationService
DetectionService     → core/helpers, core/models, SessionLogService, ProcessService
UpdateService        → (nothing, just __version__)
BookmarkService      → bookmarks repo, config repo
HistoryService       → history repo, SessionLogService
```

No circular dependencies. Config repo is infrastructure — services import it directly.

---

## Task 1: Codify layer rules in architecture.md

**Files:**
- Modify: `.claude/rules/architecture.md`

- [ ] **Step 1:** Add layer rules, import constraints, DTO naming convention (`*DTO` suffix), and the rule that UI never imports repositories
- [ ] **Step 2:** Commit: `docs: codify layer rules before service refactor`

---

## Task 2: Create core/ directory, framework classes, move infrastructure

**Files:**
- Create: `claudewatch/backend/core/__init__.py`
- Create: `claudewatch/backend/core/services/__init__.py`
- Create: `claudewatch/backend/core/base_service.py`
- Create: `claudewatch/backend/core/dto.py`
- Create: `tests/test_base_service.py`
- Create: `tests/test_dto.py`
- Move: `backend/models.py` → `backend/core/models.py` (shim at old location)
- Move: `backend/helpers.py` → `backend/core/helpers.py` (shim at old location)
- Move: `backend/paths.py` → `backend/core/paths.py` (shim at old location)

- [ ] **Step 1:** Create directories and `__init__.py` files
- [ ] **Step 2:** Write tests for `BaseService` import constraint enforcement
- [ ] **Step 3:** Write tests for `BaseDTO` construction and immutability
- [ ] **Step 4:** Implement `BaseService` with `ImportConstraint`
- [ ] **Step 5:** Implement `BaseDTO` and all DTO classes (`SessionDTO`, `PinDTO`, `HistoryEntryDTO`, `UpdateDTO`, `ActivityEventDTO`, `TokenUsageDTO`)
- [ ] **Step 6:** Run tests — verify they pass
- [ ] **Step 7:** `git mv` models.py, helpers.py, paths.py to `core/`
- [ ] **Step 8:** Create re-export shims at old locations
- [ ] **Step 9:** Run full test suite — must pass with no changes to consumers
- [ ] **Step 10:** Commit: `feat: add core/ with BaseService, DTOs, move infrastructure`

---

## Task 3: Create ProcessService (core/services/process.py)

**Files:**
- Create: `claudewatch/backend/core/services/process.py`
- Create: `tests/test_process_service.py`

Wraps existing `procinfo.py` ctypes functions + child PID registry (extracted from `summarize.py`).

```python
class ProcessService(BaseService):
    def __init__(self) -> None:
        super().__init__()
        self._child_pids: set[int] = set()
        self._lock = threading.Lock()

    def list_all(self) -> list[dict]: ...
    def get_info(self, pids: list[int]) -> dict[int, dict]: ...
    def get_cwds(self, pids: list[int]) -> dict[int, str]: ...
    def get_ppid(self, pid: int) -> int: ...
    def get_single_info(self, pid: int) -> dict | None: ...
    def register_child(self, pid: int) -> None: ...
    def unregister_child(self, pid: int) -> None: ...
    def get_child_pids(self) -> set[int]: ...
```

- [ ] **Step 1:** Write tests for ProcessService
- [ ] **Step 2:** Implement ProcessService delegating to procinfo functions
- [ ] **Step 3:** Run tests — verify they pass
- [ ] **Step 4:** Commit: `feat: add ProcessService`

---

## Task 4: Create SessionLogService (core/services/session_log.py)

**Files:**
- Create: `claudewatch/backend/core/services/session_log.py`
- Create: `tests/test_session_log_service.py`

Wraps existing `jsonl.py` functions.

```python
class SessionLogService(BaseService):
    def find_most_recent(self, cwd: str) -> str | None: ...
    def is_safe_path(self, path: str) -> bool: ...
    def read_tail(self, path: str, tail_bytes: int = 10240) -> str: ...
    def read_full(self, path: str) -> list[str]: ...
    def get_session_id(self, path: str) -> str: ...
```

- [ ] **Step 1:** Write tests for SessionLogService
- [ ] **Step 2:** Implement SessionLogService delegating to jsonl functions
- [ ] **Step 3:** Run tests — verify they pass
- [ ] **Step 4:** Commit: `feat: add SessionLogService`

---

## Task 5: Convert domain services to classes

Convert each service module to a class extending `BaseService`. Each class encapsulates its module-level state as instance attributes. Dependencies injected via constructor.

**Sub-task 5a: UsageService**
- Modify: `claudewatch/backend/services/usage.py`
- Update: `tests/test_usage.py`, `tests/test_usage_tokens.py`
- Returns `TokenUsageDTO`

**Sub-task 5b: ActivityService**
- Modify: `claudewatch/backend/services/activity.py`
- Update: `tests/test_activity.py`
- Returns `list[ActivityEventDTO]`

**Sub-task 5c: NotificationService**
- Modify: `claudewatch/backend/services/notifications.py`
- Update: `tests/test_notifications.py`
- Accepts `list[SessionDTO]`

**Sub-task 5d: OnboardingService**
- Modify: `claudewatch/backend/services/onboarding.py`
- Update: `tests/test_onboarding.py`
- Uses config repo directly, depends on `NotificationService`

**Sub-task 5e: UpdateService**
- Modify: `claudewatch/backend/services/updates.py`
- Update: `tests/test_updates.py`
- Returns `UpdateDTO | None`

**Sub-task 5f: SummaryService**
- Rename: `summarize.py` → `summary.py`
- Update: `tests/test_summarize.py`, `tests/test_summarize_store.py`
- Depends on `SessionLogService`, `ProcessService`

**Sub-task 5g: DetectionService**
- Modify: `claudewatch/backend/services/detection.py`
- Update: `tests/test_detection.py`, `tests/test_detection_extra.py`
- Returns `list[SessionDTO]`
- Depends on `ProcessService`, `SessionLogService`

**Sub-task 5h: BookmarkService**
- Create: `claudewatch/backend/services/bookmark.py`
- Create: `tests/test_bookmark_service.py`
- Wraps bookmarks repo, returns `list[PinDTO]`

**Sub-task 5i: HistoryService**
- Create: `claudewatch/backend/services/history.py`
- Create: `tests/test_history_service.py`
- Wraps history repo, returns `list[HistoryEntryDTO]`

For each sub-task:
- [ ] Write/update tests
- [ ] Convert to class with constructor DI
- [ ] Update return types to use DTOs
- [ ] Run tests — verify pass
- [ ] Commit per sub-task

---

## Task 6: Wire services and update UI layer

**Files:**
- Modify: `claudewatch/ui/menubar.py` — service instances via constructor, remove all repo imports
- Modify: `claudewatch/ui/preferences.py` — remove repo imports, use services
- Modify: `claudewatch/ui/welcome.py` — use `OnboardingService.mark_welcome_shown()`
- Modify: `claudewatch/ui/activity.py` — use `ActivityService`

Create service wiring in `main()`:

```python
def main() -> None:
    # ... logging setup ...

    process_svc = ProcessService()
    session_log_svc = SessionLogService()
    notification_svc = NotificationService()
    onboarding_svc = OnboardingService(notification_svc)
    usage_svc = UsageService(session_log_svc)
    activity_svc = ActivityService(session_log_svc)
    summary_svc = SummaryService(session_log_svc, process_svc)
    detection_svc = DetectionService(process_svc, session_log_svc)
    update_svc = UpdateService()
    bookmark_svc = BookmarkService()
    history_svc = HistoryService(session_log_svc)

    delegate = _AppDelegate.alloc().init()
    app = ClaudeWatchApp(delegate, ...)
    delegate._app = app
    app.run()
```

- [ ] **Step 1:** Add service parameters to `ClaudeWatchApp.__init__`
- [ ] **Step 2:** Replace all `from claudewatch.backend.repositories.*` imports in UI files
- [ ] **Step 3:** Replace direct function calls with service method calls
- [ ] **Step 4:** Build service wiring in `main()`
- [ ] **Step 5:** Run full test suite
- [ ] **Step 6:** Verify: `grep -r "from claudewatch.backend.repositories" claudewatch/ui/` returns nothing
- [ ] **Step 7:** Commit: `refactor: wire services, remove repo imports from UI`

---

## Task 7: Remove shims and absorbed modules

**Files:**
- Delete: `claudewatch/backend/models.py` (shim)
- Delete: `claudewatch/backend/helpers.py` (shim)
- Delete: `claudewatch/backend/paths.py` (shim)
- Delete: `claudewatch/backend/services/procinfo.py` (absorbed into ProcessService)
- Delete: `claudewatch/backend/services/jsonl.py` (absorbed into SessionLogService)
- Delete: `claudewatch/backend/services/summarize.py` (renamed to summary.py)
- Update: all remaining imports to final paths

- [ ] **Step 1:** Update all imports to use `core/` paths (grep for shim imports)
- [ ] **Step 2:** Delete shims and absorbed files
- [ ] **Step 3:** Run full test suite
- [ ] **Step 4:** Commit: `refactor: remove shims and absorbed modules`

---

## Task 8: Update rules and documentation

**Files:**
- Modify: `.claude/rules/architecture.md` — finalize with new structure
- Modify: `CLAUDE.md` — updated module index
- Modify: `CONTRIBUTING.md` — updated directory tree

- [ ] **Step 1:** Update all docs to reflect final structure
- [ ] **Step 2:** Commit: `docs: finalize architecture docs for service class refactor`

---

## Verification

1. `uv run ruff check .` — lint clean
2. `uv run pytest` — all tests pass
3. `grep -r "from claudewatch.backend.repositories" claudewatch/ui/` — returns nothing
4. `grep -r "from claudewatch.backend.services" claudewatch/backend/core/` — returns nothing
5. `uv run claudewatch` — manual test: icon, polling, submenus, preferences, quit, restart

## Risks

- **Large blast radius** — every import changes. Shim approach mitigates by keeping old imports working during migration.
- **Module-level state → instance state** — services with background threads/caches must be long-lived singletons. Service registry in `main()` handles this.
- **Test patching** — tests that `patch.object(module, "_PATH")` need updating. Do this per-service during conversion.
- **`ImportConstraint` overhead** — check runs once per service class, at first instantiation. Negligible.

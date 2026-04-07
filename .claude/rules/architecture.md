---
paths:
  - "claudewatch/backend/**/*.py"
  - "claudewatch/ui/**/*.py"
---

## Import Rules

| From \ To | core/ | core sub-packages | domains | ui/ |
|-----------|-------|-------------------|---------|-----|
| **core/** | self | NO | NO | NO |
| **core sub-packages** | YES | self | NO | NO |
| **domains** | YES | YES | peers (via deps) | NO |
| **ui/** | YES (models/return types) | NO | YES (via deps) | self |

- Enforced statically via `scripts/audit_imports.py` (runs in CI).
- Two service access patterns:
  - **Constructor injection** for `ClaudeWatchApp` — services passed as keyword args from `main()`, stored as instance attrs. This is the primary pattern for the menubar.
  - **Factory functions** (`get_*_service()`) for standalone UI (preferences panes, activity windows, etc.) that don't have a parent app reference.

## Domain Package Convention

Each domain is a package under `backend/` with at minimum:

- `service.py` — extends `BaseService`, thin facade that delegates to other modules. Never implements persistence or business logic directly.
- `dependencies.py` — `@lru_cache(maxsize=1)` factory function `get_*_service()` that wires constructor args and caches the singleton. This is the only entry point for UI code.

Additional modules as needed:

- `repository.py` — persistence layer (JSON file I/O, database access). Service delegates here for all reads and writes.
- `models.py` — domain-specific data types (ORM model classes, frozen dataclasses, enums, store lifecycle). For DB-backed domains, this includes the SQLAlchemy `Base`, `*Row` classes, and the `Store` class.

Cross-layer DTOs (`BookmarkDTO`, `HistoryEntryDTO`, etc.) live in `core/dto.py` and inherit `BaseDTO`. Domain-internal return types live in the domain's `models.py`.

## Return Type Convention

- Services return frozen dataclasses or named types, never raw dicts.
- Cross-layer types used by UI live in `core/dto.py` and inherit `BaseDTO` (suffixed `DTO`).
- Domain-internal return types (e.g. `ToolUsage`, `AgentInfo`) are frozen dataclasses in the domain's `models.py` — they don't need `BaseDTO` or the `DTO` suffix.
- `ClaudeSession` from `core/models.py` is the shared session model (mutable, internal).

## Encapsulation Rules

- Never access private methods (`_method`) across module boundaries. If a UI pane needs data from a repository, the repository must expose a public method for it.
- The service layer is the public API for each domain. UI code calls the service, the service delegates to the repository. UI should never reach through the service into the repository's internals (`service._repo._private_method()` is a violation).
- When adding new data accessors, add them to the repository as public methods and expose through the service if needed.

## Typing Rules

- All function parameters and return types must have type annotations.
- Never use bare `dict`, `list`, `tuple`, `set` — always parameterize (`dict[str, int]`, `list[str]`).
- Never use `Any`. If the type is truly unknown, use `object`. If it's JSON-shaped, use `dict[str, object]`.
- Use `| None` instead of `Optional`.

## Threading Rules

- All `self.sessions` access happens on the main thread.
- Set `_modal_active = True` during any modal dialog to pause polling. Reset in `finally`.
- Never generate summaries or do I/O during menu build — only read from caches.
- **Session status rule:** Only mark a session IDLE if there is NO action required from the user. If Claude is waiting for tool approval, input, or any response — that's ATTENTION, not IDLE.

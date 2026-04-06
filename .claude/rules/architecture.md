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

Each domain is a package with:
- `service.py` — extends `BaseService`, receives dependencies via constructor
- `dependencies.py` — `@lru_cache(maxsize=1)` factory function `get_*_service()` that wires dependencies

## Return Type Convention

- Services return frozen dataclasses or named types, never raw dicts.
- Cross-layer types used by UI live in `core/dto.py` and inherit `BaseDTO` (suffixed `DTO`).
- Domain-internal return types (e.g. `ToolUsage`, `AgentInfo`) are frozen dataclasses in the domain's `models.py` — they don't need `BaseDTO` or the `DTO` suffix.
- `ClaudeSession` from `core/models.py` is the shared session model (mutable, internal).

## Threading Rules

- All `self.sessions` access happens on the main thread.
- Set `_modal_active = True` during any modal dialog to pause polling. Reset in `finally`.
- Never generate summaries or do I/O during menu build — only read from caches.
- **Session status rule:** Only mark a session IDLE if there is NO action required from the user. If Claude is waiting for tool approval, input, or any response — that's ATTENTION, not IDLE.

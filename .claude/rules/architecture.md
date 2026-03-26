---
paths:
  - "claudewatch/backend/**/*.py"
  - "claudewatch/ui/**/*.py"
---

## Import Rules

| From \ To | core/ | core/services | domains | ui/ |
|-----------|-------|---------------|---------|-----|
| **core/** | self | NO | NO | NO |
| **core/services** | YES | self | NO | NO |
| **domains** | YES | YES | peers (via deps) | NO |
| **ui/** | YES (DTOs/models) | NO | YES (via deps) | self |

- Enforced statically via `scripts/audit_imports.py` (runs in CI).
- UI imports services via `get_*_service()` factory functions from each domain's `dependencies.py`.

## Domain Package Convention

Each domain is a package with:
- `service.py` — extends `BaseService`, receives dependencies via constructor
- `dependencies.py` — `@lru_cache(maxsize=1)` factory function `get_*_service()` that wires dependencies

## DTO Convention

- All DTOs inherit `BaseDTO` (frozen dataclass), suffixed with `DTO`
- DTOs flow from services to UI across layer boundaries
- `ClaudeSession` from `core/models.py` is the shared session model (mutable, internal)
- Services return DTOs, not raw dicts

## Threading Rules

- All `self.sessions` access happens on the main thread.
- Set `_modal_active = True` during any modal dialog to pause polling. Reset in `finally`.
- Never generate summaries or do I/O during menu build — only read from caches.
- **Session status rule:** Only mark a session IDLE if there is NO action required from the user. If Claude is waiting for tool approval, input, or any response — that's ATTENTION, not IDLE.

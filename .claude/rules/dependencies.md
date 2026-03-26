---
paths:
  - "pyproject.toml"
  - "uv.lock"
---

- All dependencies must compile on macOS ARM (Apple Silicon). Verify before adding.
- Use `uv` for dependency management. Never use `pip` directly.
- PyObjC packages are excluded from `pip-audit` (they don't publish to the standard vulnerability DB).
- Pin versions in `pyproject.toml`. Let `uv.lock` handle transitive resolution.
- Briefcase bundles dependencies into the `.app` — any new dependency increases app size and attack surface. Justify additions.

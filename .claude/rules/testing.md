---
paths:
  - "tests/**/*.py"
  - "claudewatch/backend/**/*.py"
---

- All pure functions in `backend/` should have tests.
- CI enforces ≥70% backend coverage (`ui/` and `dependencies.py` files excluded).
- CI runs pip-audit for dependency vulnerability scanning.
- Tests must never call real system commands. Use `unittest.mock.patch` to mock external calls.
- Use `tmp_path` fixture for tests that need filesystem state.
- When mocking `CLAUDE_PROJECTS_DIR`, patch at `claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR` (the module that reads it). If a function also imports it directly, patch both.
- Reset module-level state between tests (e.g. `_host_app_cache.clear()` in `setup_method`).

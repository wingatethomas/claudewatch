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

## Write operations MUST have tests

Any code that writes to user files (JSON config, SQLite, plist) must have tests covering:
- The happy path (write succeeds, file reflects change)
- Missing file (returns False or raises gracefully)
- Preservation (other data in the file is not lost)
- Idempotency where applicable

Never merge code that modifies files in `~/.claude/` or `~/Library/` without test coverage on the write path.

## New preference panes MUST have render tests

Every pane registered in `window.py` must have at least one test in `tests/ui/test_panes.py` that calls `pane.build()` and asserts it returns `NSView` without crashing. Test with both empty data and populated data.

## Verify real file formats before writing parsers

Never assume the structure of Claude Code config files (plugins, blocklist, settings, policy). Read the actual file from `~/.claude/` first and confirm the keys, nesting, and value types. Document the real format in code comments when it differs from what you'd expect.

## LLM output parsing

When parsing output from an LLM (via `claude -p` or any subprocess that calls a model):
- Validate **structurally** (expected format elements present), not **semantically** (checking for specific phrases like "I don't see" or "no activity"). LLM responses are unpredictable — string matching will always miss edge cases.
- Test the parser with realistic bad inputs: empty response, refusal text, echoed prompt, malformed format, partial format (title but no bullets, bullets but no title).
- If the response doesn't match the expected structure, treat it as a failure and retry — don't display it to the user.

## Smoke-test before committing

Before committing a new UI feature:
- Launch the app (`uv run claudewatch`) and verify it doesn't crash on the new pane/view
- Test with both empty data and populated data
- Verify scroll behavior if the content exceeds the viewport
- Check that text doesn't truncate unexpectedly at the actual window width

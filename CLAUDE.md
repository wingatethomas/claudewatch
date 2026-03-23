# ClaudeWatch — Project Rules

## Architecture

- **Layered structure:** `backend/services/` (business logic), `backend/repositories/` (persistence), `ui/` (views).
- **backend/** has no UI imports. Never import from `ui/` in backend code.
- **helpers.py** — shared AppleScript runner, escaping, shell utilities.
- **models.py** — data structures, enums, and path mapping (`cwd_to_proj_key()` / `proj_key_to_cwd()`).
- **jsonl.py** — all JSONL discovery, symlink validation, and reading. Never do inline JSONL file discovery — use `find_most_recent_jsonl()`, `read_jsonl_tail()`, `is_safe_jsonl_path()`.
- **summarize.py** — conversation summaries via `claude -p`. Subprocess calls must use `Popen` with PID tracking (never `shell=True`). Summaries persist to `~/.claude/claudewatch-summaries.json`. Background thread refreshes every 60s. Max 1 concurrent `claude -p`. Own PIDs tracked in `_our_pids` set and filtered from detection.
- **onboarding.py** — feature discovery tips via terminal-notifier. Tracks shown tips and session count in config. One tip per poll cycle.
- `detect_sessions()` runs on a background thread. Results are collected on the main thread via `Future.result()`. All `self.sessions` access happens on the main thread.
- Set `_modal_active = True` during any modal dialog to pause polling. Reset in `finally`.
- Never generate summaries or do I/O during menu build — only read from caches. Background threads handle generation.

## Security

- Never pass user-controlled strings (project names, window titles, paths) to shell commands without validation.
- Session IDs must be validated as UUIDs before use in commands or clipboard content.
- All values interpolated into AppleScript must go through `escape_applescript()` which strips control chars and escapes quotes. Exception: integer values (e.g. `window_id`) verified via `isdigit()` may be interpolated directly — add a comment noting the safety invariant.
- JSONL file reads must validate the resolved path stays within `~/.claude/projects/` via `is_safe_jsonl_path()` in `jsonl.py`.
- Notification content must never include raw terminal buffer data. Only tool names and project names. Truncation limit: 200 chars.
- GitHub Actions must be pinned to commit hashes, not mutable tags. Comment the version for readability (e.g. `actions/checkout@abc123 # v4`).

## Code Style

- Run `uv run ruff check .` and `uv run pytest` before committing.
- Type hints on all functions.

- Conventional commit messages: `feat:`, `fix:`, `refactor:`, `docs:`, `style:`, `test:`, `chore:`.

## Testing

- All pure functions in `backend/` should have tests.
- CI enforces ≥60% backend coverage (`ui/` excluded — requires running macOS app).
- CI runs pip-audit for dependency vulnerability scanning.
- Tests must never call real system commands. Use `unittest.mock.patch` to mock external calls.
- Use `tmp_path` fixture for tests that need filesystem state.
- When mocking `CLAUDE_PROJECTS_DIR`, patch at `claudewatch.backend.services.jsonl.CLAUDE_PROJECTS_DIR` (the module that reads it). If a function also imports it directly, patch both.
- Reset module-level state between tests (e.g. `_host_app_cache.clear()` in `setup_method`).

## macOS-Specific

- Terminal.app AppleScript must be guarded with `if application "Terminal" is running`.
- **Window focus must only raise the target window, never all windows of the app.** For Terminal.app, use `set index of window id X to 1` + `activateWithOptions_(1 << 1)` (without `NSApplicationActivateAllWindows`). Never use `-activate` with terminal-notifier for Terminal.app — use `-execute` with targeted AppleScript instead.
- Always `NSImage.copy()` before calling `setSize_` on images from `NSWorkspace`.
- Pair `NSImage.lockFocus()` with `unlockFocus()` in try/finally.
- Thread-safety: use `threading.Event` or similar guards when background threads update UI objects that may be deallocated (e.g. modal text fields).
- Check `AXIsProcessTrusted()` on launch and show a menu item if permission is missing.

## License

This project is GPL-3.0-or-later. All contributions are subject to the same license.

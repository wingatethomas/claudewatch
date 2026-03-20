# ClaudeWatch — Project Rules

## Architecture

- **Layered structure:** `backend/services/` (business logic), `backend/repositories/` (persistence), `ui/` (views).
- **backend/** has no UI imports. Never import from `ui/` in backend code.
- **helpers.py** is shared across layers — AppleScript runner, escaping, shell utilities.
- **models.py** defines data structures used everywhere.
- All AppleScript string interpolation MUST use `escape_applescript()`. Exception: integer values (e.g. `window_id`) verified via `isdigit()` may be interpolated directly — add a comment noting the safety invariant.
- `detect_sessions()` runs on a background thread. Results are collected on the main thread via `Future.result()`. All `self.sessions` access happens on the main thread.

## Security

- Never pass user-controlled strings (project names, window titles, paths) to shell commands without validation.
- Session IDs must be validated as UUIDs before use in commands or clipboard content.
- All values interpolated into AppleScript must go through `escape_applescript()` which strips control chars and escapes quotes.
- JSONL file reads must validate the resolved path stays within `~/.claude/projects/` via `os.path.realpath()` (symlink traversal protection).
- Notification content must never include raw terminal buffer data. Only tool names and project names. Truncation limit: 200 chars.
- Notifications use `terminal-notifier` (external binary). Resolution prefers trusted Homebrew paths (`/opt/homebrew/bin`, `/usr/local/bin`) before falling back to `shutil.which()`. The fallback is susceptible to PATH hijacking. Will migrate to native `UNUserNotificationCenter` when packaged as a `.app` bundle.

## Code Style

- Run `uv run ruff check .` and `uv run pytest` before committing.
- Type hints on all functions.
- No AI attribution in commits, PRs, code comments, or docs.
- Conventional commit messages: `feat:`, `fix:`, `refactor:`, `docs:`, `style:`, `test:`, `chore:`.

## Testing

- All pure functions in `backend/` should have tests.
- Tests must never call real system commands. Use `unittest.mock.patch` to mock external calls.
- Use `tmp_path` fixture for tests that need filesystem state.
- Reset module-level state between tests (e.g. `_host_app_cache.clear()` in `setup_method`).

## macOS-Specific

- Detection runs on a background thread (`ThreadPoolExecutor`). UI updates must happen on the main thread.
- Terminal.app AppleScript must be guarded with `if application "Terminal" is running`.
- For Terminal.app, use `NSRunningApplication.activateWithOptions_` or `AXRaise` instead of AppleScript `activate` to avoid raising all windows.
- Always `NSImage.copy()` before calling `setSize_` on images from `NSWorkspace`.
- Pair `NSImage.lockFocus()` with `unlockFocus()` in try/finally.
- Check `AXIsProcessTrusted()` on launch and show a menu item if permission is missing.

## License

This project is GPL-3.0-or-later. All contributions are subject to the same license.

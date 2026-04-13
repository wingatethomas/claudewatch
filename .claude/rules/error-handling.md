---
paths:
  - "claudewatch/backend/**/*.py"
  - "claudewatch/ui/**/*.py"
---

- ClaudeWatch is a long-running menu bar process. Unhandled exceptions in polling loops kill the app silently — always catch and log.
- Write errors to the audit log (`~/Library/Application Support/ClaudeWatch/claudewatch.log`) via Python `logging`. Never print to stdout.
- User-facing errors (modal dialogs) are reserved for actions the user initiated (e.g. failed update). Background failures should log and retry on the next poll cycle.
- Never retry in a tight loop. Polling-based services already have a natural retry interval via `NSTimer`.
- If a JSONL file is corrupt or unreadable, skip it and log — never crash the app over one bad session file.
- When calling external CLIs with new flags (`--session-id`, `-r`, etc.), always implement a fallback to the previous behavior after N consecutive failures. Never assume the user's installed version supports new flags. Log a warning when falling back.

## File Writes

- All JSON file mutations must be atomic: write to `path + ".tmp"`, then `os.replace(tmp, path)`. Never write directly to the target file — a crash mid-write corrupts it. See `_atomic_json_write()` in `security/repository.py` and `_save_store()` in `summary/repository.py`.

## Background Threads

- Fire-and-forget daemon threads must have top-level exception safety. Use `_safe_bg(fn)` from `menubar.py` or wrap the thread target in try/except.
- Infinite loops in background threads (e.g. `_bg_refresh_loop`) must wrap each iteration in try/except so one bad iteration doesn't kill the thread. Sleep after exceptions to avoid tight retry loops.
- AppleScript calls must use the timeout parameter (default 10s). A hung Terminal.app must not block the detection thread forever.

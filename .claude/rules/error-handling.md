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

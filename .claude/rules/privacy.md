---
paths:
  - "claudewatch/**/*.py"
---

- ClaudeWatch reads `~/.claude/` session data. Never expose raw JSONL content to the user — only derived metadata (tool names, project names, timestamps, token counts).
- Audit log (`~/Library/Application Support/ClaudeWatch/claudewatch.log`) must never contain session content, user prompts, or assistant responses.
- Notifications must only contain tool names and project names. Never raw terminal buffer data. Truncation limit: 200 chars.
- No network calls except to `api.github.com` for update checks. No telemetry, no analytics, no crash reporting.
- Never add functionality that sends session data off-machine.

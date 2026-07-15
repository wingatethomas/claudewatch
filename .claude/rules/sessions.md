## Session Identity

- Any data or UI surface describing a single session is keyed by `session_id`, never by `cwd` alone — many sessions share one cwd. Resolve a session's JSONL with `SessionLogService.resolve_jsonl(cwd, session_id)`: with a session_id it returns that exact file or None. Never substitute a sibling's file on None for a per-session surface.
- `find_most_recent(cwd)` is only for genuinely per-project surfaces and for legacy entries with an empty session_id.
- UI action payloads carry `session_id|cwd`; parse with a bare-cwd fallback for legacy rows. Stores dedupe and remove by session_id, matching entries without one by cwd (see the bookmark and history repositories for the pattern).

## Session ↔ JSONL Pairing (detection)

- Title match first: a session whose window title contains a known aiTitle owns that file.
- Unmatched sessions pair with the newest UNCLAIMED file either created after the process started or modified after it (resumed sessions append to files born earlier). Each file pairs with at most one session per poll.
- Unpaired sessions display plainly (no borrowed title or session_id) and default to IDLE.
- Absence of evidence is idle: no heuristic may return WORKING or ATTENTION from missing, empty, or unreadable input. Title indicators override JSONL-derived status in both directions.

## Claude Code CLI Contract

- Claude Code (observed at 2.1.170) does not write the assistant tool_use entry to the JSONL until the permission decision is made. JSONL alone cannot detect a waiting permission dialog — Terminal sessions read the visible screen instead (`_get_terminal_buffers` + `_buffer_prompt_line`). IDE-hosted sessions have no readable screen; their prompts are undetectable until the CLI writes something.
- `backend/core/session_log/schema.py` is the only place JSONL discriminator strings appear; all code uses its enums. Tests may write literal JSONL fixtures.
- Run `uv run python scripts/live_smoke.py --pty` before tagging a release. The unit suite mocks every system boundary and cannot detect the outside world drifting; the smoke script fails on drift (dialog wording, tool_use deferral, ghost windows, buffer readability).

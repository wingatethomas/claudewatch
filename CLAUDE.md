# ClaudeWatch

MIT licensed. All contributions are subject to the same license.

## Code Style

- Run `uv run ruff check .` and `uv run pytest` before committing.
- Type hints on all functions.
- Conventional commit messages: `feat:`, `fix:`, `refactor:`, `docs:`, `style:`, `test:`, `chore:`.
- **One branch per domain.** Each distinct feature or bug gets its own branch. Never combine unrelated changes in one branch/PR.

## Rules Index

Path-scoped rules in `.claude/rules/` — only loaded when touching relevant files:

| Rule | Scope | Purpose |
|------|-------|---------|
| `privacy.md` | `claudewatch/**` | Data handling, no telemetry, session content boundaries |
| `security.md` | `backend/**`, `ui/**` | Input validation, AppleScript escaping, JSONL safety |
| `error-handling.md` | `backend/**`, `ui/**` | Crash resilience, logging, retry strategy |
| `architecture.md` | `backend/**`, `ui/**` | Import rules, DTOs, threading |
| `testing.md` | `tests/**`, `backend/**` | Coverage, mocking, fixtures |
| `macos.md` | `ui/**`, detection, notifications | AppKit patterns, PyObjC, window focus |
| `packaging.md` | `pyproject.toml`, icons, release workflow | Briefcase builds, Homebrew tap |
| `dependencies.md` | `pyproject.toml`, `uv.lock` | Dependency policy, ARM compat, `uv` usage |
| `ci.md` | `.github/**`, `pyproject.toml` | Actions pinning, release process |

# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in ClaudeWatch, please report it responsibly.

**Do not open a public issue.**

Instead, email **claudewatch@protonmail.com** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact

You should receive a response within 48 hours. We will work with you to understand and address the issue before any public disclosure.

## Scope

ClaudeWatch runs locally on macOS and interacts with:

- Terminal.app via AppleScript (Automation permission)
- Process table via libproc (Accessibility permission)
- `~/.claude/projects/` (session JSONL files)
- `~/Library/Application Support/ClaudeWatch/` (app data)
- `api.github.com` (update checks, no auth)

Security concerns in any of these areas are in scope.

## Supported Versions

Only the latest release is supported with security updates.

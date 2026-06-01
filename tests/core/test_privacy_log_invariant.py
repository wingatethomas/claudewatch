"""Static check: no log.*() call may pass session-content-bearing values.

privacy.md forbids the audit log from containing session content, prompts,
or assistant responses. Code review catches obvious leaks, but a static
guard catches future regressions.

Scope is intentionally narrow — only attributes that are unambiguously
session content. Broader names like "content" or "message" would false-positive
on log lines that are about something else entirely.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BANNED_ATTRS = frozenset(
    {
        "prompt_text",  # ClaudeSession.prompt_text — tool input snippet
        "prompt_context",  # ClaudeSession.prompt_context — full tool input dump
    }
)

_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "critical", "exception"})

_BACKEND = Path(__file__).resolve().parents[2] / "claudewatch" / "backend"


def _find_log_calls(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _LOG_METHODS:
            calls.append(node)
    return calls


def _banned_attr_in_node(node: ast.AST) -> str | None:
    """Return the first banned attribute access found within ``node``."""
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute) and child.attr in _BANNED_ATTRS:
            return child.attr
    return None


def test_detector_flags_known_bad_pattern() -> None:
    """Self-check: the detector must catch a deliberate violation.

    Without this, a bug that silently returns no violations would let the
    real invariant test pass for the wrong reason.
    """
    bad = "log.info('saw prompt: %s', session.prompt_text)"
    tree = ast.parse(bad)
    calls = _find_log_calls(tree)
    assert len(calls) == 1
    hits = [_banned_attr_in_node(arg) for arg in calls[0].args]
    assert "prompt_text" in hits

    bad_fstring = "log.warning(f'context = {s.prompt_context}')"
    tree = ast.parse(bad_fstring)
    calls = _find_log_calls(tree)
    assert _banned_attr_in_node(calls[0].args[0]) == "prompt_context"


def test_detector_ignores_safe_patterns() -> None:
    """Self-check: ordinary log calls must not trip the detector."""
    safe = "log.info('detected %d sessions', len(sessions))"
    tree = ast.parse(safe)
    calls = _find_log_calls(tree)
    assert all(_banned_attr_in_node(arg) is None for arg in calls[0].args)


def test_no_log_call_references_session_content() -> None:
    violations: list[tuple[str, int, str]] = []
    for path in _BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for call in _find_log_calls(tree):
            # Inspect every argument and keyword to the log call. We deliberately
            # include the format string itself — even a literal mention there
            # would be suspicious.
            for arg in [*call.args, *(kw.value for kw in call.keywords)]:
                banned = _banned_attr_in_node(arg)
                if banned:
                    rel = path.relative_to(_BACKEND.parent.parent)
                    violations.append((str(rel), call.lineno, banned))

    assert not violations, (
        "log.* calls must not reference session-content attributes "
        "(privacy.md). Violations: " + ", ".join(f"{p}:{ln} -> {attr}" for p, ln, attr in violations)
    )

"""Security service — thin facade coordinating repository and notifications."""

from __future__ import annotations

import json
import logging

from claudewatch.backend.core import features
from claudewatch.backend.core.models import ClaudeSession
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.notifications.service import NotificationService
from claudewatch.backend.security.models import DEFAULT_SUSPICIOUS_PATTERNS, SecurityAlert
from claudewatch.backend.security.repository import SecurityRepository

log = logging.getLogger("claudewatch")

_FEATURE_KEY = "security"


class SecurityService(BaseService):
    """Monitors Claude Code config and sessions for security-relevant changes."""

    def __init__(
        self,
        repository: SecurityRepository,
        notification_service: NotificationService,
        session_log_service: SessionLogService,
    ) -> None:
        super().__init__()
        self._repo = repository
        self._notifications = notification_service
        self._session_log = session_log_service
        self._alerted_hashes: set[str] = set()
        self._alerted_pids: set[int] = set()
        self._initialized = False

    def check_config(self) -> list[SecurityAlert]:
        """Check config files for changes against the stored baseline.

        First call stores the baseline and returns no alerts.
        Subsequent calls diff against the baseline and return alerts.
        """
        if not features.is_enabled(_FEATURE_KEY):
            return []
        if not features.get_facet(_FEATURE_KEY, "config_alerts"):
            return []

        current = self._repo.capture_snapshot()

        if not self._initialized:
            baseline = self._repo.load_baseline()
            if baseline is None:
                self._repo.save_baseline(current)
                self._initialized = True
                return []
            self._initialized = True
            alerts = self._repo.diff_snapshots(baseline, current)
        else:
            baseline = self._repo.load_baseline()
            if baseline is None:
                self._repo.save_baseline(current)
                return []
            alerts = self._repo.diff_snapshots(baseline, current)

        if alerts:
            self._repo.save_baseline(current)

        return self._deduplicate(alerts)

    def check_runtime(self, sessions: list[ClaudeSession]) -> list[SecurityAlert]:
        """Check active sessions for runtime security issues."""
        if not features.is_enabled(_FEATURE_KEY):
            return []
        if not features.get_facet(_FEATURE_KEY, "runtime_alerts"):
            return []

        alerts: list[SecurityAlert] = []

        # Evict stale PIDs
        live_pids = {s.pid for s in sessions}
        self._alerted_pids = {p for p in self._alerted_pids if p in live_pids}

        for session in sessions:
            if session.pid in self._alerted_pids:
                continue
            if not session.cwd:
                continue

            # Check permission mode
            perm_mode = self._check_permission_mode(session.cwd)
            if perm_mode and perm_mode != "default":
                alerts.append(
                    SecurityAlert(
                        alert_type="unrestricted_session",
                        severity="critical",
                        title="Claude Security",
                        subtitle="Unrestricted Session",
                        message=f"Session in '{session.project}' running with --dangerously-skip-permissions",
                    )
                )
                self._alerted_pids.add(session.pid)

            # Check suspicious commands
            cmd_alerts = self._check_suspicious_commands(session)
            alerts.extend(cmd_alerts)

        return self._deduplicate(alerts)

    def process_alerts(self, alerts: list[SecurityAlert]) -> None:
        """Send each alert as a macOS notification."""
        if not features.is_enabled(_FEATURE_KEY):
            return

        for alert in alerts:
            self._notifications.send(alert.title, alert.subtitle, alert.message[:200])
            log.info(
                "security.alert type=%s severity=%s message=%s",
                alert.alert_type,
                alert.severity,
                alert.message[:80],
            )

    def _check_permission_mode(self, cwd: str) -> str | None:
        """Read the permission mode from the first few lines of the session JSONL."""
        path = self._session_log.find_most_recent(cwd)
        if not path:
            return None

        try:
            with open(path) as f:
                for i, line in enumerate(f):
                    if i > 10:  # noqa: PLR2004
                        break
                    try:
                        entry = json.loads(line)
                        mode = entry.get("permissionMode")
                        if mode:
                            return str(mode)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            pass
        return None

    def _check_suspicious_commands(self, session: ClaudeSession) -> list[SecurityAlert]:  # noqa: PLR0912
        """Scan recent Bash commands in a session's JSONL for suspicious patterns."""
        path = self._session_log.find_most_recent(session.cwd)
        if not path:
            return []

        tail = self._session_log.read_tail(path, tail_bytes=5120)
        if not tail:
            return []

        alerts: list[SecurityAlert] = []
        for line in tail.strip().splitlines():
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            msg = entry.get("message", {})
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") != "Bash":
                    continue
                inp = block.get("input", {})
                if not isinstance(inp, dict):
                    continue
                command = inp.get("command", "")
                if not isinstance(command, str):
                    continue

                for pattern in DEFAULT_SUSPICIOUS_PATTERNS:
                    if pattern.matches(command):
                        alerts.append(
                            SecurityAlert(
                                alert_type="suspicious_command",
                                severity=pattern.severity,
                                title="Claude Security",
                                subtitle="Suspicious Command",
                                message=f"{pattern.description} in '{session.project}'",
                            )
                        )
                        break  # one alert per command

        return alerts

    def _deduplicate(self, alerts: list[SecurityAlert]) -> list[SecurityAlert]:
        """Filter out alerts that have already been emitted."""
        unique: list[SecurityAlert] = []
        for alert in alerts:
            key = f"{alert.alert_type}:{alert.message}"
            if key not in self._alerted_hashes:
                self._alerted_hashes.add(key)
                unique.append(alert)
        return unique

"""Security service — business logic for config diffing, pattern matching, alerts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from claudewatch.backend.core import features
from claudewatch.backend.core.models import ClaudeSession
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.security.models import (
    DEFAULT_SUSPICIOUS_PATTERNS,
    ConfigSnapshot,
    SecurityAlert,
)
from claudewatch.backend.security.repository import SecurityRepository

if TYPE_CHECKING:
    from claudewatch.backend.core.session_log.service import SessionLogService
    from claudewatch.backend.notifications.service import NotificationService

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

    # -- Config monitoring --------------------------------------------------

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
        baseline = self._repo.load_baseline()

        if baseline is None:
            self._repo.save_baseline(current)
            self._initialized = True
            return []

        self._initialized = True
        alerts = self.diff_snapshots(baseline, current)

        if alerts:
            self._repo.save_baseline(current)

        self.warm_command_cache()

        return self._deduplicate(alerts)

    def check_runtime(self, sessions: list[ClaudeSession]) -> list[SecurityAlert]:
        """Check active sessions for runtime security issues."""
        if not features.is_enabled(_FEATURE_KEY):
            return []
        if not features.get_facet(_FEATURE_KEY, "runtime_alerts"):
            return []

        alerts: list[SecurityAlert] = []

        live_pids = {s.pid for s in sessions}
        self._alerted_pids = {p for p in self._alerted_pids if p in live_pids}

        for session in sessions:
            if session.pid in self._alerted_pids:
                continue
            if not session.cwd:
                continue

            perm_mode = self._repo.check_permission_mode(session.cwd)
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

            cmd_alerts = self.check_suspicious_commands(session.cwd, session.project)
            alerts.extend(cmd_alerts)

        return self._deduplicate(alerts)

    @property
    def repository(self) -> SecurityRepository:
        """Public access to the repository for UI code that needs I/O methods."""
        return self._repo

    # -- Diff logic (pure business logic, no I/O) --------------------------

    def diff_snapshots(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        """Compare two snapshots and return alerts for each detected change."""
        alerts: list[SecurityAlert] = []
        alerts.extend(self._diff_plugins_installed(old, new))
        alerts.extend(self._diff_plugins_enabled(old, new))
        alerts.extend(self._diff_blocklist(old, new))
        alerts.extend(self._diff_marketplaces(old, new))
        alerts.extend(self._diff_policy(old, new))
        alerts.extend(self._diff_permissions(old, new))
        return alerts

    def _diff_plugins_installed(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []
        old_plugins = self._plugin_keys(old.plugins_installed)
        new_plugins = self._plugin_keys(new.plugins_installed)

        for name in new_plugins - old_plugins:
            alerts.append(
                SecurityAlert(
                    alert_type="plugin_installed",
                    severity="info",
                    title="Claude Security",
                    subtitle="Plugin Installed",
                    message=f"Plugin '{name}' was installed",
                )
            )

        for name in old_plugins - new_plugins:
            alerts.append(
                SecurityAlert(
                    alert_type="plugin_uninstalled",
                    severity="info",
                    title="Claude Security",
                    subtitle="Plugin Removed",
                    message=f"Plugin '{name}' was uninstalled",
                )
            )

        return alerts

    def _diff_plugins_enabled(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []
        old_enabled = set(self._enabled_plugins(old.settings))
        new_enabled = set(self._enabled_plugins(new.settings))

        for name in new_enabled - old_enabled:
            alerts.append(
                SecurityAlert(
                    alert_type="plugin_enabled",
                    severity="info",
                    title="Claude Security",
                    subtitle="Plugin Enabled",
                    message=f"Plugin '{name}' was enabled",
                )
            )

        for name in old_enabled - new_enabled:
            alerts.append(
                SecurityAlert(
                    alert_type="plugin_disabled",
                    severity="info",
                    title="Claude Security",
                    subtitle="Plugin Disabled",
                    message=f"Plugin '{name}' was disabled",
                )
            )

        return alerts

    def _diff_blocklist(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []
        old_blocked = set(self._blocklist_keys(old.plugins_blocklist))
        new_blocked = set(self._blocklist_keys(new.plugins_blocklist))

        for name in old_blocked - new_blocked:
            alerts.append(
                SecurityAlert(
                    alert_type="plugin_unblocked",
                    severity="warning",
                    title="Claude Security",
                    subtitle="Plugin Unblocked",
                    message=f"Plugin '{name}' was removed from blocklist",
                )
            )

        return alerts

    def _diff_marketplaces(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []
        old_mkts = set(self._marketplace_names(old.known_marketplaces))
        new_mkts = set(self._marketplace_names(new.known_marketplaces))

        for name in new_mkts - old_mkts:
            alerts.append(
                SecurityAlert(
                    alert_type="marketplace_added",
                    severity="warning",
                    title="Claude Security",
                    subtitle="New Marketplace",
                    message=f"Plugin marketplace '{name}' was registered",
                )
            )

        return alerts

    def _diff_policy(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []

        for key in ("allow_remote_control", "allow_quick_web_setup"):
            old_val = self._get_policy_value(old.policy_limits, key)
            new_val = self._get_policy_value(new.policy_limits, key)
            if old_val != new_val and new_val is True:
                readable = key.replace("_", " ").title()
                alerts.append(
                    SecurityAlert(
                        alert_type="policy_changed",
                        severity="critical",
                        title="Claude Security",
                        subtitle="Policy Changed",
                        message=f"{readable} was enabled",
                    )
                )

        return alerts

    def _diff_permissions(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        alerts: list[SecurityAlert] = []
        old_perms = self._permission_rules(old.settings_local)
        new_perms = self._permission_rules(new.settings_local)

        added = new_perms - old_perms
        if added:
            alerts.append(
                SecurityAlert(
                    alert_type="permission_added",
                    severity="info",
                    title="Claude Security",
                    subtitle="Permission Changed",
                    message=f"{len(added)} new permission rule(s) added",
                )
            )

        return alerts

    # -- Runtime checks -----------------------------------------------------

    def check_suspicious_commands(self, cwd: str, project: str) -> list[SecurityAlert]:
        """Scan recent Bash commands for suspicious patterns."""
        commands = self._repo.read_bash_commands(cwd)
        alerts: list[SecurityAlert] = []
        for command in commands:
            for pattern in DEFAULT_SUSPICIOUS_PATTERNS:
                if pattern.matches(command):
                    alerts.append(
                        SecurityAlert(
                            alert_type="suspicious_command",
                            severity=pattern.severity,
                            title="Claude Security",
                            subtitle="Suspicious Command",
                            message=f"{pattern.description} in '{project}'",
                        )
                    )
                    break
        return alerts

    # -- Public data extraction (no I/O, operates on snapshots) -------------

    def get_plugin_keys(self, snapshot: ConfigSnapshot) -> set[str]:
        """Get all installed plugin names."""
        return self._plugin_keys(snapshot.plugins_installed)

    def get_policy_value(self, snapshot: ConfigSnapshot, key: str) -> bool | None:
        """Get a policy value from a snapshot."""
        return self._get_policy_value(snapshot.policy_limits, key)

    def get_blocklist_entries(self, snapshot: ConfigSnapshot) -> list[dict[str, str]]:
        """Get blocklist entries with plugin name and reason."""
        plugins = snapshot.plugins_blocklist.get("plugins", [])
        if not isinstance(plugins, list):
            return []
        return [e for e in plugins if isinstance(e, dict) and e.get("plugin")]

    # -- Notifications ------------------------------------------------------

    def process_alerts(self, alerts: list[SecurityAlert]) -> None:
        """Send each alert as a macOS notification."""
        if not features.is_enabled(_FEATURE_KEY):
            return

        sound = str(features.get_facet(_FEATURE_KEY, "alert_sound") or "Glass")
        for alert in alerts:
            self._notifications.send(alert.title, alert.subtitle, alert.message[:200], sound=sound)
            log.info(
                "security.alert type=%s severity=%s message=%s",
                alert.alert_type,
                alert.severity,
                alert.message[:80],
            )

    def warm_command_cache(self) -> None:
        """Pre-warm whatis cache with commands from all permission rules."""
        try:
            _, global_rules = self._repo.get_global_permissions()
            project_perms = self._repo.get_all_project_permissions()
            all_commands: list[str] = list(global_rules)
            for _name, _path, rules in project_perms:
                all_commands.extend(rules)
            bases: list[str] = []
            for rule in all_commands:
                if rule.startswith("Bash(") and rule.endswith(")"):
                    inner = rule[5:-1]
                    cmd = inner.split(":*")[0] if ":*" in inner else inner
                    bases.append(cmd)
            if bases:
                self._repo.warm_whatis_cache(bases)
        except Exception:
            log.debug("failed to warm whatis cache", exc_info=True)

    # -- Private helpers ----------------------------------------------------

    def _deduplicate(self, alerts: list[SecurityAlert]) -> list[SecurityAlert]:
        """Filter out alerts that have already been emitted."""
        unique: list[SecurityAlert] = []
        for alert in alerts:
            key = f"{alert.alert_type}:{alert.message}"
            if key not in self._alerted_hashes:
                self._alerted_hashes.add(key)
                unique.append(alert)
        return unique

    # -- Static snapshot extraction helpers ---------------------------------

    @staticmethod
    def _plugin_keys(plugins_data: dict[str, object]) -> set[str]:
        plugins = plugins_data.get("plugins", {})
        if isinstance(plugins, dict):
            return set(plugins.keys())
        return set()

    @staticmethod
    def _enabled_plugins(settings_data: dict[str, object]) -> list[str]:
        enabled = settings_data.get("enabledPlugins", {})
        if isinstance(enabled, dict):
            return [k for k, v in enabled.items() if v]
        return []

    @staticmethod
    def _blocklist_keys(blocklist_data: dict[str, object]) -> list[str]:
        entries = blocklist_data.get("plugins", [])
        if isinstance(entries, list):
            return [
                e.get("plugin", "") or e.get("id", "")
                for e in entries
                if isinstance(e, dict) and (e.get("plugin") or e.get("id"))
            ]
        return []

    @staticmethod
    def _marketplace_names(marketplaces_data: dict[str, object]) -> list[str]:
        mkts = marketplaces_data.get("marketplaces", {})
        if isinstance(mkts, dict):
            return list(mkts.keys())
        return []

    @staticmethod
    def _permission_rules(settings_local: dict[str, object]) -> set[str]:
        perms = settings_local.get("permissions", {})
        if isinstance(perms, dict):
            allow = perms.get("allow", [])
            if isinstance(allow, list):
                return {str(r) for r in allow}
        return set()

    @staticmethod
    def _get_policy_value(policy_data: dict[str, object], key: str) -> bool | None:
        """Extract a policy value, handling both flat and nested formats."""
        val = policy_data.get(key)
        if isinstance(val, bool):
            return val
        restrictions = policy_data.get("restrictions")
        if isinstance(restrictions, dict):
            entry = restrictions.get(key)
            if isinstance(entry, dict):
                allowed = entry.get("allowed")
                if isinstance(allowed, bool):
                    return allowed
        return None

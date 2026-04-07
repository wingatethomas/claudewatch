"""Security repository — config file reads, baseline persistence, diff logic."""

from __future__ import annotations

import json
import logging
import os

from claudewatch.backend.core.settings import get_setting, set_setting
from claudewatch.backend.security.models import ConfigSnapshot, SecurityAlert

log = logging.getLogger("claudewatch")

_CLAUDE_DIR = os.path.expanduser("~/.claude")
_BASELINE_KEY = "security.last_config_snapshot"


class SecurityRepository:
    """Reads Claude config files, persists baselines, and diffs snapshots."""

    def __init__(self, claude_dir: str = _CLAUDE_DIR) -> None:
        self._claude_dir = claude_dir

    # -- Config capture --

    def capture_snapshot(self) -> ConfigSnapshot:
        """Read all monitored config files and return a snapshot."""
        return ConfigSnapshot(
            plugins_installed=self._read_json("plugins/installed_plugins.json"),
            plugins_blocklist=self._read_json("plugins/blocklist.json"),
            settings=self._read_json("settings.json"),
            settings_local=self._read_json("settings.local.json"),
            policy_limits=self._read_json("policy-limits.json"),
            known_marketplaces=self._read_json("plugins/known_marketplaces.json"),
        )

    def _read_json(self, relative_path: str) -> dict[str, object]:
        path = os.path.join(self._claude_dir, relative_path)
        try:
            with open(path) as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

    # -- Baseline persistence --

    def load_baseline(self) -> ConfigSnapshot | None:
        """Load the last-known config snapshot from NSUserDefaults."""
        raw = get_setting(_BASELINE_KEY)
        if not isinstance(raw, dict):
            return None
        return ConfigSnapshot.from_dict(raw)

    def save_baseline(self, snapshot: ConfigSnapshot) -> None:
        """Persist a config snapshot as the new baseline."""
        set_setting(_BASELINE_KEY, snapshot.to_dict())

    # -- Diff logic --

    def diff_snapshots(self, old: ConfigSnapshot, new: ConfigSnapshot) -> list[SecurityAlert]:
        """Compare two snapshots and return alerts for each detected change.

        Pure function — no side effects, no I/O. Highly testable.
        """
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

    @staticmethod
    def _get_policy_value(policy_data: dict[str, object], key: str) -> bool | None:
        """Extract a policy value, handling both flat and nested formats.

        Flat:   {"allow_remote_control": false}
        Nested: {"restrictions": {"allow_remote_control": {"allowed": false}}}
        """
        # Try flat format first
        val = policy_data.get(key)
        if isinstance(val, bool):
            return val

        # Try nested format
        restrictions = policy_data.get("restrictions")
        if isinstance(restrictions, dict):
            entry = restrictions.get(key)
            if isinstance(entry, dict):
                allowed = entry.get("allowed")
                if isinstance(allowed, bool):
                    return allowed

        return None

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

    # -- Permission management --

    def get_all_project_permissions(self) -> list[tuple[str, str, list[str]]]:
        """Find permission rules for all known Claude projects.

        Scans ~/.claude/projects/ for all project keys, resolves each to a CWD,
        and reads .claude/settings.local.json from that CWD.

        Returns list of (project_name, settings_path, rules).
        """
        from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, proj_key_to_cwd  # noqa: PLC0415

        results: list[tuple[str, str, list[str]]] = []
        try:
            entries = os.listdir(CLAUDE_PROJECTS_DIR)
        except OSError:
            return results

        seen_cwds: set[str] = set()
        for proj_key in entries:
            if not os.path.isdir(os.path.join(CLAUDE_PROJECTS_DIR, proj_key)):
                continue
            # Skip worktree entries
            if "--claude-worktrees-" in proj_key:
                continue
            cwd = proj_key_to_cwd(proj_key)
            if cwd in seen_cwds or not os.path.isdir(cwd):
                continue
            seen_cwds.add(cwd)

            settings_path = os.path.join(cwd, ".claude", "settings.local.json")
            if not os.path.isfile(settings_path):
                continue

            rules = self._read_permission_rules(settings_path)
            if rules:
                # Use parent/project to disambiguate projects with the same name
                parent = os.path.basename(os.path.dirname(cwd))
                basename = os.path.basename(cwd)
                project_name = f"{parent}/{basename}" if parent and parent != "/" else basename
                results.append((project_name, settings_path, rules))

        return sorted(results, key=lambda x: x[0])

    def get_global_permissions(self) -> tuple[str, list[str]]:
        """Get global permission rules from ~/.claude/settings.local.json.

        Returns (settings_path, rules).
        """
        path = os.path.join(self._claude_dir, "settings.local.json")
        rules = self._read_permission_rules(path)
        return (path, rules)

    def remove_permission_rule(self, settings_path: str, rule: str) -> bool:
        """Remove a single permission rule from a settings.local.json file."""
        try:
            with open(settings_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False

        perms = data.get("permissions", {})
        if not isinstance(perms, dict):
            return False
        allow = perms.get("allow", [])
        if not isinstance(allow, list) or rule not in allow:
            return False

        allow.remove(rule)
        perms["allow"] = allow
        data["permissions"] = perms

        try:
            with open(settings_path, "w") as f:
                json.dump(data, f, indent=2)
            log.info("security: removed permission rule '%s' from %s", rule[:50], settings_path)
            return True
        except OSError:
            log.warning("security: failed to write %s", settings_path)
            return False

    def clear_permissions(self, settings_path: str) -> bool:
        """Clear all permission rules from a settings.local.json file."""
        try:
            with open(settings_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False

        perms = data.get("permissions", {})
        if not isinstance(perms, dict):
            return False

        perms["allow"] = []
        data["permissions"] = perms

        try:
            with open(settings_path, "w") as f:
                json.dump(data, f, indent=2)
            log.info("security: cleared all permissions from %s", settings_path)
            return True
        except OSError:
            log.warning("security: failed to write %s", settings_path)
            return False

    @staticmethod
    def _read_permission_rules(path: str) -> list[str]:
        """Read permission allow rules from a settings.local.json file."""
        try:
            with open(path) as f:
                data = json.load(f)
            perms = data.get("permissions", {})
            if isinstance(perms, dict):
                allow = perms.get("allow", [])
                if isinstance(allow, list):
                    return [str(r) for r in allow]
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return []

    # -- Plugin management --

    def uninstall_plugin(self, plugin_name: str) -> bool:
        """Remove a plugin from installed_plugins.json and settings.json."""
        success = False

        # Remove from installed_plugins.json
        installed_path = os.path.join(self._claude_dir, "plugins", "installed_plugins.json")
        try:
            with open(installed_path) as f:
                data = json.load(f)
            plugins = data.get("plugins", {})
            if isinstance(plugins, dict) and plugin_name in plugins:
                del plugins[plugin_name]
                data["plugins"] = plugins
                with open(installed_path, "w") as f:
                    json.dump(data, f, indent=2)
                success = True
        except (OSError, json.JSONDecodeError):
            log.warning("security: failed to update installed_plugins.json")

        # Remove from enabledPlugins in settings.json
        settings_path = os.path.join(self._claude_dir, "settings.json")
        try:
            with open(settings_path) as f:
                data = json.load(f)
            enabled = data.get("enabledPlugins", {})
            if isinstance(enabled, dict) and plugin_name in enabled:
                del enabled[plugin_name]
                data["enabledPlugins"] = enabled
                with open(settings_path, "w") as f:
                    json.dump(data, f, indent=2)
        except (OSError, json.JSONDecodeError):
            log.warning("security: failed to update settings.json")

        if success:
            log.info("security: uninstalled plugin '%s'", plugin_name)
        return success

    # -- Helpers --

    @staticmethod
    def _plugin_keys(plugins_data: dict[str, object]) -> set[str]:
        """Extract plugin names from installed_plugins.json structure."""
        plugins = plugins_data.get("plugins", {})
        if isinstance(plugins, dict):
            return set(plugins.keys())
        return set()

    @staticmethod
    def _enabled_plugins(settings_data: dict[str, object]) -> list[str]:
        """Extract enabled plugin names from settings.json."""
        enabled = settings_data.get("enabledPlugins", {})
        if isinstance(enabled, dict):
            return [k for k, v in enabled.items() if v]
        return []

    @staticmethod
    def _blocklist_keys(blocklist_data: dict[str, object]) -> list[str]:
        """Extract blocked plugin identifiers.

        Real format: {"plugins": [{"plugin": "name@marketplace", ...}]}
        """
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
        """Extract marketplace names."""
        mkts = marketplaces_data.get("marketplaces", {})
        if isinstance(mkts, dict):
            return list(mkts.keys())
        return []

    @staticmethod
    def _permission_rules(settings_local: dict[str, object]) -> set[str]:
        """Extract permission allow rules as a set of strings."""
        perms = settings_local.get("permissions", {})
        if isinstance(perms, dict):
            allow = perms.get("allow", [])
            if isinstance(allow, list):
                return {str(r) for r in allow}
        return set()

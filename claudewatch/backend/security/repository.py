"""Security repository — config file reads, baseline persistence, diff logic."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, proj_key_to_cwd
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.core.settings import get_setting, set_setting
from claudewatch.backend.security.models import (
    DEFAULT_SUSPICIOUS_PATTERNS,
    ConfigSnapshot,
    SecurityAlert,
    is_dangerous_permission,
)

log = logging.getLogger("claudewatch")

_CLAUDE_DIR = os.path.expanduser("~/.claude")
_BASELINE_KEY = "security.last_config_snapshot"


class SecurityRepository:
    """Reads Claude config files, persists baselines, and diffs snapshots."""

    _PROJECT_CACHE_TTL = 30.0  # seconds

    def __init__(self, claude_dir: str = _CLAUDE_DIR, session_log: SessionLogService | None = None) -> None:
        self._claude_dir = claude_dir
        self._session_log = session_log
        self._project_perms_cache: list[tuple[str, str, list[str]]] | None = None
        self._project_perms_cache_time: float = 0.0

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

    def get_all_project_permissions(self, *, force: bool = False) -> list[tuple[str, str, list[str]]]:
        """Find permission rules for all known Claude projects.

        Scans ~/.claude/projects/ for all project keys, resolves each to a CWD,
        and reads .claude/settings.local.json from that CWD. Cached for 30 seconds.

        Returns list of (project_name, settings_path, rules).
        """
        now = time.time()
        if (
            not force
            and self._project_perms_cache is not None
            and now - self._project_perms_cache_time < self._PROJECT_CACHE_TTL
        ):
            return self._project_perms_cache

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

        self._project_perms_cache = sorted(results, key=lambda x: x[0])
        self._project_perms_cache_time = now
        return self._project_perms_cache

    def invalidate_project_cache(self) -> None:
        """Force refresh on next get_all_project_permissions call."""
        self._project_perms_cache = None

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
            self.invalidate_project_cache()
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
            self.invalidate_project_cache()
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

    def remove_dangerous_permissions(self, settings_path: str) -> int:
        """Remove all dangerous permissions from a settings.local.json file. Returns count removed."""
        try:
            with open(settings_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0

        perms = data.get("permissions", {})
        if not isinstance(perms, dict):
            return 0
        allow = perms.get("allow", [])
        if not isinstance(allow, list):
            return 0

        original_count = len(allow)
        safe_rules = [r for r in allow if not is_dangerous_permission(str(r))]
        removed = original_count - len(safe_rules)

        if removed > 0:
            perms["allow"] = safe_rules
            data["permissions"] = perms
            try:
                with open(settings_path, "w") as f:
                    json.dump(data, f, indent=2)
                log.info("security: removed %d dangerous permissions from %s", removed, settings_path)
                self.invalidate_project_cache()
            except OSError:
                log.warning("security: failed to write %s", settings_path)
                return 0

        return removed

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

    # -- Public API for pane (no private method access needed) --

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

    # -- Runtime checks (delegated from service) --

    def check_permission_mode(self, cwd: str) -> str | None:
        """Read the permission mode from the first few lines of the session JSONL."""
        path = self._session_log.find_most_recent(cwd) if self._session_log else None
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

    def check_suspicious_commands(self, cwd: str, project: str) -> list[SecurityAlert]:  # noqa: PLR0912
        """Scan recent Bash commands in a session's JSONL for suspicious patterns."""
        if not self._session_log:
            return []
        path = self._session_log.find_most_recent(cwd)
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
                                message=f"{pattern.description} in '{project}'",
                            )
                        )
                        break
        return alerts

    # -- Command descriptions (via man whatis) --

    _whatis_cache: dict[str, str] = {}
    _whatis_warming: bool = False

    @classmethod
    def get_command_description(cls, command: str) -> str:
        """Get a one-line description for a command via whatis. Returns from cache only — never blocks."""
        parts = command.split(maxsplit=1)
        base = parts[0] if parts else command
        return cls._whatis_cache.get(base, "")

    @classmethod
    def warm_whatis_cache(cls, commands: list[str]) -> None:
        """Pre-warm the whatis cache for a list of commands. Call from background thread."""
        if cls._whatis_warming:
            return
        cls._whatis_warming = True
        try:
            unique_bases = {cmd.split(maxsplit=1)[0] for cmd in commands if cmd.split()}
            uncached = [b for b in unique_bases if b not in cls._whatis_cache]
            if not uncached:
                return
            # Batch whatis call — all commands at once
            try:
                result = subprocess.run(
                    ["whatis", *uncached],  # noqa: S603, S607
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.stdout:
                    for line in result.stdout.strip().splitlines():
                        if " - " in line:
                            name_part = line.split("(")[0].strip() if "(" in line else line.split(" - ")[0].strip()
                            desc = line.split(" - ", 1)[1].strip()
                            # Match against our uncached list
                            for base in uncached:
                                if name_part == base or line.startswith(f"{base}("):
                                    cls._whatis_cache[base] = desc
                                    break
            except (OSError, subprocess.TimeoutExpired):
                pass
            # Fill empty entries for commands whatis didn't know
            for base in uncached:
                if base not in cls._whatis_cache:
                    cls._whatis_cache[base] = ""
        finally:
            cls._whatis_warming = False

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

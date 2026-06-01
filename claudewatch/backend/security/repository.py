"""Security repository — config file reads, baseline persistence, cache management."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

from claudewatch.backend.core.helpers import atomic_json_write
from claudewatch.backend.core.paths import CLAUDE_PROJECTS_DIR, proj_key_to_cwd
from claudewatch.backend.core.session_log.schema import BlockType
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.core.settings import get_setting, set_setting
from claudewatch.backend.security.models import ConfigSnapshot, is_dangerous_permission

log = logging.getLogger("claudewatch")

_CLAUDE_DIR = os.path.expanduser("~/.claude")
_BASELINE_KEY = "security.last_config_snapshot"
_WHATIS_SETTINGS_KEY = "security.whatis_cache"


class SecurityRepository:
    """Reads Claude config files, persists baselines, and manages caches."""

    _PROJECT_CACHE_TTL = 30.0  # seconds

    def __init__(self, claude_dir: str = _CLAUDE_DIR, session_log: SessionLogService | None = None) -> None:
        self._claude_dir = claude_dir
        self._session_log = session_log
        self._project_perms_cache: list[tuple[str, str, list[str]]] | None = None
        self._project_perms_cache_time: float = 0.0
        self._whatis_cache: dict[str, str] | None = None
        self._whatis_warming: bool = False

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
            atomic_json_write(settings_path, data)
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
            atomic_json_write(settings_path, data)
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
                atomic_json_write(settings_path, data)
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

        installed_path = os.path.join(self._claude_dir, "plugins", "installed_plugins.json")
        try:
            with open(installed_path) as f:
                data = json.load(f)
            plugins = data.get("plugins", {})
            if isinstance(plugins, dict) and plugin_name in plugins:
                del plugins[plugin_name]
                data["plugins"] = plugins
                atomic_json_write(installed_path, data)
                success = True
        except (OSError, json.JSONDecodeError):
            log.warning("security: failed to update installed_plugins.json")

        settings_path = os.path.join(self._claude_dir, "settings.json")
        try:
            with open(settings_path) as f:
                data = json.load(f)
            enabled = data.get("enabledPlugins", {})
            if isinstance(enabled, dict) and plugin_name in enabled:
                del enabled[plugin_name]
                data["enabledPlugins"] = enabled
                atomic_json_write(settings_path, data)
        except (OSError, json.JSONDecodeError):
            log.warning("security: failed to update settings.json")

        if success:
            log.info("security: uninstalled plugin '%s'", plugin_name)
        return success

    # -- Runtime I/O --

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

    def read_bash_commands(self, cwd: str) -> list[str]:
        """Read Bash commands from the tail of the most recent session JSONL.

        Returns a list of command strings extracted from tool_use blocks.
        """
        if not self._session_log:
            return []
        path = self._session_log.find_most_recent(cwd)
        if not path:
            return []

        tail = self._session_log.read_tail(path, tail_bytes=5120)
        if not tail:
            return []

        commands: list[str] = []
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
                if not isinstance(block, dict) or block.get("type") != BlockType.TOOL_USE:
                    continue
                if block.get("name") != "Bash":
                    continue
                inp = block.get("input", {})
                if not isinstance(inp, dict):
                    continue
                command = inp.get("command", "")
                if isinstance(command, str) and command:
                    commands.append(command)
        return commands

    # -- Command descriptions --

    def _load_whatis_cache(self) -> dict[str, str]:
        if self._whatis_cache is None:
            raw = get_setting(_WHATIS_SETTINGS_KEY)
            self._whatis_cache = dict(raw) if isinstance(raw, dict) else {}
        return self._whatis_cache

    def _save_whatis_cache(self) -> None:
        if self._whatis_cache:
            set_setting(_WHATIS_SETTINGS_KEY, self._whatis_cache)

    def get_command_description(self, command: str) -> str:
        """Get a one-line description for a command from the whatis cache.

        Returns the longest-matching multi-word key (e.g. `gh pr create` before `gh`).
        """
        _max_desc = 40
        words = [w for w in command.split() if "=" not in w]
        if not words:
            return ""
        cache = self._load_whatis_cache()
        for length in range(len(words), 0, -1):
            key = " ".join(words[:length])
            desc = cache.get(key, "")
            if desc:
                return desc[:_max_desc] if len(desc) > _max_desc else desc
        return ""

    def warm_whatis_cache(self, commands: list[str]) -> None:
        """Pre-warm the whatis cache for a list of commands. Call from background thread."""
        if self._whatis_warming:
            return
        self._whatis_warming = True
        try:
            cache = self._load_whatis_cache()
            keys_needed: set[str] = set()

            for cmd in commands:
                words = [w for w in cmd.split() if "=" not in w]
                for length in range(len(words), 0, -1):
                    key = " ".join(words[:length])
                    if key not in cache:
                        keys_needed.add(key)

            for key in keys_needed:
                if key in cache:
                    continue
                words = key.split()
                desc = ""
                for length in range(len(words), 0, -1):
                    hyphenated = "-".join(words[:length])
                    desc = self._lookup_whatis(hyphenated)
                    if desc:
                        break
                cache[key] = desc

            self._save_whatis_cache()
        finally:
            self._whatis_warming = False

    @staticmethod
    def _lookup_whatis(command: str) -> str:
        """Look up a single command via whatis. Returns description or empty string."""
        try:
            result = subprocess.run(
                ["whatis", command],  # noqa: S603, S607
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().splitlines():
                    if line.startswith(f"{command}(") and " - " in line:
                        return line.split(" - ", 1)[1].strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

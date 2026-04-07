"""Tests for SecurityRepository — config capture, baseline persistence, diff logic."""

import json
import os

import pytest

from claudewatch.backend.security.models import ConfigSnapshot
from claudewatch.backend.security.repository import SecurityRepository


@pytest.fixture
def claude_dir(tmp_path: str) -> str:
    """Create a mock ~/.claude/ directory with config files."""
    plugins_dir = os.path.join(tmp_path, "plugins")
    os.makedirs(plugins_dir)

    _write_json(
        os.path.join(plugins_dir, "installed_plugins.json"),
        {
            "version": 2,
            "plugins": {
                "code-review@official": [{"scope": "user", "version": "1.0"}],
                "swift-lsp@official": [{"scope": "user", "version": "1.0"}],
            },
        },
    )
    _write_json(
        os.path.join(plugins_dir, "blocklist.json"),
        {
            "plugins": [{"plugin": "malicious@evil", "reason": "security"}],
        },
    )
    _write_json(
        os.path.join(plugins_dir, "known_marketplaces.json"),
        {
            "marketplaces": {"claude-plugins-official": {"source": "anthropics/claude-plugins-official"}},
        },
    )
    _write_json(
        os.path.join(tmp_path, "settings.json"),
        {
            "enabledPlugins": {"code-review@official": True, "swift-lsp@official": True},
        },
    )
    _write_json(
        os.path.join(tmp_path, "settings.local.json"),
        {
            "permissions": {"allow": ["Bash(python3:*)"]},
        },
    )
    _write_json(
        os.path.join(tmp_path, "policy-limits.json"),
        {
            "allow_remote_control": False,
            "allow_quick_web_setup": False,
        },
    )
    return str(tmp_path)


def _write_json(path: str, data: dict[str, object]) -> None:
    with open(path, "w") as f:
        json.dump(data, f)


class TestCaptureSnapshot:
    def test_reads_all_config_files(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        snap = repo.capture_snapshot()

        assert "plugins" in snap.plugins_installed
        assert "plugins" in snap.plugins_blocklist
        assert "enabledPlugins" in snap.settings
        assert "permissions" in snap.settings_local
        assert "allow_remote_control" in snap.policy_limits
        assert "marketplaces" in snap.known_marketplaces

    def test_handles_missing_files(self, tmp_path: str) -> None:
        repo = SecurityRepository(str(tmp_path))
        snap = repo.capture_snapshot()

        assert snap.plugins_installed == {}
        assert snap.settings == {}
        assert snap.policy_limits == {}

    def test_handles_corrupt_json(self, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "settings.json")
        with open(path, "w") as f:
            f.write("not json {{{")
        repo = SecurityRepository(str(tmp_path))
        snap = repo.capture_snapshot()
        assert snap.settings == {}


class TestConfigSnapshotSerialization:
    def test_roundtrip(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        snap = repo.capture_snapshot()
        restored = ConfigSnapshot.from_dict(snap.to_dict())

        assert restored.plugins_installed == snap.plugins_installed
        assert restored.settings == snap.settings
        assert restored.policy_limits == snap.policy_limits

    def test_from_dict_handles_empty(self) -> None:
        snap = ConfigSnapshot.from_dict({})
        assert snap.plugins_installed == {}

    def test_from_dict_handles_non_dict(self) -> None:
        snap = ConfigSnapshot.from_dict("garbage")  # type: ignore[arg-type]
        assert snap.plugins_installed == {}


class TestDiffSnapshots:
    def test_no_changes(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        snap = repo.capture_snapshot()
        alerts = repo.diff_snapshots(snap, snap)
        assert alerts == []

    def test_plugin_installed(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "plugins/installed_plugins.json"),
            {
                "version": 2,
                "plugins": {
                    "code-review@official": [{"scope": "user"}],
                    "swift-lsp@official": [{"scope": "user"}],
                    "new-plugin@sketchy": [{"scope": "user"}],
                },
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "plugin_installed"
        assert "new-plugin@sketchy" in alerts[0].message

    def test_plugin_uninstalled(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "plugins/installed_plugins.json"),
            {
                "version": 2,
                "plugins": {"code-review@official": [{"scope": "user"}]},
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "plugin_uninstalled"
        assert "swift-lsp" in alerts[0].message

    def test_plugin_enabled(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "settings.json"),
            {
                "enabledPlugins": {
                    "code-review@official": True,
                    "swift-lsp@official": True,
                    "superpowers@official": True,
                },
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert any(a.alert_type == "plugin_enabled" for a in alerts)
        assert any("superpowers" in a.message for a in alerts)

    def test_plugin_disabled(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "settings.json"),
            {
                "enabledPlugins": {"code-review@official": True},
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert any(a.alert_type == "plugin_disabled" for a in alerts)

    def test_plugin_unblocked(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(os.path.join(claude_dir, "plugins/blocklist.json"), {"plugins": []})
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "plugin_unblocked"
        assert alerts[0].severity == "warning"

    def test_new_marketplace(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "plugins/known_marketplaces.json"),
            {
                "marketplaces": {
                    "claude-plugins-official": {},
                    "sketchy-marketplace": {"source": "unknown/repo"},
                },
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert any(a.alert_type == "marketplace_added" for a in alerts)
        assert any("sketchy-marketplace" in a.message for a in alerts)

    def test_remote_control_enabled_flat(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "policy-limits.json"),
            {
                "allow_remote_control": True,
                "allow_quick_web_setup": False,
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "policy_changed"
        assert alerts[0].severity == "critical"

    def test_remote_control_enabled_nested(self, claude_dir: str) -> None:
        """Real format: restrictions.allow_remote_control.allowed."""
        _write_json(
            os.path.join(claude_dir, "policy-limits.json"),
            {
                "restrictions": {
                    "allow_remote_control": {"allowed": False},
                    "allow_quick_web_setup": {"allowed": False},
                },
            },
        )
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "policy-limits.json"),
            {
                "restrictions": {
                    "allow_remote_control": {"allowed": True},
                    "allow_quick_web_setup": {"allowed": False},
                },
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "policy_changed"
        assert alerts[0].severity == "critical"

    def test_remote_control_stays_false(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)
        assert not any(a.alert_type == "policy_changed" for a in alerts)

    def test_permission_added(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        _write_json(
            os.path.join(claude_dir, "settings.local.json"),
            {
                "permissions": {"allow": ["Bash(python3:*)", "Bash(rm -rf:*)"]},
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        assert any(a.alert_type == "permission_added" for a in alerts)

    def test_multiple_changes(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        old = repo.capture_snapshot()

        # Plugin installed + remote control enabled
        _write_json(
            os.path.join(claude_dir, "plugins/installed_plugins.json"),
            {
                "version": 2,
                "plugins": {
                    "code-review@official": [{}],
                    "swift-lsp@official": [{}],
                    "evil-plugin@bad": [{}],
                },
            },
        )
        _write_json(
            os.path.join(claude_dir, "policy-limits.json"),
            {
                "allow_remote_control": True,
            },
        )
        new = repo.capture_snapshot()
        alerts = repo.diff_snapshots(old, new)

        types = {a.alert_type for a in alerts}
        assert "plugin_installed" in types
        assert "policy_changed" in types


class TestRemovePermissionRule:
    def test_removes_single_rule(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        settings_path = os.path.join(claude_dir, "settings.local.json")
        assert repo.remove_permission_rule(settings_path, "Bash(python3:*)")

        rules = repo._read_permission_rules(settings_path)
        assert "Bash(python3:*)" not in rules

    def test_returns_false_for_missing_rule(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        settings_path = os.path.join(claude_dir, "settings.local.json")
        assert not repo.remove_permission_rule(settings_path, "Bash(nonexistent:*)")

    def test_returns_false_for_missing_file(self, tmp_path: str) -> None:
        repo = SecurityRepository(str(tmp_path))
        assert not repo.remove_permission_rule("/nonexistent/path.json", "rule")

    def test_preserves_other_rules(self, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "settings.local.json")
        _write_json(path, {"permissions": {"allow": ["rule1", "rule2", "rule3"]}})
        repo = SecurityRepository(str(tmp_path))
        repo.remove_permission_rule(path, "rule2")

        rules = repo._read_permission_rules(path)
        assert rules == ["rule1", "rule3"]


class TestClearPermissions:
    def test_clears_all_rules(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        settings_path = os.path.join(claude_dir, "settings.local.json")
        assert repo.clear_permissions(settings_path)

        rules = repo._read_permission_rules(settings_path)
        assert rules == []

    def test_returns_false_for_missing_file(self, tmp_path: str) -> None:
        repo = SecurityRepository(str(tmp_path))
        assert not repo.clear_permissions("/nonexistent/path.json")

    def test_preserves_other_settings(self, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "settings.local.json")
        _write_json(path, {"permissions": {"allow": ["rule1"]}, "other_key": "value"})
        repo = SecurityRepository(str(tmp_path))
        repo.clear_permissions(path)

        with open(path) as f:
            data = json.load(f)
        assert data["other_key"] == "value"
        assert data["permissions"]["allow"] == []


class TestRemoveDangerousPermissions:
    def test_removes_dangerous_only(self, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "settings.local.json")
        _write_json(
            path,
            {
                "permissions": {
                    "allow": [
                        "Bash(rm:*)",
                        "Bash(sudo:*)",
                        "Bash(uv run pytest:*)",
                        "Bash(git checkout:*)",
                    ],
                },
            },
        )
        repo = SecurityRepository(str(tmp_path))
        removed = repo.remove_dangerous_permissions(path)

        assert removed == 2
        rules = repo._read_permission_rules(path)
        assert "Bash(uv run pytest:*)" in rules
        assert "Bash(git checkout:*)" in rules
        assert "Bash(rm:*)" not in rules
        assert "Bash(sudo:*)" not in rules

    def test_returns_zero_when_no_dangerous(self, tmp_path: str) -> None:
        path = os.path.join(tmp_path, "settings.local.json")
        _write_json(path, {"permissions": {"allow": ["Bash(uv run:*)"]}})
        repo = SecurityRepository(str(tmp_path))
        assert repo.remove_dangerous_permissions(path) == 0

    def test_returns_zero_for_missing_file(self, tmp_path: str) -> None:
        repo = SecurityRepository(str(tmp_path))
        assert repo.remove_dangerous_permissions("/nonexistent.json") == 0


class TestUninstallPlugin:
    def test_removes_from_installed(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        assert repo.uninstall_plugin("swift-lsp@official")

        snap = repo.capture_snapshot()
        plugins = snap.plugins_installed.get("plugins", {})
        assert "swift-lsp@official" not in plugins
        assert "code-review@official" in plugins  # others preserved

    def test_removes_from_enabled(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        repo.uninstall_plugin("swift-lsp@official")

        snap = repo.capture_snapshot()
        enabled = snap.settings.get("enabledPlugins", {})
        assert "swift-lsp@official" not in enabled

    def test_returns_false_for_unknown_plugin(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        assert not repo.uninstall_plugin("nonexistent@fake")


class TestPublicAPI:
    def test_get_plugin_keys(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        snap = repo.capture_snapshot()
        keys = repo.get_plugin_keys(snap)
        assert "code-review@official" in keys
        assert "swift-lsp@official" in keys

    def test_get_policy_value(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        snap = repo.capture_snapshot()
        assert repo.get_policy_value(snap, "allow_remote_control") is False

    def test_get_blocklist_entries(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        snap = repo.capture_snapshot()
        entries = repo.get_blocklist_entries(snap)
        assert len(entries) == 1
        assert entries[0]["plugin"] == "malicious@evil"

    def test_get_global_permissions(self, claude_dir: str) -> None:
        repo = SecurityRepository(claude_dir)
        path, rules = repo.get_global_permissions()
        assert "Bash(python3:*)" in rules
        assert path.endswith("settings.local.json")

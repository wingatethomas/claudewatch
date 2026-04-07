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
            "entries": [{"id": "malicious@evil", "reason": "security"}],
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
        assert "entries" in snap.plugins_blocklist
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

        _write_json(os.path.join(claude_dir, "plugins/blocklist.json"), {"entries": []})
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

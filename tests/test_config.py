"""Tests for claudewatch.backend.core.settings — NSUserDefaults backend."""

import json
from unittest.mock import patch

from claudewatch.backend.core import settings as config


class _FakeDefaults:
    """In-memory stand-in for NSUserDefaults."""

    def __init__(self):
        self._store: dict[str, object] = {}

    def objectForKey_(self, key: str) -> object:  # noqa: N802
        return self._store.get(key)

    def setObject_forKey_(self, value: object, key: str) -> None:  # noqa: N802
        self._store[key] = value

    def removeObjectForKey_(self, key: str) -> None:  # noqa: N802
        self._store.pop(key, None)

    def dictionaryRepresentation(self) -> dict:  # noqa: N802
        return dict(self._store)


class TestGetSetSetting:
    def setup_method(self) -> None:
        self._fake = _FakeDefaults()
        self._patcher = patch.object(config, "_defaults", self._fake)
        self._patcher.start()

    def teardown_method(self) -> None:
        self._patcher.stop()

    def test_get_returns_default_when_not_set(self):
        assert config.get_setting("notifications_enabled") is True
        assert config.get_setting("poll_interval") == 1

    def test_set_then_get(self):
        config.set_setting("poll_interval", 5)
        assert config.get_setting("poll_interval") == 5

    def test_get_unknown_key_returns_none(self):
        assert config.get_setting("nonexistent_key") is None

    def test_get_available_sounds(self):
        sounds = config.get_available_sounds()
        assert "Glass" in sounds
        assert isinstance(sounds, tuple)


class TestMigration:
    def setup_method(self) -> None:
        self._fake = _FakeDefaults()
        self._patcher = patch.object(config, "_defaults", self._fake)
        self._patcher.start()

    def teardown_method(self) -> None:
        self._patcher.stop()

    def test_migrates_json_on_first_run(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"poll_interval": 7, "custom": "val"}))

        with patch.object(config, "_LEGACY_SETTINGS_PATH", str(settings_file)):
            config._migrate_from_json()

        assert self._fake.objectForKey_("com.claudewatch.poll_interval") == 7
        assert self._fake.objectForKey_("com.claudewatch.custom") == "val"
        assert not settings_file.exists() or settings_file.with_suffix(".json.migrated").exists()

    def test_skips_migration_when_no_json(self, tmp_path):
        with patch.object(config, "_LEGACY_SETTINGS_PATH", str(tmp_path / "nope.json")):
            config._migrate_from_json()
        assert self._fake.objectForKey_("com.claudewatch.poll_interval") is None

    def test_skips_migration_when_already_migrated(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"poll_interval": 7}))
        self._fake.setObject_forKey_(True, "com.claudewatch._migrated")

        with patch.object(config, "_LEGACY_SETTINGS_PATH", str(settings_file)):
            config._migrate_from_json()

        assert self._fake.objectForKey_("com.claudewatch.poll_interval") is None

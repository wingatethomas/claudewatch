"""Tests for claudewatch.backend.repositories.config — full coverage."""

import json
from unittest.mock import patch

from claudewatch.backend.repositories import config


class TestConfigLoadSave:
    def setup_method(self) -> None:
        config._cache = None

    def test_load_from_file(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"notifications_enabled": False, "custom_key": "value"}))
        config._cache = None
        with patch.object(config, "_SETTINGS_PATH", str(settings_file)):
            result = config._load()
        assert result["notifications_enabled"] is False
        assert result["custom_key"] == "value"
        # Defaults still present
        assert "poll_interval" in result

    def test_load_missing_file(self, tmp_path):
        config._cache = None
        with patch.object(config, "_SETTINGS_PATH", str(tmp_path / "nope.json")):
            result = config._load()
        assert result == dict(config._DEFAULTS)

    def test_load_corrupt_file(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{corrupt")
        config._cache = None
        with patch.object(config, "_SETTINGS_PATH", str(settings_file)):
            result = config._load()
        assert result == dict(config._DEFAULTS)

    def test_load_caches(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"poll_interval": 5}))
        config._cache = None
        with patch.object(config, "_SETTINGS_PATH", str(settings_file)):
            r1 = config._load()
            r2 = config._load()
        assert r1 is r2

    def test_save_writes_to_disk(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        config._cache = {"test_key": "test_value"}
        with patch.object(config, "_SETTINGS_PATH", str(settings_file)):
            config._save()
        with open(settings_file) as f:
            data = json.load(f)
        assert data["test_key"] == "test_value"

    def test_save_with_none_cache(self):
        config._cache = None
        config._save()  # should not raise


class TestGetSetSetting:
    def setup_method(self) -> None:
        config._cache = None

    def test_get_setting(self, tmp_path):
        config._cache = None
        with patch.object(config, "_SETTINGS_PATH", str(tmp_path / "nope.json")):
            assert config.get_setting("notifications_enabled") is True
            assert config.get_setting("poll_interval") == 1

    def test_set_setting(self, tmp_path):
        settings_file = tmp_path / "settings.json"
        config._cache = None
        with patch.object(config, "_SETTINGS_PATH", str(settings_file)):
            config.set_setting("poll_interval", 5)
            assert config.get_setting("poll_interval") == 5

    def test_get_available_sounds(self):
        sounds = config.get_available_sounds()
        assert "Glass" in sounds
        assert isinstance(sounds, tuple)

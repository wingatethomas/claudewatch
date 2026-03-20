"""Tests for claudewatch.backend.repositories.config."""

import json
from unittest.mock import patch

from claudewatch.backend.repositories import config


class TestConfigDefaults:
    """Config should return sensible defaults when no file exists."""

    def setup_method(self):
        config._cache = None

    def test_default_notifications_enabled(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("notifications_enabled") is True

    def test_default_poll_interval(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("poll_interval") == 2

    def test_default_notification_sound(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("notification_sound") == "Glass"

    def test_unknown_key_returns_none(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("nonexistent_key") is None


class TestConfigGetSet:
    """Config get/set round-trips correctly."""

    def setup_method(self):
        config._cache = None

    def test_set_then_get(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            config.set_setting("poll_interval", 5)
            assert config.get_setting("poll_interval") == 5

    def test_set_persists_to_disk(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            config.set_setting("notifications_enabled", False)

            # Read file directly to verify persistence
            with open(fake_path) as f:
                data = json.load(f)
            assert data["notifications_enabled"] is False

    def test_set_new_key(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            config.set_setting("custom_key", "custom_value")
            assert config.get_setting("custom_key") == "custom_value"

    def test_load_from_existing_file(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with open(fake_path, "w") as f:
            json.dump({"poll_interval": 10, "notification_sound": "Ping"}, f)

        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("poll_interval") == 10
            assert config.get_setting("notification_sound") == "Ping"
            # Defaults still available for unset keys
            assert config.get_setting("notifications_enabled") is True

    def test_load_from_corrupt_json(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with open(fake_path, "w") as f:
            f.write("{corrupt json!!!")

        with patch.object(config, "_SETTINGS_PATH", fake_path):
            # Should fall back to defaults
            assert config.get_setting("notifications_enabled") is True
            assert config.get_setting("poll_interval") == 2


class TestConfigCache:
    """Config uses a module-level cache to avoid re-reading."""

    def setup_method(self):
        config._cache = None

    def test_cache_is_populated_after_first_load(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config._cache is None
            config.get_setting("poll_interval")
            assert config._cache is not None

    def test_cache_prevents_rereading_file(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with open(fake_path, "w") as f:
            json.dump({"poll_interval": 7}, f)

        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("poll_interval") == 7

            # Overwrite the file behind the cache's back
            with open(fake_path, "w") as f:
                json.dump({"poll_interval": 99}, f)

            # Cache should still return old value
            assert config.get_setting("poll_interval") == 7

    def test_cache_reset_allows_reloading(self, tmp_path):
        fake_path = str(tmp_path / "claudewatch.json")
        with open(fake_path, "w") as f:
            json.dump({"poll_interval": 7}, f)

        with patch.object(config, "_SETTINGS_PATH", fake_path):
            assert config.get_setting("poll_interval") == 7

            # Update file and reset cache
            with open(fake_path, "w") as f:
                json.dump({"poll_interval": 99}, f)
            config._cache = None

            assert config.get_setting("poll_interval") == 99


class TestAvailableSounds:
    """available_sounds() returns the expected tuple of macOS sounds."""

    def test_returns_tuple(self):
        result = config.get_available_sounds()
        assert isinstance(result, tuple)

    def test_contains_glass(self):
        assert "Glass" in config.get_available_sounds()

    def test_contains_all_expected_sounds(self):
        sounds = config.get_available_sounds()
        expected = ("Glass", "Blow", "Bottle", "Frog", "Funk", "Hero",
                    "Morse", "Ping", "Pop", "Purr", "Submarine", "Tink")
        assert sounds == expected

    def test_immutable(self):
        """Tuple is immutable — callers cannot accidentally mutate."""
        sounds = config.get_available_sounds()
        assert type(sounds) is tuple


class TestSaveFailure:
    """_save handles OSError gracefully when file cannot be written."""

    def setup_method(self):
        config._cache = None

    def test_set_with_unwritable_path(self, tmp_path):
        # Use a path inside a non-existent directory
        fake_path = str(tmp_path / "nonexistent_dir" / "claudewatch.json")
        with patch.object(config, "_SETTINGS_PATH", fake_path):
            # Should not raise — the error is logged but swallowed
            config.set_setting("poll_interval", 5)
            # Value is still in the in-memory cache
            assert config.get_setting("poll_interval") == 5

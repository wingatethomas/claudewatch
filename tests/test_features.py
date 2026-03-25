"""Tests for the feature flag registry."""

from unittest.mock import patch

from claudewatch.backend.core import features
from claudewatch.backend.core.features import Facet, Feature


class TestFeatureRegistry:
    def setup_method(self) -> None:
        features._registry.clear()

    def test_register_and_get_all(self):
        f = Feature(key="test", description="A test feature")
        features.register(f)
        assert features.get_all() == [f]

    def test_register_duplicate_overwrites(self):
        f1 = Feature(key="test", description="v1")
        f2 = Feature(key="test", description="v2")
        features.register(f1)
        features.register(f2)
        assert len(features.get_all()) == 1
        assert features.get_all()[0].description == "v2"

    def test_get_all_returns_copy(self):
        features.register(Feature(key="a", description="A"))
        result = features.get_all()
        result.clear()
        assert len(features.get_all()) == 1


class TestFeatureEnabled:
    """Uses a dict to mock get_setting/set_setting from core.settings."""

    def setup_method(self) -> None:
        features._registry.clear()
        self._store: dict[str, object] = {}
        self._get_patcher = patch(
            "claudewatch.backend.core.features.get_setting",
            side_effect=self._store.get,
        )
        self._set_patcher = patch(
            "claudewatch.backend.core.features.set_setting",
            side_effect=self._store.__setitem__,
        )
        self._get_patcher.start()
        self._set_patcher.start()

    def teardown_method(self) -> None:
        self._get_patcher.stop()
        self._set_patcher.stop()

    def test_default_enabled(self):
        features.register(Feature(key="x", description="X", default_enabled=True))
        assert features.is_enabled("x") is True

    def test_default_disabled(self):
        features.register(Feature(key="x", description="X", default_enabled=False))
        assert features.is_enabled("x") is False

    def test_set_enabled(self):
        features.register(Feature(key="x", description="X", default_enabled=True))
        features.set_enabled("x", False)
        assert features.is_enabled("x") is False

    def test_is_enabled_unregistered_returns_false(self):
        assert features.is_enabled("nonexistent") is False


class TestFacets:
    def setup_method(self) -> None:
        features._registry.clear()
        self._store: dict[str, object] = {}
        self._get_patcher = patch(
            "claudewatch.backend.core.features.get_setting",
            side_effect=self._store.get,
        )
        self._set_patcher = patch(
            "claudewatch.backend.core.features.set_setting",
            side_effect=self._store.__setitem__,
        )
        self._get_patcher.start()
        self._set_patcher.start()

    def teardown_method(self) -> None:
        self._get_patcher.stop()
        self._set_patcher.stop()

    def test_get_facet_default(self):
        features.register(Feature(
            key="notif",
            description="Notifications",
            facets=(Facet("sound", "choice", "Glass", options=("Glass", "Ping")),),
        ))
        assert features.get_facet("notif", "sound") == "Glass"

    def test_set_and_get_facet(self):
        features.register(Feature(
            key="notif",
            description="Notifications",
            facets=(Facet("sound", "choice", "Glass", options=("Glass", "Ping")),),
        ))
        features.set_facet("notif", "sound", "Ping")
        assert features.get_facet("notif", "sound") == "Ping"

    def test_get_facet_unregistered_feature(self):
        assert features.get_facet("nope", "x") is None

    def test_get_facet_unregistered_facet(self):
        features.register(Feature(key="x", description="X"))
        assert features.get_facet("x", "nope") is None

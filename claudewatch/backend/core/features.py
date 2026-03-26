"""Feature flag registry — domains self-register features and configurable facets.

Storage is backed by core.settings (NSUserDefaults). Keys:
    feature.{key}.enabled  → bool
    feature.{key}.{facet}  → value
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from claudewatch.backend.core.settings import get_setting, set_setting

log = logging.getLogger("claudewatch")

_registry: dict[str, Feature] = {}


@dataclass(frozen=True)
class Facet:
    name: str
    type: str  # "bool", "int", "choice", "str"
    default: bool | int | str
    description: str = ""
    options: tuple[str, ...] = ()
    min_val: int | None = None
    max_val: int | None = None


@dataclass(frozen=True)
class Feature:
    key: str
    description: str
    default_enabled: bool = True
    facets: tuple[Facet, ...] = ()


def register(feature: Feature) -> None:
    """Register a feature. Overwrites if key already exists."""
    _registry[feature.key] = feature


def get_all() -> list[Feature]:
    """Return all registered features (ordered by registration)."""
    return list(_registry.values())


def is_enabled(key: str) -> bool:
    """Check if a feature is enabled. Returns False for unregistered features."""
    feature = _registry.get(key)
    if feature is None:
        log.warning("is_enabled called for unregistered feature: %s", key)
        return False
    val = get_setting(f"feature.{key}.enabled")
    if val is not None:
        return bool(val)
    return feature.default_enabled


def set_enabled(key: str, enabled: bool) -> None:
    """Set whether a feature is enabled."""
    set_setting(f"feature.{key}.enabled", enabled)


def get_facet(key: str, facet_name: str) -> bool | int | str | None:
    """Get a facet value. Returns None if feature or facet is unregistered."""
    feature = _registry.get(key)
    if feature is None:
        log.warning("get_facet called for unregistered feature: %s", key)
        return None
    facet = next((f for f in feature.facets if f.name == facet_name), None)
    if facet is None:
        return None
    val = get_setting(f"feature.{key}.{facet_name}")
    if val is not None:
        return val
    return facet.default


def set_facet(key: str, facet_name: str, value: bool | int | str) -> None:
    """Set a facet value."""
    set_setting(f"feature.{key}.{facet_name}", value)

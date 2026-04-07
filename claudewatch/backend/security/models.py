"""Security models — alerts, config snapshots, suspicious command patterns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class SecurityAlert:
    """A single security finding to surface to the user."""

    alert_type: str  # e.g. "plugin_installed", "unrestricted_session"
    severity: str  # "info", "warning", "critical"
    title: str
    subtitle: str
    message: str  # max 200 chars, no raw content
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


@dataclass
class ConfigSnapshot:
    """Point-in-time snapshot of Claude Code config files for diffing.

    Internal to the security domain — never crosses to UI.
    All fields are typed dicts parsed from JSON files.
    """

    plugins_installed: dict[str, object] = field(default_factory=dict)
    plugins_blocklist: dict[str, object] = field(default_factory=dict)
    settings: dict[str, object] = field(default_factory=dict)
    settings_local: dict[str, object] = field(default_factory=dict)
    policy_limits: dict[str, object] = field(default_factory=dict)
    known_marketplaces: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, dict[str, object]]:
        return {
            "plugins_installed": self.plugins_installed,
            "plugins_blocklist": self.plugins_blocklist,
            "settings": self.settings,
            "settings_local": self.settings_local,
            "policy_limits": self.policy_limits,
            "known_marketplaces": self.known_marketplaces,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ConfigSnapshot:
        if not isinstance(data, dict):
            return cls()
        return cls(
            plugins_installed=data.get("plugins_installed", {}) or {},  # type: ignore[arg-type]
            plugins_blocklist=data.get("plugins_blocklist", {}) or {},  # type: ignore[arg-type]
            settings=data.get("settings", {}) or {},  # type: ignore[arg-type]
            settings_local=data.get("settings_local", {}) or {},  # type: ignore[arg-type]
            policy_limits=data.get("policy_limits", {}) or {},  # type: ignore[arg-type]
            known_marketplaces=data.get("known_marketplaces", {}) or {},  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SuspiciousPattern:
    """A regex pattern to match against Bash commands."""

    pattern: str
    description: str
    severity: str  # "warning" or "critical"
    _compiled: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_compiled", re.compile(self.pattern))

    def matches(self, command: str) -> bool:
        return bool(self._compiled.search(command))


DEFAULT_SUSPICIOUS_PATTERNS: tuple[SuspiciousPattern, ...] = (
    SuspiciousPattern(r"rm\s+-rf\s+/", "Recursive delete from root", "critical"),
    SuspiciousPattern(r"curl\s+.*\|\s*(ba)?sh", "Piping curl to shell", "warning"),
    SuspiciousPattern(r"wget\s+.*\|\s*(ba)?sh", "Piping wget to shell", "warning"),
    SuspiciousPattern(r"chmod\s+777\s+", "Setting 777 permissions", "warning"),
    SuspiciousPattern(r"chmod\s+\+s\s+", "Setting setuid bit", "critical"),
    SuspiciousPattern(r"eval\s+\$\(curl", "Eval remote code", "critical"),
    SuspiciousPattern(r">/dev/sda", "Writing to raw device", "critical"),
    SuspiciousPattern(r"mkfs\.", "Formatting filesystem", "critical"),
    SuspiciousPattern(r"dd\s+if=.*of=/dev/", "dd to raw device", "critical"),
)

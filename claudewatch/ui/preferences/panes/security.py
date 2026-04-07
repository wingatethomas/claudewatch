"""Security pane — visibility into Claude Code's trust surface."""

from __future__ import annotations

import os

import objc
from AppKit import (
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSScrollView,
    NSSwitch,
    NSView,
)
from Foundation import NSMakeRect

from claudewatch.backend.core import features
from claudewatch.backend.security.dependencies import get_security_service
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

_MAX_RULE_LEN = 55
_FEATURE_KEY = "security"


class SecurityPane(BasePane):
    """Security pane showing Claude Code config and trust surface."""

    @property
    def title(self) -> str:
        return "Security"

    @property
    def subtitle(self) -> str:
        return "Claude Code plugins, policies, and permissions"

    def build_content(self, view: NSView, content_top: float) -> None:  # noqa: PLR0912, PLR0915
        repo = get_security_service()._repo
        snapshot = repo.capture_snapshot()

        _row_h = 20
        _card_pad = Spacing.LG

        scroll_h = content_top
        plugins_data = snapshot.plugins_installed.get("plugins", {})
        plugin_count = len(plugins_data) if isinstance(plugins_data, dict) else 0
        blocklist_entries = self._get_blocklist_entries(snapshot)
        perm_rules = repo._permission_rules(snapshot.settings_local)
        mkt_names = repo._marketplace_names(snapshot.known_marketplaces)

        # Estimate content height
        content_h = 0
        content_h += 80  # toggles section
        content_h += _card_pad + max(plugin_count, 1) * _row_h + _card_pad + 30
        content_h += _card_pad + 2 * _row_h + _card_pad + 30  # policies
        if blocklist_entries:
            content_h += _card_pad + len(blocklist_entries) * _row_h + _card_pad + 30
        if perm_rules:
            content_h += _card_pad + len(perm_rules) * _row_h + _card_pad + 30
        if mkt_names:
            content_h += _card_pad + len(mkt_names) * _row_h + _card_pad + 30
        content_h += Spacing.XL * 6

        inner_h = max(scroll_h, content_h)
        inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, inner_h))
        y = inner_h

        # Alert toggles at the top
        y -= Spacing.SM
        y = self._add_section_header(inner, "MONITORING", y)
        toggles_h = _card_pad + 2 * 28 + _card_pad
        toggles_card = card(self.card_width, toggles_h)
        toggles_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - toggles_h, self.card_width, toggles_h))
        inner.addSubview_(toggles_card)
        toggle_content = toggles_card.contentView()
        toggle_y = toggles_h - _card_pad

        for facet_name, facet_label in [
            ("config_alerts", "Config change alerts"),
            ("runtime_alerts", "Runtime security alerts"),
        ]:
            toggle_y -= 28
            facet_text = label(facet_label, size=Font.SECONDARY)
            facet_text.setFrame_(NSMakeRect(_card_pad, toggle_y + 4, 250, 18))
            toggle_content.addSubview_(facet_text)

            switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(self.card_width - _card_pad - 46, toggle_y + 2, 46, 22))
            val = features.get_facet(_FEATURE_KEY, facet_name)
            switch.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
            switch.setIdentifier_(f"{_FEATURE_KEY}|{facet_name}")
            switch.setTarget_(self.delegate)
            switch.setAction_(objc.selector(self.delegate.facetBoolChanged_, signature=b"v@:@"))
            toggle_content.addSubview_(switch)

        y -= toggles_h + Spacing.MD

        # Installed plugins
        y = self._add_section_header(inner, "INSTALLED PLUGINS", y)
        if isinstance(plugins_data, dict) and plugins_data:
            card_h = _card_pad + len(plugins_data) * _row_h + _card_pad
            plugins_card = card(self.card_width, card_h)
            plugins_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - card_h, self.card_width, card_h))
            inner.addSubview_(plugins_card)
            plugins_content = plugins_card.contentView()
            row_y = card_h - _card_pad

            for name, entries in plugins_data.items():
                row_y -= _row_h
                short_name = name.split("@")[0] if "@" in name else name
                name_label = label(short_name, size=Font.SECONDARY)
                name_label.setFrame_(NSMakeRect(_card_pad, row_y, 140, 16))
                plugins_content.addSubview_(name_label)

                meta = self._format_plugin_meta(entries)
                if meta:
                    meta_label = secondary_label(meta, size=Font.SMALL)
                    meta_label.setFrame_(NSMakeRect(150, row_y, self.card_width - 170, 16))
                    plugins_content.addSubview_(meta_label)

            y -= card_h + Spacing.MD
        else:
            empty = secondary_label("No plugins installed", size=Font.SECONDARY)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, y - 20, self.card_width, 16))
            inner.addSubview_(empty)
            y -= 20 + Spacing.MD

        # Policies
        y = self._add_section_header(inner, "POLICIES", y)
        policy_h = _card_pad + 2 * _row_h + _card_pad
        policy_card = card(self.card_width, policy_h)
        policy_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - policy_h, self.card_width, policy_h))
        inner.addSubview_(policy_card)
        policy_content = policy_card.contentView()
        policy_y = policy_h - _card_pad

        for key, display_name in [
            ("allow_remote_control", "Remote Control"),
            ("allow_quick_web_setup", "Quick Web Setup"),
        ]:
            policy_y -= _row_h
            val = repo._get_policy_value(snapshot.policy_limits, key)
            status = "Enabled" if val else "Disabled"
            color = theme.danger if val else theme.secondary

            key_label = label(display_name, size=Font.SECONDARY)
            key_label.setFrame_(NSMakeRect(_card_pad, policy_y, 160, 16))
            policy_content.addSubview_(key_label)

            val_label = label(status, size=Font.SECONDARY, bold=True, color=color)
            val_label.setFrame_(NSMakeRect(180, policy_y, 100, 16))
            policy_content.addSubview_(val_label)

        y -= policy_h + Spacing.MD

        # Blocklisted plugins (with reasons)
        if blocklist_entries:
            y = self._add_section_header(inner, "BLOCKLISTED PLUGINS", y)
            blocked_h = _card_pad + len(blocklist_entries) * _row_h + _card_pad
            blocked_card = card(self.card_width, blocked_h)
            blocked_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - blocked_h, self.card_width, blocked_h))
            inner.addSubview_(blocked_card)
            blocked_content = blocked_card.contentView()
            blocked_y = blocked_h - _card_pad

            for entry in blocklist_entries:
                blocked_y -= _row_h
                plugin_name = entry.get("plugin", "unknown")
                short = plugin_name.split("@")[0] if "@" in plugin_name else plugin_name
                reason = entry.get("reason", "")
                display = f"{short}  —  {reason}" if reason else short

                blocked_label = label(display, size=Font.SECONDARY, color=theme.danger)
                blocked_label.setFrame_(NSMakeRect(_card_pad, blocked_y, self.card_width - _card_pad * 2, 16))
                blocked_content.addSubview_(blocked_label)

            y -= blocked_h + Spacing.MD

        # Permission rules (truncated)
        if perm_rules:
            y = self._add_section_header(inner, "PERMISSION RULES", y)
            rules_h = _card_pad + len(perm_rules) * _row_h + _card_pad
            rules_card = card(self.card_width, rules_h)
            rules_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - rules_h, self.card_width, rules_h))
            inner.addSubview_(rules_card)
            rules_content = rules_card.contentView()
            rules_y = rules_h - _card_pad

            for rule in sorted(perm_rules):
                rules_y -= _row_h
                display_rule = rule if len(rule) <= _MAX_RULE_LEN else rule[: _MAX_RULE_LEN - 1] + "…"
                rule_label = secondary_label(display_rule, size=Font.SMALL)
                rule_label.setFrame_(NSMakeRect(_card_pad, rules_y, self.card_width - _card_pad * 2, 16))
                rules_content.addSubview_(rule_label)

            y -= rules_h + Spacing.MD

        # Marketplaces
        if mkt_names:
            y = self._add_section_header(inner, "PLUGIN MARKETPLACES", y)
            mkt_h = _card_pad + len(mkt_names) * _row_h + _card_pad
            mkt_card = card(self.card_width, mkt_h)
            mkt_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - mkt_h, self.card_width, mkt_h))
            inner.addSubview_(mkt_card)
            mkt_content = mkt_card.contentView()
            mkt_y = mkt_h - _card_pad

            for name in mkt_names:
                mkt_y -= _row_h
                mkt_label = label(name, size=Font.SECONDARY)
                mkt_label.setFrame_(NSMakeRect(_card_pad, mkt_y, self.card_width - _card_pad * 2, 16))
                mkt_content.addSubview_(mkt_label)

            y -= mkt_h + Spacing.MD

        # Scroll
        if content_h <= scroll_h:
            inner.setFrame_(NSMakeRect(0, 0, self.width, scroll_h))
            view.addSubview_(inner)
        else:
            scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, scroll_h))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutohidesScrollers_(True)
            scroll.setDrawsBackground_(False)
            scroll.setDocumentView_(inner)
            inner.scrollPoint_((0, inner_h))
            view.addSubview_(scroll)

    def _add_section_header(self, container: NSView, text: str, y: float) -> float:
        header = label(text, size=Font.CAPTION, color=theme.tertiary)
        header.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width, 14))
        container.addSubview_(header)
        return y - 14 - Spacing.XS

    @staticmethod
    def _format_plugin_meta(entries: object) -> str:
        """Format plugin metadata: scope (with project name for local) + install date."""
        if not isinstance(entries, list) or not entries:
            return ""
        entry = entries[0] if isinstance(entries[0], dict) else {}
        scope = entry.get("scope", "")
        installed = entry.get("installedAt", "")[:10]

        if scope == "local":
            project_path = entry.get("projectPath", "")
            project_name = os.path.basename(project_path) if project_path else ""
            scope_display = f"project: {project_name}" if project_name else "project-scoped"
        elif scope == "user":
            scope_display = "global"
        else:
            scope_display = scope

        parts = [p for p in [scope_display, installed] if p]
        return " · ".join(parts)

    @staticmethod
    def _get_blocklist_entries(snapshot: object) -> list[dict[str, str]]:
        """Get blocklist entries with plugin name and reason."""
        blocklist = snapshot.plugins_blocklist
        if not isinstance(blocklist, dict):
            return []
        plugins = blocklist.get("plugins", [])
        if not isinstance(plugins, list):
            return []
        return [e for e in plugins if isinstance(e, dict) and e.get("plugin")]

"""Security pane — visibility into Claude Code's trust surface."""

from __future__ import annotations

from AppKit import NSScrollView, NSView
from Foundation import NSMakeRect

from claudewatch.backend.security.dependencies import get_security_service
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme


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
        # Estimate content height
        plugin_count = len(repo._plugin_keys(snapshot.plugins_installed))
        blocked_count = len(repo._blocklist_keys(snapshot.plugins_blocklist))
        policy_count = 2  # remote_control + web_setup
        perm_rules = repo._permission_rules(snapshot.settings_local)
        mkt_names = repo._marketplace_names(snapshot.known_marketplaces)

        content_h = 0
        content_h += _card_pad + max(plugin_count, 1) * _row_h + _card_pad + 30  # plugins
        content_h += _card_pad + max(policy_count, 1) * _row_h + _card_pad + 30  # policies
        if blocked_count:
            content_h += _card_pad + blocked_count * _row_h + _card_pad + 30
        if perm_rules:
            content_h += _card_pad + len(perm_rules) * _row_h + _card_pad + 30
        if mkt_names:
            content_h += _card_pad + len(mkt_names) * _row_h + _card_pad + 30
        content_h += Spacing.XL * 5

        inner_h = max(scroll_h, content_h)
        inner = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, inner_h))
        y = inner_h

        # Installed plugins card
        y -= Spacing.SM
        y = self._add_section_header(inner, "INSTALLED PLUGINS", y)

        plugins_data = snapshot.plugins_installed.get("plugins", {})
        if isinstance(plugins_data, dict) and plugins_data:
            card_h = _card_pad + len(plugins_data) * _row_h + _card_pad
            plugins_card = card(self.card_width, card_h)
            plugins_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - card_h, self.card_width, card_h))
            inner.addSubview_(plugins_card)
            content_view = plugins_card.contentView()
            row_y = card_h - _card_pad

            for name, entries in plugins_data.items():
                row_y -= _row_h
                short_name = name.split("@")[0] if "@" in name else name
                name_label = label(short_name, size=Font.SECONDARY)
                name_label.setFrame_(NSMakeRect(_card_pad, row_y, 160, 16))
                content_view.addSubview_(name_label)

                # Extract install date and scope
                meta = ""
                if isinstance(entries, list) and entries:
                    entry = entries[0] if isinstance(entries[0], dict) else {}
                    scope = entry.get("scope", "")
                    installed = entry.get("installedAt", "")[:10]
                    parts = [p for p in [scope, installed] if p]
                    meta = " · ".join(parts)

                if meta:
                    meta_label = secondary_label(meta, size=Font.SMALL)
                    meta_label.setFrame_(NSMakeRect(180, row_y, self.card_width - 200, 16))
                    content_view.addSubview_(meta_label)

            y -= card_h + Spacing.MD
        else:
            empty = secondary_label("No plugins installed", size=Font.SECONDARY)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, y - 20, self.card_width, 16))
            inner.addSubview_(empty)
            y -= 20 + Spacing.MD

        # Policies card
        y = self._add_section_header(inner, "POLICIES", y)
        policy_h = _card_pad + policy_count * _row_h + _card_pad
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

        # Blocklisted plugins
        blocked = repo._blocklist_keys(snapshot.plugins_blocklist)
        if blocked:
            y = self._add_section_header(inner, "BLOCKLISTED PLUGINS", y)
            blocked_h = _card_pad + len(blocked) * _row_h + _card_pad
            blocked_card = card(self.card_width, blocked_h)
            blocked_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - blocked_h, self.card_width, blocked_h))
            inner.addSubview_(blocked_card)
            blocked_content = blocked_card.contentView()
            blocked_y = blocked_h - _card_pad

            for name in blocked:
                blocked_y -= _row_h
                blocked_label = label(name, size=Font.SECONDARY, color=theme.danger)
                blocked_label.setFrame_(NSMakeRect(_card_pad, blocked_y, self.card_width - _card_pad * 2, 16))
                blocked_content.addSubview_(blocked_label)

            y -= blocked_h + Spacing.MD

        # Permission rules
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
                rule_label = secondary_label(rule, size=Font.SMALL)
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

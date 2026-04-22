"""Security pane — visibility into Claude Code's trust surface."""

from __future__ import annotations

import os

import objc
from AppKit import (
    NSButton,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
    NSPopUpButton,
    NSSwitch,
    NSView,
)
from Foundation import NSMakeRect

from claudewatch.backend.core import features
from claudewatch.backend.security.dependencies import get_security_service
from claudewatch.backend.security.models import is_dangerous_permission
from claudewatch.ui.components.layout import VStack
from claudewatch.ui.components.tokens import Font, Spacing
from claudewatch.ui.components.widgets.cards import card
from claudewatch.ui.components.widgets.labels import label, secondary_label
from claudewatch.ui.preferences.panes.common import CONTENT_PADDING, BasePane
from claudewatch.ui.theme import theme

_MAX_RULE_LEN = 70
_FEATURE_KEY = "security"
_ROW_H = 20
_TALL_ROW_H = 36
_CARD_PAD = Spacing.LG


class SecurityPane(BasePane):
    """Security pane showing Claude Code config and trust surface."""

    @property
    def title(self) -> str:
        return "Security"

    @property
    def subtitle(self) -> str:
        return "Claude Code plugins, policies, and permissions"

    def build_content(self, view: NSView, content_top: float) -> None:  # noqa: PLR0915
        svc = get_security_service()
        repo = svc.repository
        snapshot = repo.capture_snapshot()

        plugins_data = snapshot.plugins_installed.get("plugins", {})
        blocklist_entries = svc.get_blocklist_entries(snapshot)
        global_path, global_rules_list = repo.get_global_permissions()
        global_rules = set(global_rules_list)
        project_perms = repo.get_all_project_permissions()

        stack = VStack(width=self.width, padding=CONTENT_PADDING, spacing=Spacing.SM, v_padding=Spacing.XS)

        # Monitoring toggles
        stack.add(self._build_section_header("MONITORING"), height=14)
        _toggle_row_h = 42
        _dropdown_row_h = 34
        stack.add(self._build_toggles_card(), height=_CARD_PAD + 2 * _toggle_row_h + 2 * _dropdown_row_h + _CARD_PAD)

        # Installed plugins
        stack.add(self._build_section_header("INSTALLED PLUGINS"), height=14)
        if isinstance(plugins_data, dict) and plugins_data:
            card_h = _CARD_PAD + len(plugins_data) * _ROW_H + _CARD_PAD
            stack.add(self._build_plugins_card(plugins_data), height=card_h)
        else:
            empty = secondary_label("No plugins installed", size=Font.SECONDARY)
            stack.add(empty, height=18)

        # Policies
        stack.add(self._build_section_header("POLICIES"), height=14)
        policy_note = secondary_label("Managed by Claude Code · edit in ~/.claude/policy-limits.json", size=Font.SMALL)
        stack.add(policy_note, height=14)
        policies = [
            ("allow_remote_control", "Remote Control", "External tools can send commands to Claude"),
            ("allow_quick_web_setup", "Quick Web Setup", "Browser-based Claude configuration"),
        ]
        policy_h = _CARD_PAD + len(policies) * _TALL_ROW_H + _CARD_PAD
        stack.add(self._build_policies_card(svc, snapshot, policies), height=policy_h)

        # Blocklisted plugins
        if blocklist_entries:
            fetched_at = snapshot.plugins_blocklist.get("fetchedAt", "")
            fetched_date = str(fetched_at)[:10] if fetched_at else "unknown"
            stack.add(self._build_section_header("BLOCKLISTED PLUGINS"), height=14)
            stack.add(self._build_blocklist_source(fetched_date), height=14)
            blocked_h = _CARD_PAD + len(blocklist_entries) * _TALL_ROW_H + _CARD_PAD
            stack.add(self._build_blocklist_card(svc, snapshot, blocklist_entries), height=blocked_h)

        # Permissions
        total_perm_rows = 0
        scope_count = (1 if global_rules else 0) + len(project_perms)
        if global_rules:
            total_perm_rows += 1 + len(global_rules)
        for _name, _path, rules in project_perms:
            total_perm_rows += 1 + len(rules)
        if total_perm_rows > 0:
            stack.add(self._build_section_header("PERMISSIONS"), height=14)
            scope_gaps = max(scope_count - 1, 0) * Spacing.SM
            perm_h = _CARD_PAD + total_perm_rows * _ROW_H + scope_gaps + _CARD_PAD
            stack.add(
                self._build_permissions_card(global_path, global_rules, project_perms),
                height=perm_h,
            )

        # Marketplaces
        marketplaces_data = snapshot.known_marketplaces
        if isinstance(marketplaces_data, dict) and marketplaces_data:
            stack.add(self._build_section_header("PLUGIN MARKETPLACES"), height=14)
            mkt_h = _CARD_PAD + len(marketplaces_data) * _TALL_ROW_H + _CARD_PAD
            stack.add(self._build_marketplaces_card(marketplaces_data), height=mkt_h)

        scroll = stack.to_scroll_view(max_height=content_top)
        scroll.setFrame_(NSMakeRect(0, 0, self.width, content_top))
        view.addSubview_(scroll)

    # -- Section builders (each returns an NSView) --

    @staticmethod
    def _build_section_header(text: str) -> NSView:
        return label(text, size=Font.CAPTION, color=theme.tertiary)

    def _build_toggles_card(self) -> NSView:
        _toggle_row_h = 42
        _dropdown_row_h = 34
        bool_toggles = [
            ("config_alerts", "Config change alerts", "Plugin installs, policy changes, new permissions"),
            ("runtime_alerts", "Runtime security alerts", "Unrestricted sessions, suspicious commands"),
        ]
        dropdowns = [
            ("check_interval", "Check interval", ("10s", "30s", "60s", "5m")),
            ("alert_sound", "Alert sound", ("Glass", "Blow", "Funk", "Hero", "Ping", "Pop", "Purr", "Submarine")),
        ]
        card_h = _CARD_PAD + len(bool_toggles) * _toggle_row_h + len(dropdowns) * _dropdown_row_h + _CARD_PAD
        toggle_card = card(self.card_width, card_h)
        content = toggle_card.contentView()
        row_y = card_h - _CARD_PAD

        for facet_name, facet_label, description in bool_toggles:
            row_y -= _toggle_row_h
            text = label(facet_label, size=Font.SECONDARY, bold=True)
            text.setFrame_(NSMakeRect(_CARD_PAD, row_y + 22, 300, 16))
            content.addSubview_(text)

            desc = secondary_label(description, size=Font.SMALL)
            desc.setFrame_(NSMakeRect(_CARD_PAD, row_y + 4, 300, 14))
            content.addSubview_(desc)

            switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(self.card_width - _CARD_PAD - 46, row_y + 12, 46, 22))
            val = features.get_facet(_FEATURE_KEY, facet_name)
            switch.setState_(NSControlStateValueOn if val else NSControlStateValueOff)
            switch.setIdentifier_(f"{_FEATURE_KEY}|{facet_name}")
            switch.setTarget_(self.delegate)
            switch.setAction_(objc.selector(self.delegate.facetBoolChanged_, signature=b"v@:@"))
            content.addSubview_(switch)

        for facet_name, facet_label, options in dropdowns:
            row_y -= _dropdown_row_h
            text = label(facet_label, size=Font.SECONDARY)
            text.setFrame_(NSMakeRect(_CARD_PAD, row_y + 8, 150, 16))
            content.addSubview_(text)

            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(self.card_width - _CARD_PAD - 130, row_y + 4, 130, 24), False
            )
            popup.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
            popup.addItemsWithTitles_(list(options))
            current = features.get_facet(_FEATURE_KEY, facet_name)
            if current:
                popup.selectItemWithTitle_(str(current))
            popup.cell().setRepresentedObject_(f"{_FEATURE_KEY}|{facet_name}")
            popup.setTarget_(self.delegate)
            popup.setAction_(objc.selector(self.delegate.facetChanged_, signature=b"v@:@"))
            content.addSubview_(popup)

        return toggle_card

    def _build_plugins_card(self, plugins_data: dict[str, object]) -> NSView:
        card_h = _CARD_PAD + len(plugins_data) * _ROW_H + _CARD_PAD
        plugins_card = card(self.card_width, card_h)
        content = plugins_card.contentView()
        row_y = card_h - _CARD_PAD

        for name, entries in plugins_data.items():
            row_y -= _ROW_H
            short_name = name.split("@")[0] if "@" in name else name
            name_label = label(short_name, size=Font.SECONDARY)
            name_label.setFrame_(NSMakeRect(_CARD_PAD, row_y, 120, 16))
            content.addSubview_(name_label)

            meta = self._format_plugin_meta(entries)
            if meta:
                meta_label = secondary_label(meta, size=Font.SMALL)
                meta_label.setFrame_(NSMakeRect(130, row_y, self.card_width - 200, 16))
                content.addSubview_(meta_label)

            uninstall_btn = NSButton.alloc().initWithFrame_(NSMakeRect(self.card_width - _CARD_PAD - 16, row_y, 16, 16))
            uninstall_btn.setTitle_("✕")
            uninstall_btn.setBezelStyle_(0)
            uninstall_btn.setBordered_(False)
            uninstall_btn.setFont_(NSFont.systemFontOfSize_(9.0))
            uninstall_btn.setTarget_(self.delegate)
            uninstall_btn.setAction_(objc.selector(self.delegate.uninstallPlugin_, signature=b"v@:@"))
            uninstall_btn.cell().setRepresentedObject_(name)
            content.addSubview_(uninstall_btn)

        return plugins_card

    def _build_policies_card(  # noqa: PLR0913
        self,
        svc: object,
        snapshot: object,
        policies: list[tuple[str, str, str]],
    ) -> NSView:
        card_h = _CARD_PAD + len(policies) * _TALL_ROW_H + _CARD_PAD
        policy_card = card(self.card_width, card_h)
        content = policy_card.contentView()
        row_y = card_h - _CARD_PAD

        status_w = 70
        desc_w = self.card_width - _CARD_PAD * 2 - status_w

        for key, display_name, description in policies:
            row_y -= _TALL_ROW_H
            val = svc.get_policy_value(snapshot, key)
            status = "Enabled" if val else "Disabled"
            color = theme.danger if val else theme.secondary

            key_label = label(display_name, size=Font.SECONDARY, bold=True)
            key_label.setFrame_(NSMakeRect(_CARD_PAD, row_y + 16, desc_w, 16))
            content.addSubview_(key_label)

            desc_label = secondary_label(description, size=Font.SMALL)
            desc_label.setFrame_(NSMakeRect(_CARD_PAD, row_y, desc_w, 14))
            content.addSubview_(desc_label)

            val_label = label(status, size=Font.SECONDARY, bold=True, color=color)
            val_label.setFrame_(NSMakeRect(self.card_width - _CARD_PAD - status_w, row_y + 10, status_w, 16))
            content.addSubview_(val_label)

        return policy_card

    def _build_blocklist_source(self, fetched_date: str) -> NSView:
        link_btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, self.card_width, 14))
        link_btn.setTitle_(f"Synced from Anthropic on {fetched_date} ↗")
        link_btn.setBezelStyle_(0)
        link_btn.setBordered_(False)
        link_btn.setAlignment_(0)  # NSTextAlignmentLeft
        link_btn.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
        link_btn.setTarget_(self.delegate)
        link_btn.setAction_(objc.selector(self.delegate.openBlocklistSource_, signature=b"v@:@"))
        return link_btn

    def _build_blocklist_card(self, svc: object, snapshot: object, entries: list[dict[str, str]]) -> NSView:
        card_h = _CARD_PAD + len(entries) * _TALL_ROW_H + _CARD_PAD
        blocked_card = card(self.card_width, card_h)
        content = blocked_card.contentView()
        row_y = card_h - _CARD_PAD
        installed_plugins = svc.get_plugin_keys(snapshot)

        for entry in entries:
            row_y -= _TALL_ROW_H
            plugin_name = entry.get("plugin", "unknown")
            short = plugin_name.split("@")[0] if "@" in plugin_name else plugin_name
            reason = entry.get("reason", "")
            explanation = entry.get("text", "")

            is_conflict = plugin_name in installed_plugins
            if is_conflict:
                name_color = theme.danger
                name_display = f"⚠ {short}  (installed)"
            else:
                name_color = theme.secondary
                name_display = short

            name_label = label(name_display, size=Font.SECONDARY, bold=True, color=name_color)
            name_label.setFrame_(NSMakeRect(_CARD_PAD, row_y + 16, self.card_width - _CARD_PAD * 2 - 80, 16))
            content.addSubview_(name_label)

            reason_display = explanation or reason or "No reason given"
            if len(reason_display) > _MAX_RULE_LEN:
                reason_display = reason_display[: _MAX_RULE_LEN - 1] + "…"
            reason_label = secondary_label(reason_display, size=Font.SMALL)
            reason_label.setFrame_(NSMakeRect(_CARD_PAD, row_y, self.card_width - _CARD_PAD * 2, 14))
            content.addSubview_(reason_label)

            if reason:
                badge_label = label(reason, size=Font.SMALL, color=theme.tertiary)
                badge_label.setFrame_(NSMakeRect(self.card_width - _CARD_PAD - 80, row_y + 16, 80, 16))
                content.addSubview_(badge_label)

        return blocked_card

    def _build_permissions_card(
        self,
        global_path: str,
        global_rules: set[str],
        project_perms: list[tuple[str, str, list[str]]],
    ) -> NSView:
        _scope_gap = Spacing.SM  # breathing room between scope groups
        scope_count = (1 if global_rules else 0) + len(project_perms)
        total_rows = 0
        if global_rules:
            total_rows += 1 + len(global_rules)
        for _name, _path, rules in project_perms:
            total_rows += 1 + len(rules)

        card_h = _CARD_PAD + total_rows * _ROW_H + max(scope_count - 1, 0) * _scope_gap + _CARD_PAD
        perm_card = card(self.card_width, card_h)
        content = perm_card.contentView()
        row_y = card_h - _CARD_PAD
        is_first_scope = True

        if global_rules:
            row_y -= _ROW_H
            self._add_scope_header(content, "Global (all projects)", global_path, list(global_rules), row_y, _CARD_PAD)
            for rule in sorted(global_rules, key=lambda r: (":*" not in r, r)):
                row_y -= _ROW_H
                self._add_permission_row(content, rule, global_path, row_y, _CARD_PAD)
            is_first_scope = False

        for proj_name, settings_path, rules in project_perms:
            if not is_first_scope:
                row_y -= _scope_gap
            row_y -= _ROW_H
            self._add_scope_header(content, proj_name, settings_path, rules, row_y, _CARD_PAD)
            for rule in sorted(rules, key=lambda r: (":*" not in r, r)):
                row_y -= _ROW_H
                self._add_permission_row(content, rule, settings_path, row_y, _CARD_PAD)
            is_first_scope = False

        return perm_card

    def _build_marketplaces_card(self, marketplaces_data: dict[str, object]) -> NSView:
        card_h = _CARD_PAD + len(marketplaces_data) * _TALL_ROW_H + _CARD_PAD
        mkt_card = card(self.card_width, card_h)
        content = mkt_card.contentView()
        row_y = card_h - _CARD_PAD

        for name, data in marketplaces_data.items():
            row_y -= _TALL_ROW_H
            mkt_label = label(name, size=Font.SECONDARY, bold=True)
            mkt_label.setFrame_(NSMakeRect(_CARD_PAD, row_y + 16, self.card_width - _CARD_PAD * 2, 16))
            content.addSubview_(mkt_label)

            source_repo = ""
            if isinstance(data, dict):
                source = data.get("source", {})
                if isinstance(source, dict):
                    source_repo = source.get("repo", "")
            source_display = source_repo or "Unknown source"
            source_label = secondary_label(source_display, size=Font.SMALL)
            source_label.setFrame_(NSMakeRect(_CARD_PAD, row_y, self.card_width - _CARD_PAD * 2, 14))
            content.addSubview_(source_label)

        return mkt_card

    # -- Card-internal helpers (manual coordinates inside card contentView) --

    def _add_scope_header(  # noqa: PLR0913
        self, content: NSView, scope_name: str, settings_path: str, rules: list[str], row_y: float, pad: float
    ) -> None:
        scope_label = label(scope_name, size=Font.SMALL, bold=True, color=theme.tertiary)
        scope_label.setFrame_(NSMakeRect(pad, row_y, 200, 16))
        content.addSubview_(scope_label)

        btn_x = self.card_width - pad

        btn_x -= 60
        clear_btn = NSButton.alloc().initWithFrame_(NSMakeRect(btn_x, row_y, 55, 16))
        clear_btn.setTitle_("Clear All")
        clear_btn.setBezelStyle_(0)
        clear_btn.setBordered_(False)
        clear_btn.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
        clear_btn.setTarget_(self.delegate)
        clear_btn.setAction_(objc.selector(self.delegate.clearPermissions_, signature=b"v@:@"))
        clear_btn.cell().setRepresentedObject_(settings_path)
        content.addSubview_(clear_btn)

        has_dangerous = any(is_dangerous_permission(r) for r in rules)
        if has_dangerous:
            btn_x -= 110
            danger_btn = NSButton.alloc().initWithFrame_(NSMakeRect(btn_x, row_y, 105, 16))
            danger_btn.setTitle_("Remove Dangerous")
            danger_btn.setBezelStyle_(0)
            danger_btn.setBordered_(False)
            danger_btn.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
            danger_btn.setTarget_(self.delegate)
            danger_btn.setAction_(objc.selector(self.delegate.removeDangerousPermissions_, signature=b"v@:@"))
            danger_btn.cell().setRepresentedObject_(settings_path)
            content.addSubview_(danger_btn)

    def _add_permission_row(self, content: NSView, rule: str, settings_path: str, row_y: float, pad: float) -> None:
        dangerous = is_dangerous_permission(rule)
        is_broad = ":*" in rule
        display_rule = self.format_permission_display(rule)
        if dangerous:
            display_rule = f"{display_rule}  — {dangerous.description}"
        if len(display_rule) > _MAX_RULE_LEN:
            display_rule = display_rule[: _MAX_RULE_LEN - 1] + "…"

        if dangerous:
            color = theme.danger
            prefix = "🚫 "
        elif is_broad:
            color = theme.warning
            prefix = "⚠ "
        else:
            color = theme.secondary
            prefix = "  "
        rule_label = label(prefix + display_rule, size=Font.SMALL, color=color)
        rule_label.setFrame_(NSMakeRect(pad + 8, row_y, self.card_width - pad * 2 - 30, 16))
        content.addSubview_(rule_label)

        remove_btn = NSButton.alloc().initWithFrame_(NSMakeRect(self.card_width - pad - 20, row_y, 16, 16))
        remove_btn.setTitle_("✕")
        remove_btn.setBezelStyle_(0)
        remove_btn.setBordered_(False)
        remove_btn.setFont_(NSFont.systemFontOfSize_(9.0))
        remove_btn.setTarget_(self.delegate)
        remove_btn.setAction_(objc.selector(self.delegate.removePermission_, signature=b"v@:@"))
        remove_btn.cell().setRepresentedObject_(f"{settings_path}|{rule}")
        content.addSubview_(remove_btn)

    # -- Static helpers --

    @staticmethod
    def _format_plugin_meta(entries: object) -> str:
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
    def format_permission_display(rule: str) -> str:
        """Format a permission rule for display — raw command + whatis description for wildcards."""
        if rule.startswith("Bash(") and rule.endswith(")"):
            inner = rule[5:-1]
            if ":*" in inner:
                cmd = inner.replace(":*", " *")
                # Strip env var prefixes (e.g., GH_PAGER=cat gh pr diff)
                clean_cmd = inner.split(":*")[0]
                words = clean_cmd.split()
                words = [w for w in words if "=" not in w]  # drop VAR=val prefixes
                desc = get_security_service().repository.get_command_description(" ".join(words))
                display = f"{cmd}  —  {desc}" if desc else cmd
                if len(display) > _MAX_RULE_LEN:
                    return display[: _MAX_RULE_LEN - 1] + "…"
                return display
            if len(inner) > _MAX_RULE_LEN:
                return inner[: _MAX_RULE_LEN - 1] + "…"
            return inner
        # Non-Bash: show as-is
        if len(rule) > _MAX_RULE_LEN:
            return rule[: _MAX_RULE_LEN - 1] + "…"
        return rule

    @staticmethod
    def format_permission_tooltip(rule: str) -> str:  # noqa: PLR0911
        """Generate a tooltip explaining what the permission allows. Uses man whatis for descriptions."""
        if rule == "WebSearch":
            return "Allows Claude to search the web"
        if rule.startswith("WebFetch("):
            domain = rule[9:-1] if rule.endswith(")") else rule[9:]
            return f"Allows Claude to fetch content from {domain.replace('domain:', '')}"
        if rule.startswith("Read("):
            return "Allows reading files matching this pattern"
        if not (rule.startswith("Bash(") and rule.endswith(")")):
            return rule

        inner = rule[5:-1]
        base_cmd = inner.split(":*")[0] if ":*" in inner else inner.split()[0] if inner.split() else inner

        # Look up man page description
        desc = get_security_service().repository.get_command_description(base_cmd)

        if ":*" in inner:
            tool = inner.split(":*")[0]
            if desc:
                return f"{tool} — {desc}\nAlways allowed without asking"
            return f"Can run '{tool}' with any arguments — always allowed without asking"

        if desc:
            return f"{base_cmd} — {desc}"
        return f"Always allowed: {inner}"

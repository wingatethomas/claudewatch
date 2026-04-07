"""Security pane — visibility into Claude Code's trust surface."""

from __future__ import annotations

import os

import objc
from AppKit import (
    NSButton,
    NSControlStateValueOff,
    NSControlStateValueOn,
    NSFont,
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

        # Estimate content height
        content_h = 0
        content_h += 80  # toggles section
        content_h += _card_pad + max(plugin_count, 1) * _row_h + _card_pad + 30
        content_h += _card_pad + 2 * 36 + _card_pad + 30  # policies (taller rows)
        if blocklist_entries:
            content_h += _card_pad + len(blocklist_entries) * 36 + _card_pad + 30
        project_perms_for_height = repo.get_all_project_permissions()
        project_perms_count = sum(1 + min(len(r), 5) for _, _, r in project_perms_for_height)
        perm_total = (1 + len(perm_rules) if perm_rules else 0) + project_perms_count
        if perm_total:
            content_h += _card_pad + perm_total * _row_h + _card_pad + 30
        marketplaces_data = snapshot.known_marketplaces
        if isinstance(marketplaces_data, dict) and marketplaces_data:
            content_h += _card_pad + len(marketplaces_data) * 36 + _card_pad + 30
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
                name_label.setFrame_(NSMakeRect(_card_pad, row_y, 120, 16))
                plugins_content.addSubview_(name_label)

                meta = self._format_plugin_meta(entries)
                if meta:
                    meta_label = secondary_label(meta, size=Font.SMALL)
                    meta_label.setFrame_(NSMakeRect(130, row_y, self.card_width - 200, 16))
                    plugins_content.addSubview_(meta_label)

                # Uninstall button
                uninstall_btn = NSButton.alloc().initWithFrame_(
                    NSMakeRect(self.card_width - _card_pad - 16, row_y, 16, 16)
                )
                uninstall_btn.setTitle_("✕")
                uninstall_btn.setBezelStyle_(0)
                uninstall_btn.setBordered_(False)
                uninstall_btn.setFont_(NSFont.systemFontOfSize_(9.0))
                uninstall_btn.setTarget_(self.delegate)
                uninstall_btn.setAction_(objc.selector(self.delegate.uninstallPlugin_, signature=b"v@:@"))
                uninstall_btn.cell().setRepresentedObject_(name)
                plugins_content.addSubview_(uninstall_btn)

            y -= card_h + Spacing.MD
        else:
            empty = secondary_label("No plugins installed", size=Font.SECONDARY)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, y - 20, self.card_width, 16))
            inner.addSubview_(empty)
            y -= 20 + Spacing.MD

        # Policies — with descriptions explaining what each one controls
        _policy_row_h = 36  # taller rows for name + description
        _policies = [
            ("allow_remote_control", "Remote Control", "Allow external tools to send commands to Claude Code"),
            ("allow_quick_web_setup", "Quick Web Setup", "Allow browser-based configuration of Claude Code"),
        ]
        y = self._add_section_header(inner, "POLICIES", y)
        policy_h = _card_pad + len(_policies) * _policy_row_h + _card_pad
        policy_card = card(self.card_width, policy_h)
        policy_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - policy_h, self.card_width, policy_h))
        inner.addSubview_(policy_card)
        policy_content = policy_card.contentView()
        policy_y = policy_h - _card_pad

        for key, display_name, description in _policies:
            policy_y -= _policy_row_h
            val = repo._get_policy_value(snapshot.policy_limits, key)
            status = "Enabled" if val else "Disabled"
            color = theme.danger if val else theme.secondary

            key_label = label(display_name, size=Font.SECONDARY, bold=True)
            key_label.setFrame_(NSMakeRect(_card_pad, policy_y + 16, 260, 16))
            policy_content.addSubview_(key_label)

            desc_label = secondary_label(description, size=Font.SMALL)
            desc_label.setFrame_(NSMakeRect(_card_pad, policy_y, 260, 14))
            policy_content.addSubview_(desc_label)

            val_label = label(status, size=Font.SECONDARY, bold=True, color=color)
            val_label.setFrame_(NSMakeRect(self.card_width - _card_pad - 80, policy_y + 10, 80, 16))
            policy_content.addSubview_(val_label)

        y -= policy_h + Spacing.MD

        # Blocklisted plugins — managed by Anthropic, fetched centrally
        if blocklist_entries:
            _blocked_row_h = 36
            fetched_at = snapshot.plugins_blocklist.get("fetchedAt", "")
            fetched_date = str(fetched_at)[:10] if fetched_at else "unknown"
            y = self._add_section_header(inner, "BLOCKLISTED PLUGINS", y)

            # Source attribution
            source_text = f"Synced from Anthropic on {fetched_date}"
            source_label = secondary_label(source_text, size=Font.SMALL)
            source_label.setFrame_(NSMakeRect(CONTENT_PADDING, y - 14, self.card_width - 40, 14))
            inner.addSubview_(source_label)

            # Link button to view the source repo
            link_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(CONTENT_PADDING + self.card_width - 40, y - 14, 30, 14)
            )
            link_btn.setTitle_("View")
            link_btn.setBezelStyle_(0)
            link_btn.setBordered_(False)
            link_btn.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
            link_btn.setTarget_(self.delegate)
            link_btn.setAction_(objc.selector(self.delegate.openBlocklistSource_, signature=b"v@:@"))
            inner.addSubview_(link_btn)

            y -= 14 + Spacing.XS

            blocked_h = _card_pad + len(blocklist_entries) * _blocked_row_h + _card_pad
            blocked_card = card(self.card_width, blocked_h)
            blocked_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - blocked_h, self.card_width, blocked_h))
            inner.addSubview_(blocked_card)
            blocked_content = blocked_card.contentView()
            blocked_y = blocked_h - _card_pad

            installed_plugins = repo._plugin_keys(snapshot.plugins_installed)

            for entry in blocklist_entries:
                blocked_y -= _blocked_row_h
                plugin_name = entry.get("plugin", "unknown")
                short = plugin_name.split("@")[0] if "@" in plugin_name else plugin_name
                reason = entry.get("reason", "")
                explanation = entry.get("text", "")

                # Flag if this blocked plugin is also installed
                is_conflict = plugin_name in installed_plugins
                name_display = f"⚠ {short}" if is_conflict else short

                name_label = label(name_display, size=Font.SECONDARY, bold=True, color=theme.danger)
                name_label.setFrame_(NSMakeRect(_card_pad, blocked_y + 16, 200, 16))
                blocked_content.addSubview_(name_label)

                reason_display = explanation or reason or "No reason given"
                if len(reason_display) > _MAX_RULE_LEN:
                    reason_display = reason_display[: _MAX_RULE_LEN - 1] + "…"
                reason_label = secondary_label(reason_display, size=Font.SMALL)
                reason_label.setFrame_(NSMakeRect(_card_pad, blocked_y, self.card_width - _card_pad * 2, 14))
                blocked_content.addSubview_(reason_label)

                if reason:
                    badge_label = label(reason, size=Font.SMALL, color=theme.danger)
                    badge_label.setFrame_(NSMakeRect(self.card_width - _card_pad - 80, blocked_y + 16, 80, 16))
                    blocked_content.addSubview_(badge_label)

            y -= blocked_h + Spacing.MD

        # Permission rules — global + per-project
        y = self._add_section_header(inner, "PERMISSIONS", y)

        # Global permissions (from ~/.claude/settings.local.json)
        global_path, global_rules_list = repo.get_global_permissions()
        global_rules = set(global_rules_list)
        # Per-project permissions (crawl all known Claude projects)
        project_perms = repo.get_all_project_permissions()

        total_rows = 0
        if global_rules:
            total_rows += 1 + len(global_rules)  # header + rules
        for _proj_name, _path, rules in project_perms:
            total_rows += 1 + len(rules)  # header + rules

        if total_rows == 0:
            empty = secondary_label("No permission rules configured", size=Font.SECONDARY)
            empty.setFrame_(NSMakeRect(CONTENT_PADDING, y - 20, self.card_width, 16))
            inner.addSubview_(empty)
            y -= 20 + Spacing.MD
        else:
            rules_h = _card_pad + total_rows * _row_h + _card_pad
            rules_card = card(self.card_width, rules_h)
            rules_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - rules_h, self.card_width, rules_h))
            inner.addSubview_(rules_card)
            rules_content = rules_card.contentView()
            rules_y = rules_h - _card_pad

            if global_rules:
                rules_y -= _row_h
                scope_label = label("Global (all projects)", size=Font.SMALL, bold=True, color=theme.tertiary)
                scope_label.setFrame_(NSMakeRect(_card_pad, rules_y, 200, 16))
                rules_content.addSubview_(scope_label)

                clear_btn = NSButton.alloc().initWithFrame_(
                    NSMakeRect(self.card_width - _card_pad - 60, rules_y, 55, 16)
                )
                clear_btn.setTitle_("Clear All")
                clear_btn.setBezelStyle_(0)
                clear_btn.setBordered_(False)
                clear_btn.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
                clear_btn.setTarget_(self.delegate)
                clear_btn.setAction_(objc.selector(self.delegate.clearPermissions_, signature=b"v@:@"))
                clear_btn.cell().setRepresentedObject_(global_path)
                rules_content.addSubview_(clear_btn)

                for rule in sorted(global_rules, key=lambda r: (":*" not in r, r)):
                    rules_y -= _row_h
                    rules_y = self._add_permission_row(rules_content, rule, global_path, rules_y, _card_pad)

            for proj_name, settings_path, rules in project_perms:
                rules_y -= _row_h
                scope_label = label(proj_name, size=Font.SMALL, bold=True, color=theme.tertiary)
                scope_label.setFrame_(NSMakeRect(_card_pad, rules_y, 200, 16))
                rules_content.addSubview_(scope_label)

                clear_btn = NSButton.alloc().initWithFrame_(
                    NSMakeRect(self.card_width - _card_pad - 60, rules_y, 55, 16)
                )
                clear_btn.setTitle_("Clear All")
                clear_btn.setBezelStyle_(0)
                clear_btn.setBordered_(False)
                clear_btn.setFont_(NSFont.systemFontOfSize_(Font.SMALL))
                clear_btn.setTarget_(self.delegate)
                clear_btn.setAction_(objc.selector(self.delegate.clearPermissions_, signature=b"v@:@"))
                clear_btn.cell().setRepresentedObject_(settings_path)
                rules_content.addSubview_(clear_btn)

                display_rules = sorted(rules, key=lambda r: (":*" not in r, r))
                for rule in display_rules:
                    rules_y -= _row_h
                    rules_y = self._add_permission_row(rules_content, rule, settings_path, rules_y, _card_pad)

            y -= rules_h + Spacing.MD

        # Marketplaces — show name + GitHub source
        marketplaces_data = snapshot.known_marketplaces
        if isinstance(marketplaces_data, dict) and marketplaces_data:
            y = self._add_section_header(inner, "PLUGIN MARKETPLACES", y)
            _mkt_row_h = 36
            mkt_h = _card_pad + len(marketplaces_data) * _mkt_row_h + _card_pad
            mkt_card = card(self.card_width, mkt_h)
            mkt_card.setFrame_(NSMakeRect(CONTENT_PADDING, y - mkt_h, self.card_width, mkt_h))
            inner.addSubview_(mkt_card)
            mkt_content = mkt_card.contentView()
            mkt_y = mkt_h - _card_pad

            for name, data in marketplaces_data.items():
                mkt_y -= _mkt_row_h
                mkt_label = label(name, size=Font.SECONDARY, bold=True)
                mkt_label.setFrame_(NSMakeRect(_card_pad, mkt_y + 16, self.card_width - _card_pad * 2, 16))
                mkt_content.addSubview_(mkt_label)

                source_repo = ""
                if isinstance(data, dict):
                    source = data.get("source", {})
                    if isinstance(source, dict):
                        source_repo = source.get("repo", "")
                source_display = source_repo or "Unknown source"
                source_label = secondary_label(source_display, size=Font.SMALL)
                source_label.setFrame_(NSMakeRect(_card_pad, mkt_y, self.card_width - _card_pad * 2, 14))
                mkt_content.addSubview_(source_label)

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

    def _add_permission_row(self, content: NSView, rule: str, settings_path: str, row_y: float, pad: float) -> float:
        """Add a single permission rule row with delete button."""
        is_broad = ":*" in rule
        display_rule = self._format_permission_rule(rule)
        if len(display_rule) > _MAX_RULE_LEN:
            display_rule = display_rule[: _MAX_RULE_LEN - 1] + "…"

        color = theme.danger if is_broad else theme.secondary
        prefix = "⚠ " if is_broad else "  "
        rule_label = label(prefix + display_rule, size=Font.SMALL, color=color)
        rule_label.setFrame_(NSMakeRect(pad + 8, row_y, self.card_width - pad * 2 - 30, 16))
        content.addSubview_(rule_label)

        # X button to remove this rule
        remove_btn = NSButton.alloc().initWithFrame_(NSMakeRect(self.card_width - pad - 20, row_y, 16, 16))
        remove_btn.setTitle_("✕")
        remove_btn.setBezelStyle_(0)
        remove_btn.setBordered_(False)
        remove_btn.setFont_(NSFont.systemFontOfSize_(9.0))
        remove_btn.setTarget_(self.delegate)
        remove_btn.setAction_(objc.selector(self.delegate.removePermission_, signature=b"v@:@"))
        remove_btn.cell().setRepresentedObject_(f"{settings_path}|{rule}")
        content.addSubview_(remove_btn)

        return row_y

    @staticmethod
    def _format_permission_rule(rule: str) -> str:  # noqa: PLR0911
        """Make a permission rule human-readable plain English.

        'Bash(python3:*)' → 'Can run any Python script'
        'Bash(wc -l /Users/.../projects/-Users-dev-myapp/*.jsonl)' → 'Can count lines in backend-api logs'
        """
        if not (rule.startswith("Bash(") and rule.endswith(")")):
            return rule

        inner = rule[5:-1]

        # Wildcard permissions
        if ":*" in inner:
            tool = inner.split(":*")[0]
            known = {
                "python3": "Can run any Python script",
                "node": "Can run any Node.js script",
                "npm": "Can run any npm command",
                "git": "Can run any git command",
                "docker": "Can run any Docker command",
            }
            return known.get(tool, f"Can run {tool} with any arguments")

        # Claude session log access
        if "/.claude/projects/" in inner:
            parts = inner.split("/.claude/projects/")
            proj_path = parts[1] if len(parts) > 1 else ""
            proj_segments = proj_path.split("/")[0].split("-")
            project_name = proj_segments[-1] if proj_segments else "unknown"
            return f"Can read {project_name} session logs"

        # Generic bash command — show a simplified version
        if inner.startswith("wc "):
            return "Can count lines in files"
        if inner.startswith("cat "):
            return "Can read file contents"
        if inner.startswith("ls "):
            return "Can list directory contents"
        if inner.startswith("grep "):
            return "Can search file contents"

        # Fallback: truncate the raw command
        if len(inner) > 40:
            return inner[:39] + "…"
        return inner

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

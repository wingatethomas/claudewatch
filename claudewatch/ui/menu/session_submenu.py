"""Session submenu builder — single source for Summary + Usage + Actions.

Replaces the 3x duplicated pattern in menu_builder.py.
Used for active sessions, bookmarks, and recent sessions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claudewatch.backend.analytics.models import AgentInfo

from AppKit import NSMenu, NSMenuItem

from claudewatch.ui.icons import sf_icon
from claudewatch.ui.menu.core import add_summary_lines, make_menu_item

MenuCallback = Callable[[NSMenuItem], None]


@dataclass
class SessionActions:
    """Optional action callbacks for a session submenu."""

    activity: MenuCallback | None = None
    resume: MenuCallback | None = None
    bookmark: MenuCallback | None = None
    unbookmark: MenuCallback | None = None
    quit: MenuCallback | None = None
    remove: MenuCallback | None = None
    track_summary: Callable[[], None] | None = None
    usage_lines: list[str] = field(default_factory=list)


def build_session_submenu(
    *,
    delegate: object,
    summary: str | None,
    generating: bool = False,
    actions: SessionActions | None = None,
    agents: list[AgentInfo] | None = None,
) -> NSMenu:
    """Build a session submenu with Summary, Usage, and contextual actions."""
    sub = NSMenu.alloc().init()
    d = delegate
    act = actions or SessionActions()

    # Summary submenu
    summary_item = make_menu_item("Summary", None, d)
    summary_sub = NSMenu.alloc().init()
    if summary:
        add_summary_lines(summary_sub, summary, d)
    elif generating:
        summary_sub.addItem_(make_menu_item("Generating…", None, d))
    else:
        summary_sub.addItem_(make_menu_item("Generating…", None, d))
        if act.track_summary:
            act.track_summary()
    summary_item.setSubmenu_(summary_sub)
    sub.addItem_(summary_item)

    # Usage submenu
    usage_item = make_menu_item("Usage", None, d)
    usage_sub = NSMenu.alloc().init()
    if act.usage_lines:
        for line in act.usage_lines:
            usage_sub.addItem_(make_menu_item(f"  {line}", None, d))
        usage_sub.addItem_(NSMenuItem.separatorItem())
    if act.activity:
        usage_sub.addItem_(make_menu_item("View session activity log", act.activity, d))
    usage_item.setSubmenu_(usage_sub)
    sub.addItem_(usage_item)

    # Agents submenu
    if agents:
        agents_item = build_agents_submenu(agents, d)
        sub.addItem_(agents_item)

    sub.addItem_(NSMenuItem.separatorItem())

    # Contextual actions
    action_items = [
        ("resume", "Resume", "play.circle"),
        ("bookmark", "Bookmark...", "bookmark"),
        ("unbookmark", "Unbookmark", "bookmark.slash"),
        ("quit", "Quit session", "xmark.circle"),
        ("remove", "Remove", "trash"),
    ]
    for attr, title, icon_name in action_items:
        cb = getattr(act, attr, None)
        if cb:
            item = make_menu_item(title, cb, d)
            item.setImage_(sf_icon(icon_name))
            sub.addItem_(item)

    return sub


def build_agents_submenu(agents: list[AgentInfo], delegate: object) -> NSMenuItem:
    """Build an Agents (N) submenu showing type and status for each agent."""
    d = delegate
    agents_item = make_menu_item(f"Agents ({len(agents)})", None, d)
    agents_sub = NSMenu.alloc().init()
    for agent in agents:
        agent_type = getattr(agent, "agent_type", "agent")
        status = getattr(agent, "status", "")
        label = f"{agent_type} · {status}" if status else agent_type
        agents_sub.addItem_(make_menu_item(f"  {label}", None, d))
    agents_item.setSubmenu_(agents_sub)
    return agents_item

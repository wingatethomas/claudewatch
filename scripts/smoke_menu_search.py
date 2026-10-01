"""Manual smoke test for the session search field inside a status-item menu.

Run: uv run python scripts/smoke_menu_search.py

Checklist (interact with the ✦ status item that appears):
  1. Click the field, type "parser" — only the alpha row stays visible.
  2. Type gibberish — "No matching sessions" appears.
  3. Clear via the x button — all rows return.
  4. Keep the menu open >3s while typing — watch stdout: rebuilds must be
     SKIPPED while the field is focused or has text, and focus must survive.
  5. Close + reopen the menu — field is cleared, all rows visible.

Ctrl+C in the terminal to quit.
"""

from __future__ import annotations

import signal

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSTimer,
)
from PyObjCTools import AppHelper

from claudewatch.ui.menu.core import AppDelegate, disabled_item
from claudewatch.ui.menu.filtering import FilterRow, FilterSection, apply_filter, build_haystack
from claudewatch.ui.menu.search_item import build_search_item

FAKE_SESSIONS = [
    ("alpha", "fix the parser", "rewrote tokenizer error recovery"),
    ("beta", "write docs", "drafted the install guide"),
    ("gamma", "refactor ui", None),
]


class FakeApp:
    def __init__(self) -> None:
        self.menu = NSMenu.alloc().init()
        self.menu.setAutoenablesItems_(False)
        self.menu_open = False
        self.query = ""
        self.rebuilds = 0
        self.delegate = AppDelegate.alloc().init()
        self.delegate._app = self
        self.search_item, self.search_field = build_search_item(self.delegate)
        self.sections: list[FilterSection] = []
        self.no_match_item: NSMenuItem | None = None
        self.menu.setDelegate_(self.delegate)
        self.build()

    def build(self) -> None:
        self.rebuilds += 1
        self.menu.removeAllItems()
        self.menu.addItem_(self.search_item)
        header = disabled_item("✦ Working")
        self.menu.addItem_(header)
        rows: list[FilterRow] = []
        for project, title, summary in FAKE_SESSIONS:
            item = disabled_item(f"✦ {project} — {title}")
            self.menu.addItem_(item)
            detail_item = disabled_item(f"      {summary}") if summary else None
            if detail_item:
                self.menu.addItem_(detail_item)
            rows.append(FilterRow(item=item, detail_item=detail_item, haystack=build_haystack(project, title, summary)))
        self.sections = [FilterSection(header=header, rows=rows)]
        self.no_match_item = disabled_item("No matching sessions")
        self.no_match_item.setHidden_(True)
        self.menu.addItem_(self.no_match_item)
        apply_filter(self.sections, self.no_match_item, self.query)
        print(f"rebuild #{self.rebuilds}")

    def filter_active(self) -> bool:
        return bool(self.query.strip()) or self.search_field.currentEditor() is not None

    def on_session_search(self, sender: object) -> None:
        self.query = str(sender.stringValue())  # type: ignore[attr-defined]
        apply_filter(self.sections, self.no_match_item, self.query)
        print(f"query={self.query!r} editor={self.search_field.currentEditor() is not None}")

    def on_menu_open(self) -> None:
        self.menu_open = True
        print("menu opened")

    def on_menu_close(self) -> None:
        self.menu_open = False
        self.query = ""
        self.search_field.setStringValue_("")
        print("menu closed — filter cleared")

    def poll(self) -> None:
        if self.menu_open and self.filter_active():
            print("tick: rebuild SKIPPED (menu open + filter active)")
            return
        had_editor = self.search_field.currentEditor() is not None
        self.build()
        print(
            f"tick: rebuilt while menu_open={self.menu_open}; editor before={had_editor}, after={self.search_field.currentEditor() is not None}"
        )


def main() -> None:
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    fake = FakeApp()
    status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1)
    status_item.setTitle_("✦?")
    status_item.setMenu_(fake.menu)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        3.0, fake.delegate, "pollTick:", None, True
    )
    signal.signal(signal.SIGINT, lambda *_: AppHelper.stopEventLoop())
    print(__doc__)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()

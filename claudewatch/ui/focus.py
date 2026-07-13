import logging
import time

from AppKit import NSRunningApplication
from Quartz import (
    CGEventCreateMouseEvent,
    CGEventPost,
    CGPointMake,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    kCGHIDEventTap,
    kCGMouseButtonLeft,
)

from claudewatch.backend.core.helpers import escape_applescript, is_accessibility_trusted, run_applescript
from claudewatch.backend.core.models import ClaudeSession, HostApp

log = logging.getLogger("claudewatch")


def _click_at(x: float, y: float) -> None:
    """Click at screen coordinates using CGEvent (works for PyCharm tabs)."""
    point = CGPointMake(x, y)
    evt = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, point, kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, evt)
    evt = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, point, kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, evt)


def _focus_ide_tab(process_name: str, project: str, tab_index: int | None) -> None:
    """Focus an IDE window and switch to the right terminal tab."""
    if not is_accessibility_trusted():
        log.warning("focus: skipping System Events — Accessibility permission not granted")
        return
    # Step 1: Activate the app first, on its own. Window raising is
    # best-effort — IDE window titles (diff viewers, detached editors)
    # often contain no project name, and a failed whose-clause must not
    # abort activation with it.
    run_applescript(f'''
        tell application "System Events"
            set frontmost of process "{escape_applescript(process_name)}" to true
        end tell
    ''')
    run_applescript(f'''
        tell application "System Events"
            tell process "{escape_applescript(process_name)}"
                try
                    set targetWindow to first window whose name contains "{escape_applescript(project)}"
                    perform action "AXRaise" of targetWindow
                end try
            end tell
        end tell
    ''')
    # Step 2: If we know the tab index, click the terminal tab via AX position
    if tab_index is not None:
        time.sleep(0.3)
        # Ensure terminal panel is open (Option+F12 for JetBrains, Ctrl+` for VS Code)
        if "pycharm" in process_name.lower() or "idea" in process_name.lower():
            # Check if terminal panel is already visible before toggling
            check = run_applescript(f'''
                tell application "System Events"
                    tell process "{escape_applescript(process_name)}"
                        set w to first window whose name contains "{escape_applescript(project)}"
                        set rootPane to first UI element of w whose role is "AXGroup"
                        set panels to every UI element of rootPane whose role is "AXGroup"
                        repeat with p in panels
                            try
                                set d to description of p
                                if d ends with "Tool Window" and d is not "Project Tool Window" then
                                    return "visible"
                                end if
                            end try
                        end repeat
                        return "hidden"
                    end tell
                end tell
            ''')
            if check.strip() == "hidden":
                run_applescript("""
                    tell application "System Events"
                        key code 111 using {option down}
                    end tell
                """)
                time.sleep(0.3)
        # Get terminal tab positions from AX tree
        # For JetBrains IDEs, the terminal tool window description is like "Local (N) Tool Window"
        # and contains AXStaticText tabs named "Terminal", "Local (2)", etc.
        result = run_applescript(f'''
            tell application "System Events"
                tell process "{escape_applescript(process_name)}"
                    set w to first window whose name contains "{escape_applescript(project)}"
                    set rootPane to first UI element of w whose role is "AXGroup"
                    set panels to every UI element of rootPane whose role is "AXGroup"
                    set output to ""
                    repeat with p in panels
                        try
                            set d to description of p
                            if d ends with "Tool Window" and d is not "Project Tool Window" then
                                -- Check if this panel has a "Terminal" tab (confirms it's the terminal panel)
                                set tabs to every UI element of p whose role is "AXStaticText"
                                set hasTermTab to false
                                repeat with t in tabs
                                    if description of t is "Terminal" then
                                        set hasTermTab to true
                                    end if
                                end repeat
                                if hasTermTab then
                                    repeat with t in tabs
                                        set tp to position of t
                                        set ts to size of t
                                        if (item 1 of tp) > 0 then
                                            set output to output & (item 1 of tp) & "," & (item 2 of tp) & "," & (item 1 of ts) & "," & (item 2 of ts) & linefeed
                                        end if
                                    end repeat
                                end if
                            end if
                        end try
                    end repeat
                    return output
                end tell
            end tell
        ''')
        if result:
            tabs = []
            _tab_fields = 4
            for line in result.strip().splitlines():
                parts = line.split(",")
                if len(parts) == _tab_fields:
                    try:
                        x, y, w, h = (int(float(p)) for p in parts)
                    except (ValueError, TypeError):
                        continue
                    tabs.append((x + w // 2, y + h // 2))  # center of tab
            if tabs and tab_index < len(tabs):
                cx, cy = tabs[tab_index]
                _click_at(cx, cy)


def _find_jetbrains_process() -> str:
    """Find the running JetBrains IDE process name via System Events."""
    if not is_accessibility_trusted():
        log.warning("focus: skipping System Events — Accessibility permission not granted")
        return "pycharm"
    result = run_applescript("""
        tell application "System Events"
            set jbNames to {"pycharm", "idea", "webstorm", "goland", "rubymine", "clion", "phpstorm", "rider"}
            repeat with n in jbNames
                if exists process n then return n as text
            end repeat
        end tell
        return "pycharm"
    """)
    return result.strip() or "pycharm"


def focus_session(session: ClaudeSession) -> None:
    log.info("focus: pid=%d project=%s host=%s", session.pid, session.project, session.host_app.value)
    if session.host_app == HostApp.PYCHARM:
        proc = _find_jetbrains_process()
        _focus_ide_tab(proc, session.project, session.tab_index)
    elif session.host_app == HostApp.VSCODE:
        _focus_ide_tab("Code", session.project, session.tab_index)
    elif session.window_id is not None:
        # 1. Unminimize and reorder target window to front within Terminal
        # 2. Activate Terminal without raising all windows — use
        #    NSApplicationActivateIgnoringOtherApps (1 << 1 = 2) without
        #    NSApplicationActivateAllWindows (1 << 0 = 1)
        # window_id is always int — validated via isdigit() in detection.py
        run_applescript(f"""
            tell application "Terminal"
                set miniaturized of window id {session.window_id} to false
                set index of window id {session.window_id} to 1
            end tell
        """)
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.Terminal"):
            app.activateWithOptions_(1 << 1)  # NSApplicationActivateIgnoringOtherApps only
    else:
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.Terminal"):
            app.activateWithOptions_(1 << 1)

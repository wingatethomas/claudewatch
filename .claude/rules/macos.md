---
paths:
  - "claudewatch/ui/**/*.py"
  - "claudewatch/backend/core/helpers.py"
  - "claudewatch/backend/detection/**/*.py"
  - "claudewatch/backend/notifications/**/*.py"
---

- **Menu bar app uses direct AppKit** — `NSStatusBar`, `NSMenu`, `NSMenuItem`, `NSTimer`, `AppHelper.runEventLoop()`.
- **Callback dispatch:** `_AppDelegate` maps `NSMenuItem` tags (integers) to Python callables. Use `_make_menu_item(title, callback, delegate)` to create items. Always clear `_callbacks` dict and reset `_next_tag` when rebuilding the menu to prevent leaks.
- **NSObject subclasses must use `objc.super()`** — never use Python's `super()` in PyObjC classes. Pattern: `self = objc.super(ClassName, self).init()`.
- **Quit uses `AppHelper.stopEventLoop()`** — not `NSApplication.terminate_()`, which doesn't work with `AppHelper.runEventLoop()`. Ctrl+C also uses `stopEventLoop` via a SIGINT handler.
- **Restart uses `os.execv(sys.executable, [sys.executable] + sys.argv)`** — replaces the process in-place.
- **`NSApplicationActivationPolicyAccessory`** — set in `run()` for menu-bar-only mode (no dock icon).
- Terminal.app AppleScript must be guarded with `if application "Terminal" is running`.
- **Window focus must only raise the target window, never all windows of the app.** For Terminal.app, use `set index of window id X to 1` + `activateWithOptions_(1 << 1)` (without `NSApplicationActivateAllWindows`). Never use `-activate` with terminal-notifier for Terminal.app — use `-execute` with targeted AppleScript instead.
- Always `NSImage.copy()` before calling `setSize_` on images from `NSWorkspace`.
- Pair `NSImage.lockFocus()` with `unlockFocus()` in try/finally.
- Thread-safety: use `threading.Event` or similar guards when background threads update UI objects that may be deallocated (e.g. modal text fields).
- Check `AXIsProcessTrusted()` on launch and show a menu item if permission is missing.

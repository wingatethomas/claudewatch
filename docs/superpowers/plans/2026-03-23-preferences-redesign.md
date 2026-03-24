# Preferences Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace sidebar-tabbed preferences with a single-page System Settings-style layout using grouped rounded cards.

**Architecture:** Complete rewrite of `preferences.py`. Drop sidebar/NSTableView, build a single scrollable NSView with four card groups (Notifications, Sessions, Recent Sessions, About). Right-click context menu on history rows. Same public API (`show_preferences()`), same backend repositories.

**Tech Stack:** PyObjC (AppKit NSBox, NSSwitch, NSMenu, NSMenuItem), rumps

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `claudewatch/ui/preferences.py` | Rewrite | Single-page settings window with grouped cards |

No new files. Same public API. All backend code untouched.

---

## Chunk 1: Rewrite preferences.py

### Task 1: Strip old sidebar infrastructure

**Files:**
- Modify: `claudewatch/ui/preferences.py`

- [ ] **Step 1: Remove sidebar imports and constants**

Remove `NSTableColumn`, `NSTableView` from AppKit imports. Remove `_SECTIONS`, `_content_views` dict. Add `NSMenu`, `NSMenuItem` imports.

- [ ] **Step 2: Remove sidebar delegate methods**

Remove from `_PrefsDelegate`:
- `numberOfRowsInTableView_`
- `tableView_viewForTableColumn_row_`
- `tableViewSelectionDidChange_`
- `_content_container` attribute

- [ ] **Step 3: Remove old pane builder functions**

Remove `_build_general_view`, `_build_about_view`, `_build_history_view`.

- [ ] **Step 4: Verify it still imports cleanly**

Run: `uv run python -c "from claudewatch.ui.preferences import show_preferences"`
Expected: No import error (show_preferences still exists but will be rewritten next)

- [ ] **Step 5: Commit**

```bash
git add claudewatch/ui/preferences.py
git commit -m "refactor: strip old sidebar infrastructure from preferences"
```

### Task 2: Build the card layout system

**Files:**
- Modify: `claudewatch/ui/preferences.py`

- [ ] **Step 1: Update window constants**

```python
_W = 500
_H = 420
_PAD = 20
_CARD_PAD = 16
_CARD_GAP = 12
_CARD_RADIUS = 10.0
```

- [ ] **Step 2: Add card builder helper**

```python
def _make_card(y: float, height: float, content_w: float) -> tuple[NSBox, float]:
    """Create a rounded card. Returns (card, inner_y for content placement)."""
    card = NSBox.alloc().initWithFrame_(NSMakeRect(_PAD, y, content_w, height))
    card.setBoxType_(4)  # NSBoxCustom
    card.setCornerRadius_(_CARD_RADIUS)
    card.setBorderWidth_(0)
    card.setFillColor_(NSColor.controlBackgroundColor())
    card.setContentViewMargins_(NSMakeSize(0, 0))
    return card
```

- [ ] **Step 3: Add section header helper**

```python
def _make_header(text: str, y: float) -> NSTextField:
    """Create an uppercase section header label."""
    label = NSTextField.labelWithString_(text.upper())
    label.setFrame_(NSMakeRect(_PAD + _CARD_PAD, y, 200, 14))
    label.setFont_(NSFont.systemFontOfSize_weight_(11.0, 0.6))
    label.setTextColor_(NSColor.secondaryLabelColor())
    return label
```

- [ ] **Step 4: Add row helpers**

```python
def _make_row_label(text: str, x: float, y: float, w: float) -> NSTextField:
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, 18))
    label.setFont_(NSFont.systemFontOfSize_(13.0))
    return label

def _make_hint(text: str, x: float, y: float, w: float) -> NSTextField:
    label = NSTextField.labelWithString_(text)
    label.setFrame_(NSMakeRect(x, y, w, 14))
    label.setFont_(NSFont.systemFontOfSize_(11.0))
    label.setTextColor_(NSColor.tertiaryLabelColor())
    return label

def _make_separator(x: float, y: float, w: float) -> NSBox:
    sep = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, 1))
    sep.setBoxType_(2)  # NSBoxSeparator
    return sep

def _make_link_button(text: str, x: float, y: float, target: object, action: bytes) -> NSButton:
    btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, len(text) * 8 + 10, 18))
    btn.setTitle_(text)
    btn.setBezelStyle_(0)  # inline / borderless
    btn.setBordered_(False)
    attr = NSMutableAttributedString.alloc().initWithString_(text)
    r = NSRange(0, len(text))
    attr.addAttribute_value_range_("NSFont", NSFont.systemFontOfSize_(11.0), r)
    attr.addAttribute_value_range_("NSColor", NSColor.systemBlueColor(), r)
    btn.setAttributedTitle_(attr)
    btn.setTarget_(target)
    btn.setAction_(objc.selector(action, signature=b"v@:@"))
    return btn
```

- [ ] **Step 5: Commit**

```bash
git add claudewatch/ui/preferences.py
git commit -m "refactor: add card layout helpers for System Settings style"
```

### Task 3: Build the four cards

**Files:**
- Modify: `claudewatch/ui/preferences.py`

- [ ] **Step 1: Rewrite `show_preferences` with scrollable card layout**

Replace the sidebar/pane code with a single `_FlippedView` inside an `NSScrollView`. Build all four cards top-to-bottom:

1. Notifications card (~80px): toggle + sound picker
2. Sessions card (~60px): pin expiry dropdown + hint
3. Recent Sessions card (~220px max): history list with internal scroll
4. About card (~90px): version + audit log + github rows

Window: 500x420, fixed size, title "ClaudeWatch".

- [ ] **Step 2: Build Notifications card**

Two rows: notification toggle (NSButton switch type) and sound popup. Existing delegate methods `notificationsToggled_` and `soundChanged_` unchanged.

- [ ] **Step 3: Build Sessions card**

One row: pin expiry popup with hint text below. Existing delegate method `expiryChanged_` unchanged.

- [ ] **Step 4: Build Recent Sessions card**

History entries from `get_history()` rendered in a `_FlippedView` inside a nested `NSScrollView` (max ~220px). Each row: project name + meta line on left, blue "Resume" and "Activity" link buttons on right. Rows separated by 1px lines.

- [ ] **Step 5: Build About card**

Three rows: Version (static label), Audit Log (blue link → Console.app), Source Code (blue link → GitHub). Existing delegate methods `viewAuditLog_` and `openRepo_` unchanged.

- [ ] **Step 6: Run the app and verify**

Run: `uv run claudewatch`
Open Preferences from the menu. Verify: single page, four cards, all controls functional.

- [ ] **Step 7: Commit**

```bash
git add claudewatch/ui/preferences.py
git commit -m "feat: System Settings-style preferences with grouped cards"
```

### Task 4: Add right-click context menu to history rows

**Files:**
- Modify: `claudewatch/ui/preferences.py`

- [ ] **Step 1: Add context menu delegate method**

Add to `_PrefsDelegate`:
```python
def showContextMenu_(self, sender):
    """Show right-click context menu for a history entry."""
    data = str(sender.representedObject())
    # data format: "session_id|project|cwd"
    ...build NSMenu with Resume, Activity, separator, Delete...
```

- [ ] **Step 2: Attach context menu to history row views**

For each history entry, create an `NSMenu` with three items (Resume, Activity, Delete) and attach it to the row's container view via `setMenu_`.

- [ ] **Step 3: Style Delete as destructive**

Use `NSColor.systemRedColor()` attributed title for the Delete menu item.

- [ ] **Step 4: Run the app and verify right-click**

Run: `uv run claudewatch`
Right-click a history entry. Verify: Resume, Activity, Delete appear. Delete shows confirmation.

- [ ] **Step 5: Commit**

```bash
git add claudewatch/ui/preferences.py
git commit -m "feat: right-click context menu on history entries"
```

### Task 5: Lint, test, final cleanup

**Files:**
- Modify: `claudewatch/ui/preferences.py`

- [ ] **Step 1: Run ruff check and fix**

Run: `uv run ruff check . && uv run ruff format .`

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -q`
Expected: 199 passed

- [ ] **Step 3: Remove any dead imports**

Check for unused imports from the old sidebar code.

- [ ] **Step 4: Final commit**

```bash
git add claudewatch/ui/preferences.py
git commit -m "style: clean up preferences after redesign"
```

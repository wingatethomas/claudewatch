---
paths:
  - "claudewatch/ui/components/**/*.py"
  - "claudewatch/ui/preferences/**/*.py"
  - "claudewatch/ui/windows/**/*.py"
  - "claudewatch/ui/menu/**/*.py"
---

## Layout Rules

1. **Zero-frame convention**: All design system widgets (labels, buttons, toggles) MUST start with frame `(0, 0, 0, 0)`. The layout system (VStack) or the caller sets the actual frame. Never rely on intrinsic sizing.

2. **VStack owns width**: When a view is added to VStack, VStack sets its width. Don't pre-set width on views managed by VStack. VStack children with `width == 0` get `container_width - 2 * padding`.

3. **Cards own their internals**: Cards position their own children using manual coordinates inside `contentView()`. VStack only positions the card itself.

4. **No manual pixel math outside cards**: Pane layout (between header and bottom) MUST go through VStack. Manual y-tracking is only allowed inside card content views. If you find yourself writing `y -= height + spacing` at the pane level, you're doing it wrong — use `stack.add(view, height=h)`. New panes that don't use VStack will be rejected in review.

## Component Architecture

5. **Props-in, view-out**: Composites are pure functions of data. They receive everything they need as arguments and never import services.

6. **Callbacks as props**: Components receive `on_toggle`, `on_click` callbacks. Only containers (panes) wire callbacks to services.

7. **Explicit function names**: Every composite builder is named `build_<thing>()`, not just `build()`. Import should be self-documenting.

8. **Descriptive variable names**: No single-letter variables except `x`, `y`, `w`, `h` as function params. Coordinate-suffixed abbreviations (`ry`, `ty` for row-y, tool-y) and `d` for delegate are acceptable in layout code. Use `feature_card` not `c`, `content` not `cc`, `bookmark_button` not `bm_btn`.

## Delegate Pattern

9. **Thin delegate dispatch**: `PrefsDelegate` methods are one-liners that call into handler modules. Business logic lives in `handlers/`, not in the delegate.

10. **@objc_callback on all delegate methods**: Every ObjC callback method must have the `@objc_callback` decorator for crash safety.

11. **Use `get_represented_object(sender)`**: Never call `sender.representedObject()` directly. The helper handles NSMenuItem vs NSButton differences.

12. **No `import X as Y`**: Naming should be clear enough without aliasing. If a name clashes, rename the local variable instead.

13. **Use design tokens**: Import `Spacing`, `Font`, `Colors` from `components.tokens` instead of hardcoding pixel values, font sizes, or color constructors.

## AppKit Gotchas

14. **NSSwitch has no cell()**: `NSSwitch.cell()` returns None. Use `setIdentifier_()` to store represented objects on NSSwitch, and `get_represented_object()` in safety.py handles the fallback to `identifier()`. Never call `.cell().setRepresentedObject_()` on NSSwitch.

15. **Scroll position resets on pane rebuild**: `show_pane()` rebuilds the entire pane, resetting scroll to top. If you need to preserve scroll after a user action (like deleting a row), save the scroll position before the action, run the action, rebuild, then restore.

16. **Build minimal UI first, then polish**: Don't over-build on the first pass. Ship a functional version, user-test it, then iterate on spacing/colors/descriptions. Trying to get UX perfect in one commit leads to 12+ fix commits.

17. **Static lookup tables over subprocess calls**: For display data (command descriptions, label translations), use a built-in dict. Only use subprocess (`whatis`, `man`) as a background fallback for unknown entries. Never block the main thread with subprocess for UI rendering.

18. **Smoke-test new AppKit widgets**: Before using any AppKit class for the first time (NSSwitch, NSPopUpButton, etc.), verify in a test script that `cell()`, `setToolTip_()`, `representedObject()`, and other methods you plan to use actually work on that class. Don't assume API parity between widget types.

19. **Color semantics**: Red (`theme.danger`) = dangerous/critical only. Amber (`theme.warning`) = broad/wildcard but not dangerous. Gray (`theme.secondary`) = normal/specific. Don't use red for informational warnings.

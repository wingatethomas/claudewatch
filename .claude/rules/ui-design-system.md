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

4. **No manual pixel math outside cards**: Pane layout (between header and bottom) goes through VStack. Manual y-tracking is only allowed inside card content views.

## Component Architecture

5. **Props-in, view-out**: Composites are pure functions of data. They receive everything they need as arguments and never import services.

6. **Callbacks as props**: Components receive `on_toggle`, `on_click` callbacks. Only containers (panes) wire callbacks to services.

7. **Explicit function names**: Every composite builder is named `build_<thing>()`, not just `build()`. Import should be self-documenting.

8. **Descriptive variable names**: No single-letter variables except `x`, `y`, `w`, `h` as function params. Use `feature_card` not `c`, `content` not `cc`, `bookmark_button` not `bm_btn`.

## Delegate Pattern

9. **Thin delegate dispatch**: `PrefsDelegate` methods are one-liners that call into handler modules. Business logic lives in `handlers/`, not in the delegate.

10. **@objc_callback on all delegate methods**: Every ObjC callback method must have the `@objc_callback` decorator for crash safety.

11. **Use `get_represented_object(sender)`**: Never call `sender.representedObject()` directly. The helper handles NSMenuItem vs NSButton differences.

12. **No `import X as Y`**: Naming should be clear enough without aliasing. If a name clashes, rename the local variable instead.

13. **Use design tokens**: Import `Spacing`, `Font`, `Colors` from `components.tokens` instead of hardcoding pixel values, font sizes, or color constructors.

## Summary

<!-- 1–3 sentences. What changed and why. Link to the audit / issue if relevant. -->

## Changes

<!--
Bulleted list of the actual edits. Group by file or by concern, whichever
reads cleaner.
-->

## Test plan

- [ ] `ruff check .` clean
- [ ] `python3 scripts/audit_imports.py --check` clean
- [ ] Targeted tests pass locally: `uv run pytest <paths>`
- [ ] CI lint + macOS test (gated on `ready to merge` label)
- [ ] Smoke-test on macOS:
  <!-- Specific UI flow to exercise: which menu, which pane, which click. -->

<!--
Domain rule reminder (CLAUDE.md): one branch per domain. If this PR
spans more than one logical concern, split it before merging.
-->

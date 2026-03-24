- **Briefcase** builds the `.app` bundle. Config is in `pyproject.toml` under `[tool.briefcase]`.
- **Icon:** `icons/claudewatch.svg` — Briefcase generates all required sizes. Referenced via `icon = "icons/claudewatch"` (no extension) in pyproject.toml.
- **Build commands:**
  ```
  PIP_INDEX_URL=https://pypi.org/simple/ uv run briefcase create macOS --no-input
  uv run briefcase build macOS --no-input
  uv run briefcase package macOS --adhoc-sign --no-input
  ```
- **`PIP_INDEX_URL` override** is needed if the system pip config points to a private index. Briefcase's embedded pip inherits it.
- **`LSUIElement = true`** in Info.plist — menu-bar-only app, no dock icon.
- **Entitlements:** `com.apple.security.cs.allow-unsigned-executable-memory` and `com.apple.security.cs.disable-library-validation` are required for PyObjC. These are set by the Briefcase template.
- **TCC folder prompts** (Photos, Music, Downloads, etc.) are triggered by the Python framework startup, not our code. Users can safely deny them. This is a known BeeWare limitation.
- **Release workflow** (`.github/workflows/release.yml`): push a `v*` tag to build and attach `ClaudeWatch-vX.Y.Z-arm64.zip` to a GitHub Release.
- Always bump `version` in both `[project]` and `[tool.briefcase]` sections of pyproject.toml when tagging a release.

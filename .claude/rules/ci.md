---
paths:
  - ".github/**"
  - "pyproject.toml"
---

- GitHub Actions must be pinned to commit hashes, not mutable tags. Comment the version for readability (e.g. `actions/checkout@abc123 # v4`).
- Release workflow pushes a `v*` tag to build and attach `ClaudeWatch-vX.Y.Z-arm64.zip` to a GitHub Release. Tap update creates a PR on `homebrew-claudewatch`.
- Always bump `version` in both `[project]` and `[tool.briefcase]` sections of pyproject.toml when tagging a release.

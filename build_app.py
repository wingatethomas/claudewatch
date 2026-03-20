"""Build ClaudeWatch.app using Briefcase.

Usage: uv run python build_app.py
Output: dist/ClaudeWatch.app
"""

import subprocess
import sys


def main() -> None:
    """Build the macOS .app bundle."""
    # Create the app scaffold (first time only)
    subprocess.run(
        [sys.executable, "-m", "briefcase", "create", "macOS"],
        check=False,  # OK if already exists
    )

    # Build the app
    subprocess.run(
        [sys.executable, "-m", "briefcase", "build", "macOS"],
        check=True,
    )

    # Package as a standalone .app
    subprocess.run(
        [sys.executable, "-m", "briefcase", "package", "macOS", "--no-sign"],
        check=True,
    )

    print("\n" + "=" * 50)
    print("Built: macOS/ClaudeWatch/ClaudeWatch.app")
    print("Run:   open macOS/ClaudeWatch/ClaudeWatch.app")
    print("=" * 50)


if __name__ == "__main__":
    main()

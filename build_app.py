"""Build ClaudeWatch.app using py2app."""

import subprocess
import sys
from pathlib import Path

# Ensure py2app is available
subprocess.run([sys.executable, "-m", "pip", "install", "py2app"], check=True)

from setuptools import setup  # noqa: E402

APP = ["claudewatch/__main__.py"]
APP_NAME = "ClaudeWatch"
VERSION = "0.1.0"

OPTIONS = {
    "argv_emulation": False,
    "iconfile": None,  # TODO: add app icon
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "com.claudewatch.app",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "LSUIElement": True,  # No Dock icon — menu bar only
        "LSMinimumSystemVersion": "13.0",
        "NSAppleEventsUsageDescription": (
            "ClaudeWatch needs automation access to read terminal windows and focus sessions."
        ),
        "NSUserNotificationAlertStyle": "alert",
    },
    "packages": ["claudewatch", "rumps"],
    "includes": [
        "Foundation",
        "AppKit",
        "Quartz",
        "objc",
    ],
    "excludes": [
        "pytest",
        "ruff",
        "pre_commit",
        "setuptools",
        "pip",
    ],
}

# Clean previous build
for d in ["build", "dist"]:
    p = Path(d)
    if p.exists():
        import shutil

        shutil.rmtree(p)

sys.argv = ["build_app.py", "py2app"]

setup(
    name=APP_NAME,
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

print(f"\n{'=' * 50}")
print(f"Built: dist/{APP_NAME}.app")
print(f"Run:   open dist/{APP_NAME}.app")
print(f"{'=' * 50}")

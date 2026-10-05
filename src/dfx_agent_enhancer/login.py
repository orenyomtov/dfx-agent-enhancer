"""Launch at login: a LaunchAgent that opens the installed .app when you log in.

A plain plist in ~/Library/LaunchAgents works for an ad-hoc signed app (SMAppService needs a
real signature). It runs `open -g -a <app>` and exits, so launchd never owns the app process.
"""
from __future__ import annotations

import os
import plistlib

from . import env

LABEL = "com.orenyomtov.dfx-agent-enhancer"   # also the bundle id


def agent_path() -> str:
    return os.path.join(os.path.expanduser(env("LAUNCH_AGENTS") or "~/Library/LaunchAgents"), LABEL + ".plist")


def app_bundle() -> str | None:
    """The .app this process runs from, or None when run from source."""
    from Foundation import NSBundle
    b = NSBundle.mainBundle()
    return str(b.bundlePath()) if b.bundleIdentifier() == LABEL else None


def installed(app: str) -> bool:
    """False while the app runs from the DMG or from a quarantined download (App Translocation
    gives it a random read-only path): a login item there would point at nothing."""
    return not app.startswith("/Volumes/") and "/AppTranslocation/" not in app


def enabled() -> bool:
    return os.path.exists(agent_path())


def target() -> str | None:
    """The app the LaunchAgent opens."""
    try:
        with open(agent_path(), "rb") as f:
            return plistlib.load(f)["ProgramArguments"][-1]
    except Exception:
        return None


def enable(app: str) -> None:
    p = agent_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "wb") as f:
        plistlib.dump({"Label": LABEL, "ProgramArguments": ["/usr/bin/open", "-g", "-a", app],
                       "RunAtLoad": True, "LimitLoadToSessionType": "Aqua",
                       # System Settings > Login Items shows the app's name and icon, not "open"
                       "AssociatedBundleIdentifiers": [LABEL]}, f)
    os.replace(p + ".tmp", p)


def disable() -> None:
    try:
        os.remove(agent_path())
    except FileNotFoundError:
        pass

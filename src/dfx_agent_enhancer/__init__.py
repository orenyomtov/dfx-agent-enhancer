"""DFX Agent Enhancer: read-only menu-bar view of Claude Code and Cursor agent activity."""
import os

__version__ = "0.2.0"


def env(name: str) -> str | None:
    """DFX_<name>, or the pre-rename CURSOR_SCOPE_<name>."""
    return os.environ.get("DFX_" + name) or os.environ.get("CURSOR_SCOPE_" + name)

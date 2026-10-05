"""py2app config for DFX Agent Enhancer.app. scripts/build_release.sh runs it from build/ (so
setuptools does not pick up pyproject.toml); pip never sees it."""
import os
import sys

import py2app.build_app
from setuptools import setup

# py2app's own ad-hoc signing fails on this bundle; build_release.sh signs it afterwards
py2app.build_app.codesign_adhoc = lambda bundle: None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from dfx_agent_enhancer import __version__  # noqa: E402
from dfx_agent_enhancer.login import LABEL  # noqa: E402

setup(
    name="DFX Agent Enhancer",
    version=__version__,
    app=[os.path.join(ROOT, "scripts", "app_main.py")],
    options={"py2app": {
        "iconfile": os.environ["DFX_ICON"],
        "packages": ["dfx_agent_enhancer", "webview", "rumps"],
        "excludes": ["tkinter", "setuptools", "pkg_resources", "_distutils_hack"],
        "arch": "universal2",
        "plist": {
            "CFBundleName": "DFX Agent Enhancer",
            "CFBundleDisplayName": "DFX Agent Enhancer",
            "CFBundleIdentifier": LABEL,
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSUIElement": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Copyright 2026 Oren Yomtov. MIT License.",
        },
    }},
)

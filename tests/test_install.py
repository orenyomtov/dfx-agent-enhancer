"""Env var names, the config migration and the launch-at-login plist."""
import json
import os
import plistlib

from dfx_agent_enhancer import __main__ as app, env, login


def test_env_new_name_wins_old_still_works(monkeypatch):
    monkeypatch.delenv("DFX_CONFIG", raising=False)
    monkeypatch.setenv("CURSOR_SCOPE_CONFIG", "/old")
    assert env("CONFIG") == "/old"
    monkeypatch.setenv("DFX_CONFIG", "/new")
    assert env("CONFIG") == "/new"


def test_old_config_is_moved(monkeypatch, tmp_path):
    for k in ("DFX_CONFIG", "CURSOR_SCOPE_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    old = tmp_path / "Library/Application Support/CursorScope/config.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"window": "1h"}))
    assert app.load_config() == {"window": "1h"}
    assert app.config_path() == str(tmp_path / "Library/Application Support/DFX Agent Enhancer/config.json")
    assert os.path.exists(app.config_path()) and not old.parent.exists()


def test_launch_agent_plist(monkeypatch, tmp_path):
    monkeypatch.setenv("DFX_LAUNCH_AGENTS", str(tmp_path))
    assert not login.enabled() and login.target() is None
    login.enable("/Applications/DFX Agent Enhancer.app")
    with open(login.agent_path(), "rb") as f:
        p = plistlib.load(f)
    assert p["Label"] == login.LABEL and p["RunAtLoad"] is True and p["AssociatedBundleIdentifiers"] == [login.LABEL]
    assert p["ProgramArguments"] == ["/usr/bin/open", "-g", "-a", "/Applications/DFX Agent Enhancer.app"]
    assert login.target() == "/Applications/DFX Agent Enhancer.app"
    login.disable()
    login.disable()
    assert not login.enabled()


def test_from_source_has_no_app_bundle():
    assert login.app_bundle() is None


def test_no_login_item_from_dmg_or_translocated_copy():
    assert login.installed("/Applications/DFX Agent Enhancer.app")
    assert not login.installed("/Volumes/DFX Agent Enhancer/DFX Agent Enhancer.app")
    assert not login.installed("/private/var/folders/x/AppTranslocation/ABC/d/DFX Agent Enhancer.app")

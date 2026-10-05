"""DFX Agent Enhancer: menu-bar item, config and the 2-second poll loop.

Threading: pywebview owns the main thread and the AppKit run loop (webview.start).
The rumps status item is attached to that same NSApplication from the main thread
via AppHelper.callAfter, without calling rumps.App.run(). Polling runs in the
thread pywebview starts for us. Anything that touches AppKit is sent to the main
thread with AppHelper.callAfter; anything that waits on the main thread
(evaluate_js, file dialogs) never runs on it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time

import objc
import rumps
from Foundation import NSObject
from PyObjCTools import AppHelper

from . import env, login, panel, snapshot, sources

APP_NAME = "DFX Agent Enhancer"
POLL_SECS = 2
PARSE_BUDGET = 0.5   # seconds of transcript parsing per poll while catching up
PS_SECS = 6          # `ps` costs ~0.1 s with a few hundred processes; the pid set changes rarely
CHIME_GAP = 5        # seconds: several sessions stopping together give one chime
INFO_TAG = 4242      # the menu's status lines, rebuilt each time it opens
DEBUG = bool(env("DEBUG"))
WINDOW_NAMES = (("now", "Now"), ("1h", "Last hour"), ("today", "Today"), ("week", "Week"))
METRIC_NAMES = (("tokens", "Tokens"), ("sessions", "Sessions"))


OLD_CONFIG = "~/Library/Application Support/CursorScope/config.json"   # before the rename


def config_path() -> str:
    return os.path.expanduser(env("CONFIG") or "~/Library/Application Support/%s/config.json" % APP_NAME)


def load_config() -> dict:
    old = os.path.expanduser(OLD_CONFIG)
    if not env("CONFIG") and not os.path.exists(config_path()) and os.path.exists(old):
        try:
            os.makedirs(os.path.dirname(config_path()), exist_ok=True)
            shutil.move(old, config_path())
            os.rmdir(os.path.dirname(old))
        except OSError:
            pass
    try:
        with open(config_path()) as f:
            c = json.load(f)
            return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    p = config_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, p)
    except OSError:
        pass


class _MenuWatch(NSObject):
    """Delegate of the status item's menu: rebuilds its status lines when it opens."""

    def initWithCallback_(self, fn):
        self = objc.super(_MenuWatch, self).init()
        if self is not None:
            self.fn = fn
        return self

    def menuWillOpen_(self, menu):
        self.fn()


def _play_chime() -> None:
    """Main thread. One system sound; no notification (an unbundled process cannot post them reliably)."""
    from AppKit import NSSound
    snd = NSSound.soundNamed_("Glass")
    if snd is not None:
        snd.play()


class Controller:
    def __init__(self):
        self.cfg = load_config()
        self.cfg.pop("pinnedRepo", None)     # v1 setting, gone in v2
        if self.cfg.get("window") not in snapshot.WINDOWS:
            self.cfg["window"] = "now"
        if self.cfg.get("metric") not in snapshot.METRICS:
            self.cfg.pop("metric", None)      # unset: tokens, or sessions for a Cursor-only user
        self.scanner = snapshot.Scanner()
        self.lock = threading.Lock()
        self.procs = sources.Procs()
        self.ps_at = 0.0
        self.agents: list = []
        self.live: tuple = (set(), set())    # (working, open) session keys, from the last poll
        self.scales: dict = {}               # stable spectrum full scale per (window, metric)
        self.stops = snapshot.Stops()
        self.last_stop = None                # (session name, time), for the menu
        self.chimed = 0.0
        self.snap = None
        self.ui: panel.Panel | None = None
        self.rapp: rumps.App | None = None
        self.items: dict = {}
        self._title = None
        self._icon = None
        self._info: list = []
        self._watch = None

    def toggles(self) -> dict:
        return {"chime": self.cfg.get("chime") is True, "onTop": self.cfg.get("onTop") is not False}

    # ------------------------------------------------------------ data
    def _build(self) -> dict:
        snap = snapshot.build(self.scanner, self.cfg["window"], self.cfg.get("metric"), self.procs,
                              self.agents, scales=self.scales, live=self.live)
        snap["toggles"] = self.toggles()
        return snap

    def snapshot(self) -> dict:
        stale = self.snap is None or self.snap["window"] != self.cfg["window"] or \
            ("metric" in self.cfg and self.snap["metric"] != self.cfg["metric"])
        if stale and self.lock.acquire(timeout=1):
            try:
                self.snap = self._build()
            finally:
                self.lock.release()
        if self.snap:
            self.snap["toggles"] = self.toggles()
            return self.snap
        empty = snapshot.build(snapshot.Scanner("/nonexistent", "/nonexistent"), self.cfg["window"],
                               self.cfg.get("metric"))
        empty["loading"] = True
        empty["toggles"] = self.toggles()
        return empty

    def set_window(self, w: str) -> dict:
        if w in snapshot.WINDOWS and w != self.cfg["window"]:
            self.cfg["window"] = w
            save_config(self.cfg)
        return self._changed()

    def set_metric(self, m: str) -> dict:
        if m in snapshot.METRICS and m != self.cfg.get("metric"):
            self.cfg["metric"] = m
            save_config(self.cfg)
        return self._changed()

    def toggle(self, name: str) -> dict:
        """CHIME and TOP, from the rack's band panels or the menu."""
        if name in ("chime", "onTop"):
            self.cfg[name] = not self.toggles()[name]
            save_config(self.cfg)
            if name == "onTop" and self.ui:
                self.ui.set_on_top(self.cfg[name])
        return self._changed()

    def login_at_start(self) -> None:
        """Launch at login is on by default the first time the .app runs, and follows the app
        when it is moved. Nothing happens when run from source."""
        app = login.app_bundle()
        if app is None or not login.installed(app):
            return
        if "launchAtLogin" not in self.cfg:
            self.set_login(True)
        elif login.enabled() and login.target() != app:
            login.enable(app)

    def set_login(self, on: bool) -> None:
        app = login.app_bundle()
        if app is None or not login.installed(app):
            return
        try:
            login.enable(app) if on else login.disable()
        except OSError as e:
            print("launch at login:", repr(e))
        self.cfg["launchAtLogin"] = login.enabled()
        save_config(self.cfg)
        self.update_menu()

    def _changed(self) -> dict:
        snap = self.snapshot()
        self.update_menu()
        self._set_icon(snap)
        return snap

    def poll_once(self) -> None:
        if time.time() - self.ps_at >= PS_SECS:
            self.procs = sources.read_ps()
            self.ps_at = time.time()
        self.agents = sources.read_claude_sessions(self.scanner.roots[sources.CLAUDE], self.procs.claude_pids)
        now = time.time()
        listing = self.scanner.listing(now)     # the directory walk, outside the lock
        stopped = []
        with self.lock:
            # newest files first, half a second at a time, so a cold start shows NOW and 1H
            # within a second while the rest of the week is still being read
            self.scanner.apply(*listing, now, budget=PARSE_BUDGET)
            self.live = snapshot.live_state(self.scanner, self.procs, self.agents, now)
            stopped = self.stops.update(self.agents, self.live[0], now)
            if stopped:
                names = snapshot.session_names(self.scanner, self.agents, set(stopped))
                self.last_stop = (names[0], now)
                if DEBUG:
                    print("stopped:", ", ".join(names), flush=True)
            self.snap = self._build()
        if stopped and self.toggles()["chime"] and now - self.chimed >= CHIME_GAP:
            self.chimed = now
            AppHelper.callAfter(_play_chime)

    def run_background(self) -> None:
        """Runs in pywebview's worker thread once the GUI loop is up."""
        AppHelper.callAfter(self._attach_statusbar)
        if self.ui:
            self.ui.loaded.wait(10)
            self.ui.start()
        while True:
            t = time.time()
            try:
                self.poll_once()
                if self.ui:
                    self.ui.push(self.snap)
                    self._save_anchor(self.ui.anchor)
                self._set_title(self.snap["menuTitle"])
                self._set_icon(self.snap)
            except Exception as e:  # keep polling no matter what
                print("poll error:", repr(e))
            busy = self.scanner.backlog
            time.sleep(0.05 if busy else max(0.2, POLL_SECS - (time.time() - t)))

    def remember_window(self, docked: bool, anchor) -> None:
        self.cfg["docked"] = docked
        self._save_anchor(anchor, force=True)
        self.update_menu()

    def _save_anchor(self, anchor, force=False) -> None:
        if anchor is None:
            return
        a = [round(anchor[0], 1), round(anchor[1], 1)]
        if force or a != self.cfg.get("anchor"):
            self.cfg["anchor"] = a
            save_config(self.cfg)

    # ------------------------------------------------------------ actions
    def toggle_shown(self) -> None:
        if self.ui:
            self.ui.show() if self.ui.hidden else self.ui.hide()

    def toggle_dock(self) -> None:
        if self.ui:
            self.ui.open_panel() if self.ui.mode == "mini" else self.ui.dock()

    def _from_menu(self, kind: str, value: str) -> None:
        """Worker thread (pushing to the page waits on the main thread)."""
        snap = {"window": self.set_window, "metric": self.set_metric, "toggle": self.toggle}[kind](value)
        if self.ui:
            self.ui.push(snap)

    # ------------------------------------------------------------ menu bar
    def _attach_statusbar(self) -> None:
        """Main thread. A rumps App whose status item lives in pywebview's NSApplication."""
        from AppKit import NSApplication
        from rumps.rumps import NSApp as RumpsNSApp

        NSApplication.sharedApplication().setActivationPolicy_(1)  # accessory: no Dock icon
        bg = lambda fn: (lambda _sender: threading.Thread(target=fn, daemon=True).start())
        pick = lambda kind, value: bg(lambda: self._from_menu(kind, value))
        # rumps creates ~/Library/Application Support/<name>; the same folder as our config
        app = rumps.App(APP_NAME, title="", quit_button="Quit")
        graph, window = rumps.MenuItem("Graph"), rumps.MenuItem("Window")
        for m, label in METRIC_NAMES:
            self.items["metric:" + m] = it = rumps.MenuItem(label, callback=pick("metric", m))
            graph.add(it)
        for w, label in WINDOW_NAMES:
            self.items["window:" + w] = it = rumps.MenuItem(label, callback=pick("window", w))
            window.add(it)
        self.items["chime"] = rumps.MenuItem("Chime", callback=pick("toggle", "chime"))
        self.items["onTop"] = rumps.MenuItem("Keep on Top", callback=pick("toggle", "onTop"))
        self.items["shown"] = rumps.MenuItem("Hide", callback=bg(self.toggle_shown))
        self.items["dock"] = rumps.MenuItem("Dock", callback=bg(self.toggle_dock))
        # greyed out when run from source, from the DMG or from a translocated download
        app_path = login.app_bundle()
        self.items["login"] = rumps.MenuItem("Launch at Login", callback=(
            (lambda _sender: self.set_login(not login.enabled())) if app_path and login.installed(app_path) else None))
        app.menu = [graph, window, self.items["chime"], self.items["onTop"], rumps.separator,
                    self.items["shown"], self.items["dock"], rumps.separator, self.items["login"]]
        app._icon_nsimage = panel.graph_icon(panel.icon_bars(None))
        ns = RumpsNSApp.alloc().init()
        ns._app = app.__dict__
        app._nsapp = ns
        setattr(rumps.App, "*app_instance", app)
        ns.initializeStatusBar()
        self.rapp = app
        self._watch = _MenuWatch.alloc().initWithCallback_(self._refresh_menu)
        ns.nsstatusitem.menu().setDelegate_(self._watch)
        self._refresh_menu()
        self._menu_titles()

    def _refresh_menu(self) -> None:
        """Main thread, as the menu opens: the status lines at its top (state, today's totals,
        the active sessions, the last one that stopped)."""
        if self.rapp is None:
            return
        menu = self.rapp._nsapp.nsstatusitem.menu()
        if self.lock.acquire(timeout=0.3):     # a poll holds it for a moment at most
            try:
                self._info = snapshot.menu_lines(self.scanner, self.agents, *self.live, time.time())
            except Exception as e:
                print("menu error:", repr(e))
            finally:
                self.lock.release()
        lines = list(self._info)
        if self.last_stop:
            lines.append(("Last stopped: %s · %s" % (self.last_stop[0], snapshot.ago(time.time() - self.last_stop[1])), 0))
        from AppKit import NSMenuItem
        for it in list(menu.itemArray()):
            if it.tag() == INFO_TAG:
                menu.removeItem_(it)
        for i, line in enumerate(lines + [None]):
            if line is None:
                it = NSMenuItem.separatorItem()
            else:
                it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(line[0], None, "")
                it.setIndentationLevel_(line[1])
                it.setEnabled_(False)
            it.setTag_(INFO_TAG)
            menu.insertItem_atIndex_(it, i)
        self._menu_titles()

    def _menu_titles(self) -> None:
        """Main thread."""
        if not self.items:
            return
        if self.ui:
            self.items["shown"].title = "Show" if self.ui.hidden else "Hide"
            self.items["dock"].title = "Expand" if self.ui.mode == "mini" else "Dock"
        metric = self.snap["metric"] if self.snap else self.cfg.get("metric", "tokens")
        for m, _ in METRIC_NAMES:
            self.items["metric:" + m].state = int(m == metric)
        for w, _ in WINDOW_NAMES:
            self.items["window:" + w].state = int(w == self.cfg["window"])
        t = self.toggles()
        self.items["chime"].state = int(t["chime"])
        self.items["onTop"].state = int(t["onTop"])
        self.items["login"].state = int(login.enabled())

    def update_menu(self) -> None:
        AppHelper.callAfter(self._menu_titles)

    def show_menu(self) -> None:
        def pop():
            if self.rapp is not None:
                self.rapp._nsapp.nsstatusitem.button().performClick_(None)
        AppHelper.callAfter(pop)

    def _set_title(self, text: str) -> None:
        if text != self._title and self.rapp is not None:
            self._title = text
            AppHelper.callAfter(setattr, self.rapp, "title", text)

    def _set_icon(self, snap) -> None:
        """The menu-bar icon is the graph the window shows, redrawn only when a bar changes."""
        bars = panel.icon_bars(snap["spectrum"][snap["metric"]]["heights"])
        if bars != self._icon and self.rapp is not None:
            self._icon = bars

            def apply():
                from AppKit import NSScreen
                win = self.rapp._nsapp.nsstatusitem.button().window()
                scale = (win or NSScreen.mainScreen()).backingScaleFactor()
                self.rapp._icon_nsimage = panel.graph_icon(bars, scale)
                self.rapp._nsapp.setStatusBarIcon()
            AppHelper.callAfter(apply)


USAGE = "usage: dfx-agent-enhancer [--launch-at-login on|off]"


def main(args: list | None = None) -> None:
    if args is None:
        args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    if args:
        # for install.sh: run the installed app's binary with this flag, it exits at once
        if len(args) != 2 or args[0] != "--launch-at-login" or args[1] not in ("on", "off"):
            sys.exit(USAGE)
        app_path = login.app_bundle()
        if app_path is None or not login.installed(app_path):
            sys.exit("--launch-at-login works only from the installed .app")
        Controller().set_login(args[1] == "on")
        print("launch at login:", "on" if login.enabled() else "off", "(%s)" % login.agent_path())
        return
    ctrl = Controller()
    ctrl.login_at_start()
    ctrl.ui = panel.Panel(ctrl)
    panel.start(ctrl)


if __name__ == "__main__":
    main()

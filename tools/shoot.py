"""Run the real app, capture the panel and the deck, check hide/show, then quit.

    PYTHONPATH=src DFX_CURSOR_ROOT=... DFX_CLAUDE_ROOT=... \
    DFX_CONFIG=/tmp/dfx-demo/config.json .venv/bin/python tools/shoot.py OUTDIR [WAIT_SECS] \
    [--tips] [--menubar] [--hover] [--no-fix]

Writes OUTDIR/panel.png and OUTDIR/mini.png (2x, transparent outside the rack) and prints
which windows are visible after each switch. Docking, opening and hiding go through real DOM
clicks, so this also checks the window model. The app quits itself at the end.

--tips shows the rack's tooltip on a few bars and controls (tip-*.png) by telling the page where
the mouse is, the way the hover forwarder does; the real mouse is not touched.
--menubar captures the status item (menubar.png) and the menu opened from it (menu-open.png).
--top turns Keep on Top off, checks that iTerm2 can cover the rack and that Show brings it
forward without activating the app, then turns it back on.

--hover moves the real mouse (CGEventPost; needs Accessibility for the terminal) over a few
controls while another app is frontmost, prints what the page reports as :hover and which
cursor is showing after resting 1 s, saves hover-*.png / press-*.png, checks that one click on
an inactive window reaches the page, and puts the mouse back. It starts 15 s after launch and
only once nobody has touched the mouse or keyboard for 5 s, and flags a spot when someone
else moved the mouse during it (a person using the machine makes the results meaningless). --no-fix skips the ActiveAlways tracking
area swap, to see WKWebView's default behaviour.
"""
import os
import subprocess
import sys
import threading
import time

import Quartz
from AppKit import NSCursor, NSScreen, NSWorkspace
from PyObjCTools import AppHelper

from dfx_agent_enhancer import __main__ as app
from dfx_agent_enhancer import panel
from dfx_agent_enhancer.panel import SIZE

args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = args[0]
WAIT = float(args[1]) if len(args) > 1 else 5
HOVER = "--hover" in sys.argv
GLIDE_WAIT = 1.0        # rest on each control this long, so a cursor reset by the frontmost app shows
SETTLE = 15             # seconds after launch before the hover probe starts
os.makedirs(OUT, exist_ok=True)
if "--no-fix" in sys.argv:
    panel.Panel._hover_always = lambda self: None


def window_id(size):
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        b = w["kCGWindowBounds"]
        if w.get("kCGWindowOwnerPID") == os.getpid() and (round(b["Width"]), round(b["Height"])) == size:
            return w["kCGWindowNumber"]
    return None


def visible():
    return {k: bool(window_id(v)) for k, v in SIZE.items()}


def shot(name, size):
    n = window_id(size)
    if n:
        subprocess.run(["screencapture", "-x", "-o", "-l%d" % n, os.path.join(OUT, name + ".png")], check=False)
    print(name, "captured" if n else "NOT VISIBLE", "| visible:", visible(), flush=True)


def on_main(fn):
    box, done = [], threading.Event()

    def run():
        try:
            box.append(fn())
        finally:
            done.set()
    AppHelper.callAfter(run)
    done.wait(3)
    return box[0] if box else None


# ------------------------------------------------------------ real mouse
def mouse_pos():
    p = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return p.x, p.y


def post(kind, x, y):
    e = Quartz.CGEventCreateMouseEvent(None, kind, (x, y), Quartz.kCGMouseButtonLeft)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)


def page_to_screen(ui, px, py):
    f = on_main(lambda: ui._nswindow().frame())
    h = NSScreen.screens()[0].frame().size.height
    return f.origin.x + px, h - (f.origin.y + f.size.height) + py


def glide(ui, px, py):
    x, y = page_to_screen(ui, px, py)
    for k in range(6, -1, -1):          # a few steps in, like a hand would
        post(Quartz.kCGEventMouseMoved, x + 3 * k, y + 2 * k)
        time.sleep(0.03)
    time.sleep(GLIDE_WAIT)
    if (round(mouse_pos()[0]), round(mouse_pos()[1])) != (round(x), round(y)):
        print("  !! the mouse was moved by someone else; this spot is not valid", flush=True)
    return x, y


def wait_idle(secs=5, limit=120):
    """Do not fight a person for the mouse: wait until there was no real input for a few seconds."""
    t = time.time()
    while time.time() - t < limit:
        idle = Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateHIDSystemState,
                                                             Quartz.kCGAnyInputEventType)
        if idle >= secs:
            return
        time.sleep(1)
    print("  !! the user kept using the machine; hover results may be disturbed", flush=True)


def other_windows():
    """Windows of this process besides the rack (a tooltip shows up as one)."""
    out = []
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        b = w["kCGWindowBounds"]
        if w.get("kCGWindowOwnerPID") == os.getpid() and (round(b["Width"]), round(b["Height"])) not in SIZE.values():
            out.append((round(b["Width"]), round(b["Height"])))
    return out


def frontmost():
    return NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()


def editor_front():
    subprocess.run(["open", "-a", "iTerm"], check=False)
    time.sleep(0.8)


def hover_state(ui):
    hov = ui.window.evaluate_js(
        "Array.prototype.slice.call(document.querySelectorAll(':hover, .hover'))"
        ".map(function(e){return e.id || e.className.baseVal || e.className}).slice(-2).join(' > ')")
    hand = on_main(lambda: NSCursor.currentSystemCursor().hotSpot() == NSCursor.pointingHandCursor().hotSpot())
    return hov, "hand" if hand else "arrow"


def tracking(ui):
    from webview.platforms.cocoa import BrowserView
    wv = BrowserView.instances[ui.window.uid].webview
    return on_main(lambda: [hex(t.options()) for t in wv.trackingAreas() if t.owner() == wv])


def probe(ui, mode):
    while time.time() - STARTED < SETTLE:
        time.sleep(0.2)
    wait_idle()
    home = mouse_pos()
    try:
        editor_front()
        print("web view tracking areas:", tracking(ui), "| forwarded events:", getattr(getattr(ui, "_hover", None), "n", None), flush=True)
        print("frontmost:", frontmost(), "| key window:", on_main(lambda: bool(ui._nswindow().isKeyWindow())), flush=True)
        if mode == "panel":
            spots = [("wkey", 214, 196), ("toggle", 33, 197), ("slider", 109, 230), ("tab", 196, 57),
                     ("chime", 136, 355), ("oval", 136, 401), ("chev", 21, 33),
                     ("bar1", 37, 140), ("bar5", 129, 100), ("bar10", 244, 120)]
        else:
            spots = [("dome", 14, 14), ("mkey", 18, 55), ("display", 73, 22)]
        for name, px, py in spots:
            glide(ui, px, py)
            hov, cur = hover_state(ui)
            print("hover %-8s page :hover = %-28s cursor = %s" % (name, hov or "-", cur), flush=True)
            if name == "slider":
                time.sleep(1.5)
                print("tooltip windows after 1.9 s:", other_windows(), flush=True)
            print("  page tooltip:", ui.window.evaluate_js(
                "var t=document.getElementById('tip'); t.style.display==='block' ? t.innerText.replace(/\\n/g,' | ') : '-'"),
                flush=True)
            shot("hover-%s-%s" % (mode, name), SIZE[mode])
        if mode == "panel":
            # press look: hold the button down on an inert toggle key
            x, y = glide(ui, 33, 225)
            post(Quartz.kCGEventLeftMouseDown, x, y)
            time.sleep(0.3)
            shot("press-panel-toggle", SIZE[mode])
            print("pressed:", ui.window.evaluate_js(
                "Array.prototype.slice.call(document.querySelectorAll(':active')).map(function(e){return e.className}).join(' > ')"), flush=True)
            post(Quartz.kCGEventLeftMouseUp, x, y)
            time.sleep(0.3)
            # does one click on the inactive window reach the page?
            editor_front()
            x, y = glide(ui, 214, 214)      # the 1H key
            post(Quartz.kCGEventLeftMouseDown, x, y)
            post(Quartz.kCGEventLeftMouseUp, x, y)
            time.sleep(1.0)
            sel = ui.window.evaluate_js("document.querySelector('.wkey.on').dataset.w")
            print("first click on inactive window selected:", sel, "| frontmost now:", frontmost(), flush=True)
            glide(ui, 109, 230)
            print("hover with the app active:", hover_state(ui), flush=True)
            x, y = glide(ui, 214, 196)      # back to NOW
            post(Quartz.kCGEventLeftMouseDown, x, y)
            post(Quartz.kCGEventLeftMouseUp, x, y)
            time.sleep(0.5)
    finally:
        post(Quartz.kCGEventMouseMoved, *home)
        editor_front()


def tip_shots(ui):
    """The rack's own tooltip, driven like the hover forwarder does it, without the real mouse."""
    spots = [("bar1", 37, 140), ("bar5", 129, 120), ("bar6", 152, 100), ("bar10", 244, 120), ("readout", 196, 57),
             ("lime", 70, 57), ("row-tokens", 110, 250), ("digits", 159, 257), ("chime", 136, 355), ("top", 238, 355)]
    for name, px, py in spots:
        ui.window.evaluate_js("__hoverAt(%d, %d)" % (px, py))
        time.sleep(0.8)
        text = ui.window.evaluate_js(
            "var t=document.getElementById('tip'); t.style.display==='block' ? "
            "'[' + [t.offsetLeft, t.offsetTop, t.offsetWidth, t.offsetHeight] + '] ' + t.innerText.replace(/\\n/g,' | ') : '-'")
        print("tip %-10s %s" % (name, text), flush=True)   # [left, top, width, height] in rack px
        shot("tip-" + name, SIZE["panel"])
    ui.window.evaluate_js("__hoverAt(-1, -1)")


def menubar_shots(ctrl):
    """The status item, then the menu opened from it (the item shows highlighted)."""
    def frame():
        w = ctrl.rapp._nsapp.nsstatusitem.button().window()
        return w.frame() if w is not None else None
    f = on_main(frame)
    if f is None:
        print("menubar: no status item window", flush=True)
        return
    scr = NSScreen.screens()[0].frame().size
    x, y = f.origin.x, scr.height - f.origin.y - f.size.height
    print("status item at", (round(x), round(y), round(f.size.width), round(f.size.height)),
          "| title:", repr(ctrl.rapp.title), flush=True)
    region = lambda l, t, w, h: "-R%d,%d,%d,%d" % (max(0, l), max(0, t), min(w, scr.width - max(0, l)), h)
    subprocess.run(["screencapture", "-x", region(x - 24, y, f.size.width + 48, f.size.height),
                    os.path.join(OUT, "menubar.png")], check=False)
    ctrl.show_menu()
    time.sleep(1.5)
    subprocess.run(["screencapture", "-x", region(x - 330, y, 420 + f.size.width, 400),
                    os.path.join(OUT, "menu-open.png")], check=False)
    lines = on_main(lambda: [i.title() for i in ctrl.rapp._nsapp.nsstatusitem.menu().itemArray()])
    print("menu:", lines, flush=True)
    AppHelper.callAfter(lambda: ctrl.rapp._nsapp.nsstatusitem.menu().cancelTracking())
    time.sleep(0.8)


def top_check(ctrl):
    """TOP off: normal window level, so another app's window can cover the rack; Show still
    brings it forward without activating the app."""
    ui = ctrl.ui

    def order():
        """Front-to-back on-screen windows: is the rack above iTerm2's frontmost window?"""
        names = [(w.get("kCGWindowOwnerName"), w.get("kCGWindowOwnerPID") == os.getpid(), w.get("kCGWindowLayer"))
                 for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)]
        rack = next((i for i, n in enumerate(names) if n[1] and n[2] in (0, 25)), None)
        term = next((i for i, n in enumerate(names) if (n[0] or "").startswith("iTerm") and n[2] == 0), None)
        if term is None:
            return "no iTerm window on screen"
        return "rack above iTerm" if rack is not None and rack < term else "rack BELOW iTerm"
    level = lambda: on_main(lambda: ui._nswindow().level())
    active = lambda: on_main(lambda: bool(__import__("AppKit").NSApplication.sharedApplication().isActive()))
    def raise_iterm():
        """Bring iTerm's windows forward even when it is already the active app."""
        from AppKit import NSApplicationActivateAllWindows, NSRunningApplication
        for a in NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.googlecode.iterm2"):
            a.activateWithOptions_(NSApplicationActivateAllWindows)
        time.sleep(1.0)
    raise_iterm()
    print("TOP on: level", level(), "| after raising iTerm:", order(), flush=True)
    ctrl.toggle("onTop")
    raise_iterm()
    print("TOP off: level", level(), "| after raising iTerm:", order(), "| frontmost:", frontmost(), flush=True)
    ui.hide()
    ui.show()
    time.sleep(0.5)
    print("after Show:", order(), "| frontmost:", frontmost(), "| app active:", active(), flush=True)
    ctrl.toggle("onTop")
    print("TOP back on: level", level(), "| config:", ctrl.toggles(), flush=True)


STARTED = time.time()


def script(ctrl):
    ui = ctrl.ui
    ui.loaded.wait(15)
    if ui.mode == "mini":
        ui.open_panel()
    time.sleep(WAIT)
    shot("panel", SIZE["panel"])
    if "--tips" in sys.argv:
        tip_shots(ui)
    if "--menubar" in sys.argv:
        menubar_shots(ctrl)
    if "--top" in sys.argv:
        top_check(ctrl)
    if HOVER:
        probe(ui, "panel")
    ui.window.evaluate_js("document.getElementById('oval').click()")
    time.sleep(2.5)
    shot("mini", SIZE["mini"])
    if HOVER:
        probe(ui, "mini")
    ui.window.evaluate_js("document.getElementById('mini').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
    time.sleep(2.5)
    print("reopened:", visible(), flush=True)
    ui.window.evaluate_js("document.getElementById('dash').click()")
    time.sleep(1.0)
    menu = lambda: [ctrl.items[k].title for k in ("shown", "dock")]
    print("after dash (hide):", visible(), "| hidden:", ui.hidden, "| menu:", menu(), flush=True)
    ctrl.toggle_shown()     # the menu's Show
    time.sleep(1.0)
    print("after menu Show:", visible(), "| mode:", ui.mode, "| menu:", menu(), flush=True)
    ctrl.toggle_dock()      # the menu's Dock
    time.sleep(2.0)
    print("after menu Dock:", visible(), "| menu:", menu(), flush=True)
    ui.window.evaluate_js("document.getElementById('dome-expand').click()")
    time.sleep(2.0)
    print("after deck ^ dome:", visible(), "| menu:", menu(), flush=True)
    AppHelper.callAfter(lambda: __import__("AppKit").NSApplication.sharedApplication().terminate_(None))


_orig = app.Controller.run_background


def run_background(self):
    threading.Thread(target=script, args=(self,), daemon=True).start()
    _orig(self)


app.Controller.run_background = run_background
app.main([])

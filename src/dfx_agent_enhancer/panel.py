"""The one pywebview window. It shows either the rack panel or, when docked, the mini deck.

Only one is ever visible: docking hides the panel content, shrinks the same window to the
deck size and shows the deck; opening does the reverse. The window is placed so the lime
power oval stays under the mouse, which makes DOCK and undock feel like the original's
mini-mode switch.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading

import webview
from PyObjCTools import AppHelper

from . import env

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
APP_NAME = "DFX Agent Enhancer"

SIZE = {"panel": (272, 436), "mini": (146, 92)}
# centre of the lime power oval, from each view's top-left corner
OVAL = {"panel": (136.0, 401.5), "mini": (73.0, 74.3)}


def page(mode: str) -> str:
    """ui/index.html with its CSS, JS and SVG assets inlined (no file URL, no local server)."""
    def read(name, binary=False):
        with open(os.path.join(UI_DIR, name), "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as f:
            return f.read()

    html = read("index.html")
    for css in ("assets/outlines.css", "app.css"):
        html = html.replace('<link rel="stylesheet" href="%s">' % css, "<style>\n%s\n</style>" % read(css))
    html = html.replace('<script src="app.js"></script>',
                        "<script>window.MODE = %s;\n%s\n</script>" % (json.dumps(mode), read("app.js")))

    def data_uri(m):
        name = m.group(1)
        mime = "image/svg+xml" if name.endswith(".svg") else "image/png"
        return 'src="data:%s;base64,%s"' % (mime, base64.b64encode(read(name, binary=True)).decode())
    return re.sub(r'src="(assets/[^"]+)"', data_uri, html)


class Api:
    """Methods the page calls as window.pywebview.api.<name>(). Each call runs in its own thread."""

    def __init__(self, ctrl):
        self._ctrl = ctrl

    def snapshot(self):
        return self._ctrl.snapshot()

    def set_window(self, w):
        return self._ctrl.set_window(w)

    def set_metric(self, m):
        return self._ctrl.set_metric(m)

    def dock(self):
        self._ctrl.ui.dock()

    def drag_start(self):
        self._ctrl.ui.drag_start()

    def hide(self):
        self._ctrl.ui.hide()

    def open_panel(self):
        self._ctrl.ui.open_panel()

    def menu(self):
        self._ctrl.show_menu()

    def toggle(self, name):
        return self._ctrl.toggle(name)


class Panel:
    def __init__(self, ctrl):
        self.ctrl = ctrl
        self.mode = "mini" if ctrl.cfg.get("docked") else "panel"
        self.loaded = threading.Event()
        self.switch_lock = threading.Lock()
        self.anchor = None          # oval centre in Cocoa screen coordinates (y up)
        self.hidden = False         # hidden to the menu bar; not persisted
        self._grab = None           # at the last mouse-down on the window: mouse minus window origin
        self._dragging = False
        w, h = SIZE[self.mode]
        self.window = webview.create_window(
            APP_NAME, html=page(self.mode), js_api=Api(ctrl), width=w, height=h,
            frameless=True, easy_drag=False, resizable=False, transparent=True, shadow=False,
            on_top=True, hidden=True, background_color="#000000")
        self.window.events.loaded += self.loaded.set
        self.window.events.moved += self._moved

    # ------------------------------------------------------------ geometry (main thread only)
    def _nswindow(self):
        from webview.platforms.cocoa import BrowserView
        inst = BrowserView.instances.get(self.window.uid)
        return inst.window if inst else None

    @staticmethod
    def _frame(mode, anchor):
        from Foundation import NSMakeRect
        w, h = SIZE[mode]
        ox, oy = OVAL[mode]
        return NSMakeRect(round(anchor[0] - ox), round(anchor[1] + oy - h), w, h)

    @staticmethod
    def _anchor_of(mode, frame):
        ox, oy = OVAL[mode]
        return (frame.origin.x + ox, frame.origin.y + frame.size.height - oy)

    @staticmethod
    def _on_screen(frame) -> bool:
        from AppKit import NSScreen
        from Foundation import NSIntersectsRect
        return any(NSIntersectsRect(frame, s.visibleFrame()) for s in NSScreen.screens())

    def _default_anchor(self):
        from AppKit import NSScreen
        vf = NSScreen.mainScreen().visibleFrame()
        w, _ = SIZE["panel"]
        left, top = vf.origin.x + vf.size.width - w - 24, vf.origin.y + vf.size.height - 24
        return (left + OVAL["panel"][0], top - OVAL["panel"][1])

    def _place(self, mode, anchor=None):
        win = self._nswindow()
        if win is None:
            return
        if anchor is None:
            saved = self.ctrl.cfg.get("anchor")
            anchor = tuple(saved) if isinstance(saved, list) and len(saved) == 2 else None
        if anchor is None or not self._on_screen(self._frame(mode, anchor)):
            anchor = self._default_anchor()
        win.setFrame_display_(self._frame(mode, anchor), True)
        self.anchor = anchor

    def _moved(self, *_):
        win = self._nswindow()
        if win is not None:
            self.anchor = self._anchor_of(self.mode, win.frame())

    # ------------------------------------------------------------ dragging
    # pywebview's drag region moves the window from the page's MouseEvent.screenX/Y. WebKit measures
    # screenY from the top of the screen the window is on, and pywebview turns it back into Cocoa
    # coordinates with the height of the screen the window was created on. On a second display of
    # another height the window jumped by the difference (to the top of a laptop screen next to a
    # taller external one). So the page only says "a drag starts here" and the window follows the
    # mouse in Cocoa screen coordinates, keeping the offset it had at mouse-down.
    def _watch_drag(self) -> None:
        """Main thread. A local event monitor sees every mouse event of the app before the web view."""
        from AppKit import (NSEvent, NSEventMaskLeftMouseDown, NSEventMaskLeftMouseDragged, NSEventMaskLeftMouseUp,
                            NSEventTypeLeftMouseDown, NSEventTypeLeftMouseUp)

        def handler(event):
            try:
                win = self._nswindow()
                kind = event.type()
                if kind == NSEventTypeLeftMouseDown:
                    self._dragging = False
                    self._grab = None
                    if win is not None and event.window() == win:
                        m, o = NSEvent.mouseLocation(), win.frame().origin
                        self._grab = (m.x - o.x, m.y - o.y)
                elif self._dragging:
                    self._follow()
                    if kind == NSEventTypeLeftMouseUp:
                        self._dragging = False
            except Exception as e:              # never swallow the user's clicks
                print("drag:", repr(e))
            return event
        mask = NSEventMaskLeftMouseDown | NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        self._drag_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)

    def _follow(self) -> None:
        """Main thread: put the window where the grab point is under the mouse."""
        from AppKit import NSEvent
        win = self._nswindow()
        if win is None or self._grab is None:
            return
        m = NSEvent.mouseLocation()
        win.setFrameOrigin_((round(m.x - self._grab[0]), round(m.y - self._grab[1])))
        self.anchor = self._anchor_of(self.mode, win.frame())

    def drag_start(self) -> None:
        """The page saw a mouse-down on the chassis. The message arrives a few ms after the
        mouse-down, so the window catches up with the mouse at once. If the button is already up
        it was a click, and nothing moves."""
        def go():
            from AppKit import NSEvent
            if self._grab is not None and NSEvent.pressedMouseButtons() & 1:
                self._dragging = True
                self._follow()
        AppHelper.callAfter(go)

    def _on_main(self, fn):
        done = threading.Event()

        def run():
            try:
                fn()
            finally:
                done.set()
        AppHelper.callAfter(run)
        done.wait(3)

    # ------------------------------------------------------------ public, called from worker threads
    def start(self) -> None:
        """Position the window from the saved anchor, then show it."""
        self._on_main(lambda: (self._place(self.mode), self._hover_always(), self._watch_drag()))
        self.set_on_top(self.ctrl.toggles()["onTop"])
        self.show()

    def set_on_top(self, on: bool) -> None:
        """TOP: the status window level (above other windows, like DFX's always-on-top), or the
        normal level, so other windows can cover the rack like a desktop widget."""
        from AppKit import NSNormalWindowLevel, NSStatusWindowLevel

        def apply():
            win = self._nswindow()
            if win is not None:
                win.setLevel_(NSStatusWindowLevel if on else NSNormalWindowLevel)
        self._on_main(apply)

    def hide(self) -> None:
        """The window disappears; the menu-bar item keeps running. Show restores the same view."""
        self._on_main(lambda: self._nswindow() and self._nswindow().orderOut_(None))
        self.hidden = True
        self.ctrl.update_menu()

    def show(self) -> None:
        """Bring the window up without activating the app, so the editor keeps focus."""
        self._on_main(lambda: self._nswindow() and self._nswindow().orderFrontRegardless())
        self.hidden = False
        self.ctrl.update_menu()

    def _hover_always(self) -> None:
        """Main thread. The window belongs to an accessory app that is almost never active, so it
        is never the key window, and WKWebView only follows the mouse in the key window. Add a
        tracking area that is active always and tell the page where the mouse is, so the hover
        highlight, the pointer cursor and the page's own tooltips work while the editor is
        frontmost. Hovering never activates the app."""
        from AppKit import (NSTrackingActiveAlways, NSTrackingArea, NSTrackingInVisibleRect,
                            NSTrackingMouseEnteredAndExited, NSTrackingMouseMoved)
        from webview.platforms.cocoa import BrowserView
        inst = BrowserView.instances.get(self.window.uid)
        wv = inst.webview if inst else None
        if wv is None:
            return
        _accept_first_mouse(type(wv))
        _cursor_in_background()
        self._hover = _HoverForwarder.alloc().initWithView_(wv)
        wv.addTrackingArea_(NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            wv.bounds(), NSTrackingActiveAlways | NSTrackingInVisibleRect | NSTrackingMouseMoved
            | NSTrackingMouseEnteredAndExited, self._hover, None))

    def dock(self) -> None:
        self._switch("mini")
        if self.hidden:
            self.show()

    def open_panel(self) -> None:
        if self.mode != "panel":
            self._switch("panel")
            snap = self.ctrl.snap
            if snap is not None:
                self.push(snap)
        if self.hidden:
            self.show()

    def _switch(self, mode: str) -> None:
        with self.switch_lock:
            if mode == self.mode:
                return
            self.loaded.wait(5)
            old = self.mode
            try:
                self.window.evaluate_js("document.body.style.opacity='0'")
            except Exception:
                pass

            def resize():
                win = self._nswindow()
                if win is None:
                    return
                anchor = self._anchor_of(old, win.frame())
                self.mode = mode
                self._place(mode, anchor)
            self._on_main(resize)
            self.mode = mode
            try:
                self.window.evaluate_js("window.__mode(%s); document.body.style.opacity='1'" % json.dumps(mode))
            except Exception:
                pass
            self.ctrl.remember_window(mode == "mini", self.anchor)

    def push(self, snap) -> None:
        """Called from the poll thread, never the main thread (evaluate_js waits on it)."""
        if self.loaded.is_set():
            try:
                self.window.evaluate_js("window.__push && window.__push(%s)" % json.dumps(snap))
            except Exception:
                pass


from AppKit import NSTimer  # noqa: E402
from Foundation import NSObject  # noqa: E402
import objc  # noqa: E402

CURSOR_EVERY = 0.1   # seconds; how often the pointer cursor is re-set while over a control


class _HoverForwarder(NSObject):
    """Owner of the always-active tracking area. WebKit ignores mouse moves while its window is
    not key, so the page is asked which control is under the mouse (window.__hoverAt adds a
    .hover class that the CSS treats like :hover), and the cursor is set from here.

    Every event is checked against where the mouse really is, so a spurious mouseExited (seen
    in the first seconds after launch) does not clear the highlight. While the mouse is over a
    control a short timer re-reads the position, which heals a missed move or exit, and
    re-sets the pointer cursor, because the frontmost app keeps resetting it."""

    def initWithView_(self, view):
        self = objc.super(_HoverForwarder, self).init()
        if self is not None:
            self.view = view
            self.over = False
            self.sent = None
            self.timer = None
        return self

    @objc.python_method
    def _mouse(self):
        """The mouse in page coordinates, or None when it is outside the visible web view."""
        from AppKit import NSEvent
        from Foundation import NSPointInRect
        win = self.view.window()
        if win is None or not win.isVisible():
            return None
        p = self.view.convertPoint_fromView_(win.convertPointFromScreen_(NSEvent.mouseLocation()), None)
        b = self.view.bounds()
        if not NSPointInRect(p, b):
            return None
        return (int(p.x), int(p.y if self.view.isFlipped() else b.size.height - p.y))

    @objc.python_method
    def _update(self):
        p = self._mouse() or (-1, -1)
        if p == self.sent:
            return False
        self.sent = p

        def done(result, error):
            over = result == "1" and p[0] >= 0
            if over != self.over:
                self.over = over
                if over:
                    self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                        CURSOR_EVERY, self, "tick:", None, True)
                elif self.timer is not None:
                    self.timer.invalidate()
                    self.timer = None
            if p[0] >= 0:       # leaving: the app under the mouse owns the cursor
                self.setCursor_(None)
        self.view.evaluateJavaScript_completionHandler_(
            "window.__hoverAt ? __hoverAt(%d, %d) : ''" % p, done)
        return True

    def tick_(self, _):
        if not self._update():
            self.setCursor_(None)

    def setCursor_(self, _):
        from AppKit import NSCursor
        if not self.view.window().isKeyWindow():    # when key, WebKit does it
            (NSCursor.pointingHandCursor() if self.over else NSCursor.arrowCursor()).set()

    def mouseMoved_(self, event):
        self._update()

    def mouseEntered_(self, event):
        self._update()

    def mouseExited_(self, event):
        self._update()


def _cursor_in_background() -> None:
    """A background app may not change the cursor unless its window-server connection says so
    (the private CGS property other menu-bar utilities use). Best effort: without it the cursor
    stays an arrow until the rack is clicked."""
    import ctypes
    try:
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cg.CGSSetConnectionProperty.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        key = cf.CFStringCreateWithCString(None, b"SetsCursorInBackground", 0x08000100)   # UTF-8
        conn = cg._CGSDefaultConnection()
        cg.CGSSetConnectionProperty(conn, conn, key, ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue"))
    except Exception:
        pass


def _accept_first_mouse(cls) -> None:
    """Let the first click on the inactive window reach the page, so `-` and `v` need one click,
    not one to activate and a second to act."""
    import objc
    if getattr(cls, "_dfx_first_mouse", False):
        return

    def acceptsFirstMouse_(self, event):
        return True
    objc.classAddMethods(cls, [objc.selector(acceptsFirstMouse_, selector=b"acceptsFirstMouse:", signature=b"Z@:@")])
    cls._dfx_first_mouse = True


# menu-bar icon: the rack's 10 bars, 1.5 pt wide on a 2.5 pt pitch (3 px bars, 2 px gaps on Retina)
ICON_W, ICON_H = 24.0, 16.0
ICON_BAR, ICON_PITCH = 1.5, 2.5


def icon_bars(heights) -> tuple:
    """Fill heights in points for the menu-bar icon from the graph's 0..1 bar heights: snapped
    to 0.5 pt, and at least 1 pt for any value above 0."""
    out = []
    for h in (list(heights or ()) + [0] * 10)[:10]:
        h = max(0.0, min(1.0, h or 0.0))
        out.append(max(1.0, round(h * ICON_H * 2) / 2) if h > 0 else 0.0)
    return tuple(out)


def graph_icon(bars, scale: float = 2.0):
    """Template NSImage of the live graph: each bar a faint full-height track (black, 25%) and an
    opaque fill from the bottom. Drawn on demand, and a template, so the menu bar tints it for
    light, dark and highlighted (menu open) states. On a 1x screen half points blur, so the bars
    are 2 pt on a 3 pt pitch (29 pt wide) and the heights whole points."""
    from AppKit import NSBezierPath, NSColor, NSImage
    from Foundation import NSMakeRect, NSMakeSize

    if scale >= 2:
        width, bar, pitch, bars = ICON_W, ICON_BAR, ICON_PITCH, tuple(bars)
    else:
        width, bar, pitch = 29.0, 2.0, 3.0
        bars = tuple(max(1.0, float(round(h))) if h else 0.0 for h in bars)

    def draw(rect):
        for i, h in enumerate(bars):
            x = i * pitch
            NSColor.colorWithWhite_alpha_(0.0, 0.25).set()
            NSBezierPath.fillRect_(NSMakeRect(x, 0, bar, ICON_H))
            if h:
                NSColor.blackColor().set()
                NSBezierPath.fillRect_(NSMakeRect(x, 0, bar, h))
        return True

    img = NSImage.imageWithSize_flipped_drawingHandler_(NSMakeSize(width, ICON_H), False, draw)
    img.setTemplate_(True)
    return img


def start(ctrl) -> None:
    webview.start(ctrl.run_background, debug=bool(env("DEBUG")))

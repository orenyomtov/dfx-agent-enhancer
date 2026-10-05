import os
import re

from dfx_agent_enhancer import panel


def test_page_is_self_contained():
    """The window loads one HTML string: CSS, JS and SVG assets must all be inlined."""
    for mode in ("panel", "mini"):
        html = panel.page(mode)
        assert 'window.MODE = "%s"' % mode in html
        assert not re.search(r'(src|href)="(?!data:)[^"#]+"', html)
        assert html.count("data:image/svg+xml;base64,") == 3
        assert "clip-path: path(" in html


def test_menu_bar_icon_bars():
    """The menu-bar icon shows the graph's 10 bars on a 16 pt height, snapped to 0.5 pt, at least
    1 pt for anything above 0."""
    assert panel.icon_bars([0, 0.01, 0.5, 1, None, 0.031, 0.47]) == (0, 1.0, 8.0, 16.0, 0, 1.0, 7.5, 0, 0, 0)
    assert panel.icon_bars(None) == (0,) * 10
    assert 9 * panel.ICON_PITCH + panel.ICON_BAR == panel.ICON_W


def test_menu_bar_icon_draws_tracks_and_fills():
    from AppKit import NSBitmapImageRep, NSCalibratedRGBColorSpace, NSGraphicsContext
    from Foundation import NSMakeRect
    img = panel.graph_icon((0, 8.0, 16.0) + (0,) * 7)
    assert img.isTemplate() and tuple(img.size()) == (24, 16)
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, 48, 32, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    rep.setSize_((24, 16))                                     # Retina: 2 px per pt
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    img.drawInRect_(NSMakeRect(0, 0, 24, 16))
    NSGraphicsContext.restoreGraphicsState()
    alpha = lambda x, y: round(rep.colorAtX_y_(x, y).alphaComponent(), 2)     # y from the top
    assert alpha(1, 0) == 0.25 and alpha(1, 31) == 0.25        # bar 1: an empty track, full height
    assert alpha(3, 31) == 0                                   # the gap between bars
    assert alpha(6, 31) == 1 and alpha(6, 17) == 1 and alpha(6, 14) == 0.25   # bar 2: half full
    assert alpha(11, 0) == 1                                   # bar 3: full


def test_menu_bar_icon_on_a_1x_screen_uses_whole_points():
    img = panel.graph_icon((0, 7.5, 0.5) + (0,) * 7, scale=1)
    assert tuple(img.size()) == (29, 16)


def test_window_frame_and_oval_anchor_round_trip():
    """The saved position is the oval centre in Cocoa screen coordinates (y up); a frame built
    from it gives the same anchor back, also on a second display left of the main one (x < 0),
    and docking keeps the oval where it was."""
    for anchor in ((1160.0, 614.5), (-876.0, 547.5), (-756.0, 474.7)):
        for mode in ("panel", "mini"):
            f = panel.Panel._frame(mode, anchor)
            assert (f.size.width, f.size.height) == panel.SIZE[mode]
            back = panel.Panel._anchor_of(mode, f)
            assert abs(back[0] - anchor[0]) <= 0.5 and abs(back[1] - anchor[1]) <= 0.5
    f = panel.Panel._frame("panel", (100.0, 500.0))
    assert f.origin.x == 100 - 136 and abs(f.origin.y + f.size.height - (500 + 401.5)) <= 0.5   # whole points


def test_drag_regions_are_ours_and_hold_no_controls():
    """pywebview's drag region (it misplaced the window on a second display of another height) is
    not used; the page marks chassis parts with .drag and controls are never inside one."""
    html = open(os.path.join(panel.UI_DIR, "index.html")).read()
    assert "pywebview-drag-region" not in html
    drags = re.findall(r'<(\w+)[^>]*class="[^"]*\bdrag\b[^"]*"', html)
    assert drags == ["img", "div", "img", "div"]       # rack shell, title, deck shell, deck display
    deck = html[html.index('id="mscreen"'):html.index('<div class="mkeys">')]
    assert "<button" not in deck


def test_a_frame_whose_top_is_on_any_screen_is_left_alone():
    """AppKit keeps a titled window's top under one screen's menu bar; we let it be wherever its
    top edge is on some screen's usable area, so it can be dragged onto a display above."""
    laptop = (0, 0, 1512, 949)                 # visible frame, below a 33 pt menu bar
    above = (-300, 982, 2560, 1415)            # an external display placed above the laptop
    rack = lambda x, top: (x, top - 436, 272, 436)
    assert panel.top_on_a_screen(rack(600, 900), [laptop])
    assert not panel.top_on_a_screen(rack(600, 970), [laptop])               # under the menu bar
    assert panel.top_on_a_screen(rack(600, 1100), [laptop, above])           # on the upper display
    assert not panel.top_on_a_screen(rack(600, 970), [laptop, above])        # still the menu bar strip
    assert not panel.top_on_a_screen(rack(2400, 1100), [laptop, above])      # past the upper display's right edge

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

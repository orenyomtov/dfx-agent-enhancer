#!/usr/bin/env python3
"""Draw the app icon (the rack's display with its bars over the lime power oval, on the
chassis blue) and write an .icns with iconutil.

    python tools/make_icon.py OUT.icns
"""
import os
import subprocess
import sys
import tempfile

from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSColorSpace, NSGradient, NSGraphicsContext,
                    NSPNGFileType, NSShadow, NSDeviceRGBColorSpace)
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize


def rgb(h, a=1.0):
    h = h.lstrip("#")
    return NSColor.colorWithSRGBRed_green_blue_alpha_(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)), a)


def grad(*stops):
    """stops: (hex, location) or (hex, location, alpha)."""
    cols = [rgb(s[0], s[2] if len(s) > 2 else 1.0) for s in stops]
    return NSGradient.alloc().initWithColors_atLocations_colorSpace_(cols, [s[1] for s in stops], NSColorSpace.sRGBColorSpace())


def rect(x, top, w, h):
    """A rect given by its top edge on a 1024 canvas that is drawn y-up."""
    return NSMakeRect(x, 1024 - top - h, w, h)


def oval(cx, cy, rx, ry):
    return NSBezierPath.bezierPathWithOvalInRect_(rect(cx - rx, cy - ry, 2 * rx, 2 * ry))


def draw():
    # body: the Big Sur icon grid (824 px square, 100 px margin) with a soft drop shadow
    body = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect(100, 100, 824, 824), 185, 185)
    NSGraphicsContext.saveGraphicsState()
    sh = NSShadow.alloc().init()
    sh.setShadowOffset_(NSMakeSize(0, -12))
    sh.setShadowBlurRadius_(24)
    sh.setShadowColor_(rgb("#000000", .35))
    sh.set()
    rgb("#0a1f40").set()
    body.fill()
    NSGraphicsContext.restoreGraphicsState()
    grad(("#5b9be0", 0), ("#2c66b0", .3), ("#163f7c", .62), ("#0a2148", 1)).drawInBezierPath_angle_(body, -90)
    # glossy rail along the top and a dark rim
    NSGraphicsContext.saveGraphicsState()
    body.addClip()
    grad(("#ffffff", 0, .34), ("#ffffff", 1, 0)).drawInBezierPath_angle_(oval(512, 150, 470, 190), -90)
    NSGraphicsContext.restoreGraphicsState()
    rgb("#04101f").set()
    body.setLineWidth_(10)
    body.stroke()
    inner = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect(112, 112, 800, 800), 175, 175)
    rgb("#8ec8e5", .45).set()
    inner.setLineWidth_(4)
    inner.stroke()

    # display: black glass with a bevel, olive grid and the spectrum bars
    bezel = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect(176, 196, 672, 330), 46, 46)
    grad(("#0b1a2e", 0), ("#24456e", 1)).drawInBezierPath_angle_(bezel, -90)
    glass = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect(196, 214, 632, 294), 32, 32)
    grad(("#141414", 0), ("#1e1e1e", 1)).drawInBezierPath_angle_(glass, -90)
    NSGraphicsContext.saveGraphicsState()
    glass.addClip()
    for i in range(1, 4):
        rgb("#95b316", .3).set()
        NSBezierPath.fillRect_(rect(196, 214 + i * 294 / 4 - 2, 632, 4))
    bars = (("#9fd31b", "#5f8f0c", .62), ("#3fbf4a", "#1f7a2a", .38), ("#3a7bea", "#1d3f9a", .78),
            ("#a84fd8", "#5a2390", .5), ("#ef3b86", "#8f1a4a", .9), ("#e23434", "#8a1414", .66),
            ("#f08a22", "#9a4a0a", .44))
    x0, pitch, w, base, full = 236, 82, 50, 486, 236
    for i, (top, bottom, h) in enumerate(bars):
        bar = NSBezierPath.bezierPathWithRect_(rect(x0 + i * pitch, base - full * h, w, full * h))
        grad((top, 0), (bottom, 1)).drawInBezierPath_angle_(bar, -90)
    grad(("#ffffff", 0, .16), ("#ffffff", 1, 0)).drawInBezierPath_angle_(oval(512, 214, 380, 110), -90)
    NSGraphicsContext.restoreGraphicsState()

    # the lime power oval in its blue and chrome rings
    cx, cy = 512, 718
    rgb("#05101c").set()
    oval(cx, cy, 272, 166).fill()
    grad(("#4f7fb8", 0), ("#2a4e85", .5), ("#0d2449", 1)).drawInBezierPath_angle_(oval(cx, cy, 262, 158), -90)
    rgb("#061633").set()
    oval(cx, cy, 236, 140).fill()
    grad(("#ffffff", 0), ("#f6f6f6", .44), ("#cfcfcf", .58), ("#a6a6a6", .7), ("#7a7a7a", 1)) \
        .drawInBezierPath_angle_(oval(cx, cy, 230, 134), -60)
    face = oval(cx, cy, 212, 118)
    rgb("#111c00").set()
    face.fill()
    NSGraphicsContext.saveGraphicsState()
    oval(cx, cy, 206, 112).addClip()
    grad(("#c3e687", 0), ("#b4d056", .5), ("#92b31a", 1)).drawInBezierPath_angle_(face, -90)
    # saturated lime body under a curved horizon, like the rack's oval
    grad(("#82ab00", 0), ("#9bc400", .3), ("#b0d816", 1)).drawInBezierPath_angle_(oval(cx, cy + 150, 290, 150), -90)
    grad(("#111c00", 0, 0), ("#111c00", .82, 0), ("#111c00", 1, .55)).drawInBezierPath_relativeCenterPosition_(
        face, NSMakePoint(0, 0))
    NSGraphicsContext.restoreGraphicsState()
    # power glyph
    pw = NSBezierPath.bezierPath()
    pw.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        NSMakePoint(cx, 1024 - cy - 6), 62, 125, 55, False)
    pw.setLineWidth_(24)
    pw.setLineCapStyle_(1)
    rgb("#222b02", .88).set()
    pw.stroke()
    stem = NSBezierPath.bezierPath()
    stem.moveToPoint_(NSMakePoint(cx, 1024 - cy + 74))
    stem.lineToPoint_(NSMakePoint(cx, 1024 - cy + 6))
    stem.setLineWidth_(24)
    stem.setLineCapStyle_(1)
    stem.stroke()


def png(size, path):
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0)
    rep.setSize_(NSMakeSize(1024, 1024))      # draw in 1024 units, rasterise at `size` pixels
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    ctx.setImageInterpolation_(3)
    draw()
    ctx.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(path, True)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "AppIcon.icns")
    with tempfile.TemporaryDirectory() as d:
        iconset = os.path.join(d, "AppIcon.iconset")
        os.mkdir(iconset)
        for pt in (16, 32, 128, 256, 512):
            png(pt, os.path.join(iconset, "icon_%dx%d.png" % (pt, pt)))
            png(pt * 2, os.path.join(iconset, "icon_%dx%d@2x.png" % (pt, pt)))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
        if os.environ.get("ICON_PNG"):              # a preview PNG, for looking at the art
            png(1024, os.environ["ICON_PNG"])
    print("wrote", out)


if __name__ == "__main__":
    main()

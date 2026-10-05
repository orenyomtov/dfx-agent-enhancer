#!/usr/bin/env python3
"""Draw the static chassis art of the classic-blue DFX rack as SVG.

Writes src/dfx_agent_enhancer/ui/assets/panel-shell.svg (272x436) and ui/assets/mini-shell.svg (146x92).
All numbers are native pixels of the original DFX 10/11 window, measured from
reference captures (see NOTES.md). Dynamic parts (display content, meters, keys,
labels, the lime oval face) are HTML on top of these images.

Run with any Python 3: python3 tools/make_shell.py
"""
from __future__ import annotations

import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "dfx_agent_enhancer", "ui", "assets")

# Window outline of the main window, one point per pixel row (left edge going down,
# right edge going up). Measured from the original's window region.
OUTLINE = [
    (107, 0), (98, 1), (88, 2), (78, 3), (73, 4), (67, 5), (61, 6), (55, 7), (51, 8), (47, 9), (43, 10),
    (39, 11), (35, 12), (31, 13), (28, 14), (25, 15), (21, 16), (19, 17), (16, 18), (14, 19), (12, 20),
    (10, 21), (8, 22), (7, 23), (5, 24), (4, 25), (3, 26), (2, 27), (2, 28), (1, 29), (1, 30), (0, 31),
    (0, 376), (1, 377), (1, 378), (2, 379), (2, 380), (3, 381), (4, 382), (5, 383), (6, 384), (7, 385),
    (8, 386), (9, 387), (9, 392), (10, 393), (10, 394), (11, 395), (11, 396), (12, 397), (13, 398),
    (14, 399), (15, 400), (17, 401), (19, 402), (21, 403), (23, 404), (25, 405), (27, 406), (29, 407),
    (32, 408), (35, 409), (38, 410), (41, 411), (43, 412), (47, 413), (51, 414), (55, 415), (58, 416),
    (62, 417), (66, 418), (69, 419), (75, 420), (80, 421), (86, 422), (91, 423), (93, 424), (94, 425),
    (96, 426), (98, 427), (100, 428), (102, 429), (104, 430), (107, 431), (110, 432), (112, 433),
    (116, 434), (119, 435), (119, 436), (153, 436), (153, 435), (157, 434), (160, 433), (163, 432),
    (166, 431), (169, 430), (171, 429), (173, 428), (175, 427), (177, 426), (178, 425), (180, 424),
    (181, 423), (187, 422), (192, 421), (198, 420), (203, 419), (207, 418), (211, 417), (215, 416),
    (218, 415), (222, 414), (226, 413), (229, 412), (232, 411), (235, 410), (237, 409), (240, 408),
    (243, 407), (245, 406), (247, 405), (249, 404), (251, 403), (253, 402), (255, 401), (256, 400),
    (258, 399), (259, 398), (260, 397), (261, 396), (262, 395), (262, 394), (263, 393), (263, 387),
    (264, 386), (265, 385), (266, 384), (267, 383), (268, 382), (269, 381), (270, 380), (271, 379),
    (271, 378), (272, 377), (272, 31), (271, 30), (271, 29), (270, 28), (270, 27), (269, 26), (268, 25),
    (267, 24), (265, 23), (264, 22), (262, 21), (260, 20), (258, 19), (255, 18), (253, 17), (250, 16),
    (247, 15), (244, 14), (241, 13), (237, 12), (233, 11), (229, 10), (225, 9), (221, 8), (217, 7),
    (212, 6), (206, 5), (200, 4), (194, 3), (185, 2), (175, 1), (165, 0),
]

# Lower edge of the silver plate (first non-silver row), left to right.
PLATE_BOTTOM = [
    (13, 314), (14, 319), (17, 324), (21, 327), (25, 328.5), (29, 330), (33, 331), (37, 332.5), (41, 334),
    (45, 335), (49, 336), (53, 337), (57, 338), (61, 338.8), (65, 339.4), (69, 340), (73, 340.7),
    (77, 341.2), (81, 341.8), (85, 342.3), (89, 342.8), (93, 342.8), (97, 342), (101, 340.4),
    (105, 339), (109, 337.6), (113, 336.4), (117, 335.6), (121, 334.8), (125, 334.2), (129, 334),
    (136, 334), (143, 334), (147, 334.2), (151, 334.8), (155, 335.6), (159, 336.4), (163, 337.6),
    (167, 339), (171, 340.4), (175, 342), (179, 342.8), (183, 342.8), (187, 342.3), (191, 341.8),
    (195, 341.2), (199, 340.7), (203, 340), (207, 339.4), (211, 338.8), (215, 338), (219, 337),
    (223, 336), (227, 335), (231, 334), (235, 332.5), (239, 331), (243, 330), (247, 328.5),
    (251, 327), (255, 324), (258, 319), (259, 314),
]

# Lower edge of the dark bottom band (first blue row) and top edge of the grille.
# Measured on the right half; the shape is symmetric about x=136.
_BB_R = [(258, 372), (257, 377), (254, 380), (248, 383), (242, 385), (236, 387), (230, 388.5),
         (224, 390), (218, 391.5), (212, 393), (206, 394), (200, 395.2), (194, 396.5), (186, 398.5)]
_GT_R = [(263, 384), (260, 386.5), (254, 389), (248, 391), (242, 393), (236, 395.5), (230, 397.5),
         (224, 399), (218, 400.5), (212, 402), (206, 403.2), (200, 404.6), (194, 406), (186, 408)]


def mirror(pts):
    return [(272 - x, y) for x, y in pts]


BAND_BOTTOM = mirror(_BB_R) + list(reversed(_BB_R))   # left to right (the oval hides the middle)
GRILLE_TOP = mirror(_GT_R) + list(reversed(_GT_R))

# Bars of the spectrum and other shared geometry live in the HTML/CSS.

# ------------------------------------------------------------------ path helpers


def _f(v: float) -> str:
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def smooth(pts, k=1):
    out = list(pts)
    if len(pts) < 5:
        return out
    for i in range(1, len(pts) - 1):
        lo, hi = max(0, i - k), min(len(pts), i + k + 1)
        xs = [p[0] for p in pts[lo:hi]]
        ys = [p[1] for p in pts[lo:hi]]
        out[i] = (sum(xs) / len(xs), sum(ys) / len(ys))
    return out


def curve(pts, move=True) -> str:
    """Catmull-Rom spline through pts as cubic Bezier segments."""
    d = []
    if move:
        d.append("M%s %s" % (_f(pts[0][0]), _f(pts[0][1])))
    else:
        d.append("L%s %s" % (_f(pts[0][0]), _f(pts[0][1])))
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append("C%s %s %s %s %s %s" % tuple(_f(v) for v in (*c1, *c2, *p2)))
    return "".join(d)


def shift(pts, dy):
    return [(x, y + dy) for x, y in pts]


def outline_path() -> str:
    P = OUTLINE
    segs = [
        [(136, 0), (107, 0)] + P[1:31] + [(0, 31)],
        [(0, 376)] + P[33:43] + [(9, 387)],
        [(9, 392)] + P[45:75] + [(91, 423)],
        [(91, 423)] + P[76:87] + [(119, 435.6)],
        [(153, 435.6)] + P[91:102] + [(181, 423)],
        [(181, 423)] + P[103:132] + [(263, 392)],
        [(263, 387)] + P[134:143] + [(272, 377)],
        [(272, 31)] + P[145:175] + [(165, 0), (136, 0)],
    ]
    d = ""
    for i, s in enumerate(segs):
        d += curve(smooth(s), move=(i == 0))
    return d + "Z"


SIL = outline_path()

# ------------------------------------------------------------------ main window


def plate_path() -> str:
    top = "M13 187C13 182 16 179 21 179L251 179C256 179 259 182 259 187L259 314"
    bottom = list(reversed(PLATE_BOTTOM))
    return top + curve(smooth(bottom), move=False)[len("L259 314"):] + "L13 187Z"


def band_path() -> str:
    top = smooth(shift(PLATE_BOTTOM, 7.5))
    top[0] = (13, top[0][1] + 4)
    top[-1] = (259, top[-1][1] + 4)
    bottom = list(reversed(BAND_BOTTOM))
    d = curve(top) + curve(smooth(bottom), move=False) + "Z"
    return d


def region_between(upper, lower) -> str:
    return curve(smooth(upper)) + curve(smooth(list(reversed(lower))), move=False) + "Z"


def grille_path() -> str:
    return curve(smooth([(-2, GRILLE_TOP[0][1] - 4)] + GRILLE_TOP + [(274, GRILLE_TOP[-1][1] - 4)])) + \
        "L277 470L-5 470Z"


def panel_svg() -> str:
    plate = plate_path()
    band = band_path()
    tube_bottom = region_between(BAND_BOTTOM, GRILLE_TOP)
    # the same tube carried on into the oval's ring, where it merges with it (drawn over the ring)
    bb_ext = mirror([(180, 400.2)]) + BAND_BOTTOM + [(180, 400.2)]
    gt_ext = mirror([(180, 410.4)]) + GRILLE_TOP + [(180, 410.4)]
    tube_join = region_between(bb_ext, gt_ext)
    grille = grille_path()
    band_top_line = curve(smooth(shift(PLATE_BOTTOM[2:-2], 8.2)))
    plate_lip = curve(smooth(shift(PLATE_BOTTOM[3:-3], -0.8)))
    plate_shade = curve(smooth(shift(PLATE_BOTTOM[1:-1], -5)))
    tube_hi = curve(smooth(shift(PLATE_BOTTOM[1:-1], 3.6)))
    bb_line = curve(smooth(shift(BAND_BOTTOM, 1.2)))
    gt_line = curve(smooth(shift(GRILLE_TOP, -1.3)))
    gt_lo = curve(smooth(shift(GRILLE_TOP, 0.6)))

    # bottom band panels: x ranges and seams
    seams = (98.5, 172.5, 216.5)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="272" height="436" viewBox="0 0 272 436">
<defs>
  <clipPath id="sil"><path d="{SIL}"/></clipPath>
  <clipPath id="plateclip"><path d="{plate}"/></clipPath>
  <clipPath id="bandclip"><path d="{band}"/></clipPath>
  <clipPath id="skirtclip"><rect x="-5" y="378" width="282" height="70"/></clipPath>
  <clipPath id="lipclip"><rect x="0" y="38" width="272" height="4"/></clipPath>
  <clipPath id="ovalring"><rect x="70" y="380" width="22" height="40"/><rect x="180" y="380" width="22" height="40"/></clipPath>
  <clipPath id="tubeclip"><path d="{tube_bottom}"/></clipPath>
  <clipPath id="ovaltop"><ellipse cx="136" cy="401.75" rx="52.4" ry="32.2"/></clipPath>
  <clipPath id="ovalnotube"><rect x="0" y="360" width="272" height="35.6"/><rect x="0" y="405.2" width="272" height="40"/><rect x="95" y="390" width="82" height="20"/></clipPath>
  <!-- rail profiles across the left (x0-12) and right (x259-271) rails at y200, one stop per pixel -->
  <linearGradient id="rails" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="272" y2="0">
    <stop offset="0.0018" stop-color="#080b10"/>
    <stop offset="0.0055" stop-color="#1b2a3c"/>
    <stop offset="0.0092" stop-color="#1a2b40"/>
    <stop offset="0.0129" stop-color="#122135"/>
    <stop offset="0.0165" stop-color="#14253d"/>
    <stop offset="0.0202" stop-color="#1b314f"/>
    <stop offset="0.0239" stop-color="#243c60"/>
    <stop offset="0.0276" stop-color="#29436b"/>
    <stop offset="0.0312" stop-color="#2c4b77"/>
    <stop offset="0.0349" stop-color="#3a5e98"/>
    <stop offset="0.0386" stop-color="#5089d1"/>
    <stop offset="0.0423" stop-color="#1e3755"/>
    <stop offset="0.0460" stop-color="#00001d"/>
    <stop offset="0.0600" stop-color="#223a5c"/>
    <stop offset="0.9400" stop-color="#223a5c"/>
    <stop offset="0.9540" stop-color="#00002e"/>
    <stop offset="0.9577" stop-color="#203c61"/>
    <stop offset="0.9614" stop-color="#55a5d5"/>
    <stop offset="0.9651" stop-color="#3f71bc"/>
    <stop offset="0.9688" stop-color="#355c94"/>
    <stop offset="0.9724" stop-color="#34568b"/>
    <stop offset="0.9761" stop-color="#2f507e"/>
    <stop offset="0.9798" stop-color="#29446d"/>
    <stop offset="0.9835" stop-color="#1f3454"/>
    <stop offset="0.9871" stop-color="#182b49"/>
    <stop offset="0.9908" stop-color="#19325c"/>
    <stop offset="0.9945" stop-color="#16305d"/>
    <stop offset="0.9982" stop-color="#060c19"/>
  </linearGradient>
  <radialGradient id="titleglow" gradientUnits="userSpaceOnUse" cx="138" cy="12" r="130" gradientTransform="translate(138 12) scale(1 .34) translate(-138 -12)">
    <stop offset="0" stop-color="#4a6da0"/>
    <stop offset=".22" stop-color="#46699c"/>
    <stop offset=".45" stop-color="#36598c"/>
    <stop offset=".7" stop-color="#2a4570"/>
    <stop offset="1" stop-color="#233a5c"/>
  </radialGradient>
  <linearGradient id="titlefade" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#fff"/><stop offset=".8" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="archfade" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="40">
    <stop offset="0" stop-color="#fff"/><stop offset=".45" stop-color="#fff" stop-opacity=".8"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <mask id="archmask" maskUnits="userSpaceOnUse" x="-10" y="-10" width="292" height="60">
    <rect x="-10" y="-10" width="292" height="60" fill="url(#archfade)"/>
  </mask>
  <mask id="titlemask" maskUnits="userSpaceOnUse" x="0" y="0" width="272" height="46">
    <rect x="0" y="0" width="272" height="46" fill="url(#titlefade)"/>
  </mask>
  <linearGradient id="archrim" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="44">
    <stop offset="0" stop-color="#6a9ce0"/>
    <stop offset=".25" stop-color="#5880b8"/>
    <stop offset=".6" stop-color="#40628f"/>
    <stop offset="1" stop-color="#1a2a3e"/>
  </linearGradient>
  <linearGradient id="lip" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#365f9b"/><stop offset=".12" stop-color="#4f86d0"/><stop offset=".2" stop-color="#7dbbff"/>
    <stop offset=".8" stop-color="#7dbbff"/><stop offset=".88" stop-color="#4f86d0"/><stop offset="1" stop-color="#365f9b"/>
  </linearGradient>
  <radialGradient id="glint" cx=".5" cy=".5" r=".5">
    <stop offset="0" stop-color="#8ccaff" stop-opacity="1"/>
    <stop offset=".45" stop-color="#4f8de0" stop-opacity=".65"/>
    <stop offset="1" stop-color="#3a6cb8" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="shaft" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#6aa0e8" stop-opacity="0"/>
    <stop offset=".5" stop-color="#6aa0e8" stop-opacity=".22"/>
    <stop offset="1" stop-color="#7ab8ff" stop-opacity=".55"/>
  </linearGradient>
  <linearGradient id="streak" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#cfe2ff" stop-opacity=".22"/>
    <stop offset="1" stop-color="#cfe2ff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="midtube" gradientUnits="userSpaceOnUse" x1="0" y1="168" x2="0" y2="180">
    <stop offset="0" stop-color="#0d243a"/>
    <stop offset=".1" stop-color="#0d243a"/>
    <stop offset=".18" stop-color="#3b648e"/>
    <stop offset=".27" stop-color="#5d90c3"/>
    <stop offset=".36" stop-color="#79b6ff"/>
    <stop offset=".45" stop-color="#5880ba"/>
    <stop offset=".55" stop-color="#5778ab"/>
    <stop offset=".64" stop-color="#7ba4e3"/>
    <stop offset=".73" stop-color="#9fb4d8"/>
    <stop offset=".82" stop-color="#363658"/>
    <stop offset=".91" stop-color="#00002b"/>
    <stop offset="1" stop-color="#00002b"/>
  </linearGradient>
  <linearGradient id="midtubeH" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/>
    <stop offset=".045" stop-color="#fff"/>
    <stop offset=".955" stop-color="#fff"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
  <mask id="midtubemask" maskUnits="userSpaceOnUse" x="0" y="160" width="272" height="30">
    <rect x="0" y="160" width="272" height="30" fill="url(#midtubeH)"/>
  </mask>
  <linearGradient id="plateH" gradientUnits="userSpaceOnUse" x1="13" y1="0" x2="259" y2="0">
    <stop offset="0" stop-color="#a2a2a2"/>
    <stop offset=".016" stop-color="#a5a5a5"/>
    <stop offset=".03" stop-color="#aeaeae"/>
    <stop offset=".13" stop-color="#b3b3b3"/>
    <stop offset=".3" stop-color="#c2c2c2"/>
    <stop offset=".5" stop-color="#cbcbcb"/>
    <stop offset=".7" stop-color="#c2c2c2"/>
    <stop offset=".87" stop-color="#b3b3b3"/>
    <stop offset=".97" stop-color="#aeaeae"/>
    <stop offset=".985" stop-color="#a5a5a5"/>
    <stop offset="1" stop-color="#a2a2a2"/>
  </linearGradient>
  <radialGradient id="platespot" cx=".5" cy="0" r=".5">
    <stop offset="0" stop-color="#fff" stop-opacity=".75"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </radialGradient>
  <filter id="soft" x="-10%" y="-50%" width="120%" height="200%"><feGaussianBlur stdDeviation="2.4"/></filter>
  <filter id="soft1" x="-10%" y="-50%" width="120%" height="200%"><feGaussianBlur stdDeviation=".8"/></filter>
  <linearGradient id="bandgloss" gradientUnits="userSpaceOnUse" x1="0" y1="334" x2="0" y2="400">
    <stop offset="0" stop-color="#363636"/>
    <stop offset=".12" stop-color="#2c2c2c"/>
    <stop offset=".34" stop-color="#1c1c1c"/>
    <stop offset=".36" stop-color="#030303"/>
    <stop offset=".6" stop-color="#090909"/>
    <stop offset=".85" stop-color="#121212"/>
    <stop offset="1" stop-color="#161616"/>
  </linearGradient>
  <linearGradient id="lowtube" gradientUnits="userSpaceOnUse" x1="0" y1="380" x2="0" y2="410">
    <stop offset="0" stop-color="#1c5174"/>
    <stop offset=".2" stop-color="#214479"/>
    <stop offset=".5" stop-color="#22406c"/>
    <stop offset=".8" stop-color="#2b4f8c"/>
    <stop offset="1" stop-color="#2d58a0"/>
  </linearGradient>
  <pattern id="mesh" patternUnits="userSpaceOnUse" width="3.2" height="3.2" patternTransform="rotate(18)">
    <rect width="3.2" height="3.2" fill="#1d1b1b"/>
    <circle cx=".8" cy=".8" r=".78" fill="#a89a9a"/>
    <circle cx="2.4" cy="2.4" r=".78" fill="#7d7272"/>
  </pattern>
  <linearGradient id="meshshade" gradientUnits="userSpaceOnUse" x1="0" y1="384" x2="0" y2="428">
    <stop offset="0" stop-color="#000" stop-opacity=".15"/>
    <stop offset=".3" stop-color="#000" stop-opacity="0"/>
    <stop offset=".6" stop-color="#000" stop-opacity=".25"/>
    <stop offset="1" stop-color="#000" stop-opacity=".6"/>
  </linearGradient>
  <!-- blue ring: dark at its inner edge, bright toward the outside (measured on all four sides) -->
  <radialGradient id="ovalblue" cx=".5" cy=".5" r=".5">
    <stop offset=".78" stop-color="#05163a"/>
    <stop offset=".84" stop-color="#0d2449"/>
    <stop offset=".885" stop-color="#1b3a66"/>
    <stop offset=".915" stop-color="#2a4e85"/>
    <stop offset=".945" stop-color="#3360a6"/>
    <stop offset=".965" stop-color="#3f74c4"/>
    <stop offset=".985" stop-color="#5a8fd6"/>
    <stop offset="1" stop-color="#4f7fb8"/>
  </radialGradient>
  <linearGradient id="ovalbluetop" gradientUnits="userSpaceOnUse" x1="0" y1="368" x2="0" y2="402">
    <stop offset="0" stop-color="#03102a" stop-opacity=".45"/>
    <stop offset=".55" stop-color="#03102a" stop-opacity=".2"/>
    <stop offset="1" stop-color="#03102a" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="ovallowsides" gradientUnits="userSpaceOnUse" x1="0" y1="402" x2="0" y2="436">
    <stop offset="0" stop-color="#020c22" stop-opacity="0"/>
    <stop offset=".2" stop-color="#020c22" stop-opacity=".55"/>
    <stop offset=".55" stop-color="#020c22" stop-opacity=".5"/>
    <stop offset=".78" stop-color="#020c22" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="tubetopline" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="272" y2="0">
    <stop offset="0" stop-color="#1c5174"/>
    <stop offset=".17" stop-color="#2a74b0"/>
    <stop offset=".24" stop-color="#1c5a80"/>
    <stop offset=".3" stop-color="#3887a8"/>
    <stop offset=".7" stop-color="#8ec8e5"/>
    <stop offset=".83" stop-color="#49aef0"/>
    <stop offset=".9" stop-color="#1c5a80"/>
    <stop offset="1" stop-color="#1c5174"/>
  </linearGradient>
  <linearGradient id="tubeglint" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="272" y2="0">
    <stop offset=".1" stop-color="#5aa2ff" stop-opacity="0"/>
    <stop offset=".17" stop-color="#5aa2ff" stop-opacity=".32"/>
    <stop offset=".24" stop-color="#5aa2ff" stop-opacity="0"/>
    <stop offset=".26" stop-color="#5aa2ff" stop-opacity="0"/>
    <stop offset=".3" stop-color="#7ab0e8" stop-opacity=".25"/>
    <stop offset=".7" stop-color="#7ab0e8" stop-opacity=".3"/>
    <stop offset=".76" stop-color="#7ab0f0" stop-opacity=".38"/>
    <stop offset=".83" stop-color="#5aa2ff" stop-opacity=".45"/>
    <stop offset=".9" stop-color="#5aa2ff" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="ovaltube" gradientUnits="userSpaceOnUse" x1="0" y1="395.6" x2="0" y2="405.2">
    <stop offset="0" stop-color="#3a7fd0"/>
    <stop offset=".12" stop-color="#2f6aa8"/>
    <stop offset=".25" stop-color="#2a4f82"/>
    <stop offset=".6" stop-color="#305285"/>
    <stop offset=".8" stop-color="#34588e"/>
    <stop offset=".93" stop-color="#2a4c80"/>
    <stop offset="1" stop-color="#1a3358"/>
  </linearGradient>
  <!-- chrome ring, lit from the top left: white over the top half, grey down the right and bottom -->
  <linearGradient id="ovalchrome" x1=".3" y1="0" x2=".7" y2="1">
    <stop offset="0" stop-color="#ffffff"/>
    <stop offset=".44" stop-color="#f6f6f6"/>
    <stop offset=".58" stop-color="#cfcfcf"/>
    <stop offset=".7" stop-color="#a6a6a6"/>
    <stop offset=".85" stop-color="#8c8c8c"/>
    <stop offset="1" stop-color="#7a7a7a"/>
  </linearGradient>
  <linearGradient id="dfxorange" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ff6f26"/>
    <stop offset=".45" stop-color="#f68a35"/>
    <stop offset="1" stop-color="#ffc85a"/>
  </linearGradient>
  <linearGradient id="dfxblue" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#3a6ff0"/>
    <stop offset=".55" stop-color="#2554cf"/>
    <stop offset="1" stop-color="#1b3f9e"/>
  </linearGradient>
</defs>

<!-- chassis -->
<path d="{SIL}" fill="url(#rails)"/>
<g clip-path="url(#sil)">
  <rect x="0" y="0" width="272" height="46" fill="url(#titleglow)" mask="url(#titlemask)"/>
  <g opacity=".55" filter="url(#soft1)">
    <path d="M128 -2 L141 -2 L96 44 L84 44Z" fill="url(#streak)"/>
    <path d="M146 -2 L152 -2 L124 44 L118 44Z" fill="url(#streak)"/>
    <path d="M158 -2 L166 -2 L152 44 L146 44Z" fill="url(#streak)" opacity=".7"/>
    <path d="M112 -2 L118 -2 L62 44 L55 44Z" fill="url(#streak)" opacity=".6"/>
  </g>
  <g mask="url(#archmask)">
    <path d="{SIL}" fill="none" stroke="#3e6298" stroke-width="8.6"/>
    <path d="{SIL}" fill="none" stroke="#4b73ae" stroke-width="6.6"/>
    <path d="{SIL}" fill="none" stroke="#6598dc" stroke-width="5"/>
    <path d="{SIL}" fill="none" stroke="#608ec8" stroke-width="3.6"/>
  </g>
  <path d="{SIL}" fill="none" stroke="#0c121b" stroke-width="2.4"/>
  <!-- glare shafts falling onto the display's top lip, brightest where they hit it (the right one most) -->
  <rect x="53" y="30" width="13" height="11" fill="url(#shaft)" filter="url(#soft1)"/>
  <rect x="205" y="30" width="15" height="11" fill="url(#shaft)" filter="url(#soft1)"/>

  <!-- tube between display and plate -->
  <rect x="0" y="168" width="272" height="12" fill="url(#midtube)" mask="url(#midtubemask)"/>

  <!-- display bezel (content area is HTML) -->
  <rect x="9" y="39.5" width="253" height="131" rx="10" fill="#335da0"/>
  <rect x="10" y="40" width="251" height="130" rx="9.5" fill="#4a80cc"/>
  <rect x="11" y="40" width="249" height="6" rx="3" fill="url(#lip)"/>
  <rect x="11" y="40" width="249" height="1" fill="#3d66a5" opacity=".9"/>
  <rect x="11" y="42" width="249" height="127" rx="8" fill="#000"/>
  <g clip-path="url(#lipclip)">
    <ellipse cx="59.5" cy="41" rx="4.5" ry="1.4" fill="#8fd2ff" opacity=".75" filter="url(#soft1)"/>
    <ellipse cx="213" cy="41" rx="5" ry="1.6" fill="#d5ffff" filter="url(#soft1)"/>
    <ellipse cx="213" cy="40.6" rx="2.2" ry=".9" fill="#ffffff" opacity=".9"/>
  </g>

  <!-- silver plate with its rim -->
  <path d="{plate}" fill="none" stroke="#2c4b77" stroke-width="9"/>
  <path d="{plate}" fill="none" stroke="#3a5e98" stroke-width="7"/>
  <path d="{plate}" fill="none" stroke="#5089d1" stroke-width="5.4"/>
  <path d="{plate}" fill="none" stroke="#0a1426" stroke-width="3.6"/>

  <!-- tube between plate and band -->
  <path d="{tube_hi}" fill="none" stroke="#2f6a8a" stroke-width="5" opacity=".9"/>
  <path d="{tube_hi}" fill="none" stroke="#4ca6ff" stroke-width="2.4"/>
  <path d="{tube_hi}" fill="none" stroke="#8fd2ff" stroke-width=".8" opacity=".8"/>

  <path d="{plate}" fill="url(#plateH)"/>
  <g clip-path="url(#plateclip)">
    <ellipse cx="68" cy="179" rx="15" ry="9" fill="url(#platespot)"/>
    <ellipse cx="206" cy="179" rx="15" ry="9" fill="url(#platespot)"/>
    <rect x="13" y="179" width="246" height="1" fill="#ffffff"/>
    <rect x="13" y="180" width="246" height="1" fill="#f1f1f1" opacity=".7"/>
    <path d="{plate_shade}" fill="none" stroke="#000" stroke-opacity=".28" stroke-width="9" filter="url(#soft)"/>
    <path d="{plate_lip}" fill="none" stroke="#e8e8e8" stroke-width="1.2" opacity=".9"/>
  </g>

  <!-- lower tube, grille -->
  <path d="{tube_bottom}" fill="url(#lowtube)"/>
  <path d="{tube_bottom}" fill="url(#tubeglint)"/>
  <path d="{gt_line}" fill="none" stroke="#2f62b0" stroke-width="1.4"/>
  <path d="{grille}" fill="url(#mesh)"/>
  <path d="{grille}" fill="url(#meshshade)"/>
  <path d="{gt_lo}" fill="none" stroke="#000" stroke-opacity=".7" stroke-width="1"/>
  <g clip-path="url(#skirtclip)"><!-- the grille's light outer rim, only along the skirt -->
    <path d="{SIL}" fill="none" stroke="#6e6e6e" stroke-width="3.4" stroke-opacity=".75"/>
    <path d="{SIL}" fill="none" stroke="#000" stroke-width="1.4"/>
  </g>

  <!-- dark band with its blue rim -->
  <path d="{band}" fill="none" stroke="#2657a6" stroke-width="3.4"/>
  <path d="{band}" fill="#000"/>
  <g clip-path="url(#bandclip)">
    <rect x="13" y="320" width="246" height="90" fill="url(#bandgloss)" transform="rotate(1.8 136 360)"/>
    <path d="{band_top_line}" fill="none" stroke="#5a5a5a" stroke-width="1"/>
    {''.join(f'<rect x="{x - 1}" y="320" width="1.6" height="90" fill="#000"/><rect x="{x + .6}" y="320" width=".8" height="90" fill="#2e2e2e" opacity=".8"/>' for x in seams)}
  </g>
  <path d="{bb_line}" fill="none" stroke="url(#tubetopline)" stroke-width="1.2"/>

  <!-- power oval rings (the lime face is HTML). Centre x136: ring x82-190, chrome x88-184, face x92-180 -->
  <ellipse cx="136" cy="401.75" rx="54.6" ry="34.25" fill="#05101c" clip-path="url(#ovalnotube)"/>
  <ellipse cx="136" cy="401.75" rx="53.6" ry="33.4" fill="url(#ovalblue)"/>
  <ellipse cx="136" cy="401.75" rx="53.6" ry="33.4" fill="url(#ovalbluetop)" clip-path="url(#ovaltop)"/>
  <ellipse cx="136" cy="401.75" rx="53.6" ry="33.4" fill="url(#ovallowsides)"/>
  <!-- the lower tube runs into the ring on both sides (no outline there) -->
  <g clip-path="url(#ovalring)">
    <path d="{tube_join}" fill="url(#lowtube)"/>
    <path d="{tube_join}" fill="url(#tubeglint)"/>
  </g>
  <ellipse cx="136" cy="401.5" rx="48.7" ry="27.3" fill="#061633"/>
  <ellipse cx="136" cy="401.5" rx="48" ry="26.6" fill="url(#ovalchrome)"/>
  <ellipse cx="136" cy="401.5" rx="44.5" ry="23" fill="#111c00" stroke="#6e6e6e" stroke-width="1"/>

  <!-- DFX logo: a thick blue crescent over the top and down the right, behind heavy orange letters -->
  <path d="M29.6 357.6 C35.5 352.3, 43.5 350.6, 52 350.8 C62.5 351.1, 71.6 355.2, 74.2 362.2 C76.4 368.6, 71.4 377.6, 59.2 385.6
           C65.4 378.4, 69.6 371.6, 69.4 365.8 C69.2 359.8, 63.6 356.7, 54.6 356.2 C45.6 355.7, 37 356.2, 29.6 357.6Z" fill="url(#dfxblue)"/>
  <path d="M30.6 356.9 C36.4 352.4, 44 351.1, 52 351.3 C62 351.6, 70.8 355.6, 73.4 361.8" fill="none" stroke="#7aa6ff" stroke-width=".8" opacity=".8"/>
  <circle cx="76.2" cy="352.4" r="1.8" fill="#121212" stroke="#3c3c3c" stroke-width=".5"/>
  <text x="30.4" y="376" font-family="Impact, 'Arial Black', sans-serif" font-size="18" textLength="38.6" lengthAdjust="spacingAndGlyphs"
        transform="translate(0 368) skewX(-8) translate(0 -368)" fill="url(#dfxorange)" stroke="#2a1200" stroke-width="1.1" paint-order="stroke">DFX</text>
</g>
</svg>
"""


# ------------------------------------------------------------------ mini deck (146 x 92)
# Measured on the official DFX 10 mini-mode capture (127x82 with a 3px shadow margin): native = (file - 3) * 1.2066.
# That puts the deck at 146 x 92, the size it has next to the main window in the DFX 11 manual image.

MINI_W, MINI_H = 146, 92
MINI_OVAL = (73, 74.2)       # centre of the lime face; the blue ring is centred 0.3px lower


def mini_outline() -> str:
    # left half, top-left corner to the bottom centre, then mirrored
    top = [(73, 0), (4.6, 0), (2.2, 0.8), (1.0, 2.0), (0.3, 3.5), (0, 5)]
    side = [(0, 5), (0, 57.6)]
    skirt = [(0, 57.6), (0.6, 59.5), (1.6, 61.2), (2.9, 62.8), (3.6, 64.5), (3.9, 67.0), (4.6, 69.0), (5.8, 70.6),
             (7.2, 71.8), (8.6, 72.9), (10.6, 74.1), (13.2, 75.4), (15.9, 76.6), (19.2, 77.8), (23.0, 79.0),
             (27.4, 80.2), (31.8, 81.4), (37.6, 82.6), (43.6, 83.6)]
    ring = [(43.6, 83.6), (47.4, 84.8), (50.6, 86.1), (53.4, 87.4), (56.6, 88.7), (60.2, 90.0), (64.2, 91.1),
            (68.6, 91.7), (73, 91.9)]
    m = lambda pts: [(146 - x, y) for x, y in reversed(pts)]
    return (curve(top) + curve(side, move=False) + curve(skirt, move=False) + curve(ring, move=False) +
            curve(m(ring), move=False) + curve(m(skirt), move=False) + curve(m(side), move=False) +
            curve(m(top), move=False) + "Z")


MINI_SIL = mini_outline()

# bottom edge of the black key band: high at the sides, dipping toward the oval (hidden under its ring)
_MBAND_L = [(5.6, 60.2), (6.4, 61.0), (9.7, 62.6), (14, 64.4), (20.5, 66.2), (29, 68.4), (38.6, 70.0), (46, 70.9), (56, 71.3)]
MBAND_BOTTOM = _MBAND_L + [(146 - x, y) for x, y in reversed(_MBAND_L)]
MKEYS_TOP = 42.2


def mini_band_path() -> str:
    return ("M5.6 %s L140.4 %s " % (MKEYS_TOP, MKEYS_TOP)) + curve(smooth(list(reversed(MBAND_BOTTOM))), move=False)[0:] + "Z"


def mini_svg() -> str:
    band = mini_band_path()
    tube_lo = shift(MBAND_BOTTOM, 3.8)
    tube = region_between(shift(MBAND_BOTTOM, -0.5), tube_lo)
    grille_top = curve(smooth(shift(MBAND_BOTTOM, 3.4)))
    tube_mid = curve(smooth(shift(MBAND_BOTTOM, 1.6)))
    tube_hi = curve(smooth(shift(MBAND_BOTTOM, 1.0)))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{MINI_W}" height="{MINI_H}" viewBox="0 0 {MINI_W} {MINI_H}">
<defs>
  <clipPath id="msil"><path d="{MINI_SIL}"/></clipPath>
  <linearGradient id="mrails" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="146" y2="0">
    <stop offset=".004" stop-color="#030305"/>
    <stop offset=".012" stop-color="#1c304e"/>
    <stop offset=".02" stop-color="#1a3255"/>
    <stop offset=".03" stop-color="#2a4a7a"/>
    <stop offset=".045" stop-color="#2e4c7c"/>
    <stop offset=".07" stop-color="#325282"/>
    <stop offset=".93" stop-color="#355a90"/>
    <stop offset=".955" stop-color="#3a5d97"/>
    <stop offset=".97" stop-color="#406397"/>
    <stop offset=".98" stop-color="#30486b"/>
    <stop offset=".99" stop-color="#2b4b82"/>
    <stop offset="1" stop-color="#030305"/>
  </linearGradient>
  <linearGradient id="mlip" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#3f6dad"/><stop offset=".08" stop-color="#5696f3"/>
    <stop offset=".22" stop-color="#7bd4ff"/><stop offset=".26" stop-color="#a3ffff"/><stop offset=".3" stop-color="#69b7ff"/>
    <stop offset=".45" stop-color="#5596f1"/><stop offset=".6" stop-color="#5a9eff"/>
    <stop offset=".7" stop-color="#75ceff"/><stop offset=".74" stop-color="#a3ffff"/><stop offset=".78" stop-color="#7ad4ff"/>
    <stop offset=".92" stop-color="#599cfb"/><stop offset="1" stop-color="#3f6dad"/>
  </linearGradient>
  <linearGradient id="mliplo" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#3e75c5"/><stop offset=".1" stop-color="#4a84df"/>
    <stop offset=".22" stop-color="#75ceee"/><stop offset=".26" stop-color="#b6e7ec"/><stop offset=".3" stop-color="#60a8f1"/>
    <stop offset=".45" stop-color="#4187da"/><stop offset=".6" stop-color="#5193ea"/>
    <stop offset=".7" stop-color="#76c9e9"/><stop offset=".74" stop-color="#aeece6"/><stop offset=".78" stop-color="#71c0e9"/>
    <stop offset=".92" stop-color="#4b8ae4"/><stop offset="1" stop-color="#3b619c"/>
  </linearGradient>
  <linearGradient id="mrimtop" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#4975af"/><stop offset=".3" stop-color="#5e96e0"/><stop offset=".38" stop-color="#4a77b3"/>
    <stop offset=".62" stop-color="#4c7bb7"/><stop offset=".68" stop-color="#649ce7"/><stop offset=".76" stop-color="#4b78b4"/><stop offset="1" stop-color="#4975af"/>
  </linearGradient>
  <pattern id="mmesh" patternUnits="userSpaceOnUse" width="3" height="3" patternTransform="rotate(18)">
    <rect width="3" height="3" fill="#1d1b1b"/>
    <circle cx=".75" cy=".75" r=".72" fill="#a89a9a"/>
    <circle cx="2.25" cy="2.25" r=".72" fill="#7d7272"/>
  </pattern>
  <linearGradient id="mmeshshade" gradientUnits="userSpaceOnUse" x1="0" y1="60" x2="0" y2="92">
    <stop offset="0" stop-color="#000" stop-opacity=".1"/><stop offset=".45" stop-color="#000" stop-opacity=".25"/><stop offset="1" stop-color="#000" stop-opacity=".75"/>
  </linearGradient>
  <linearGradient id="mtube" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="146" y2="0">
    <stop offset="0" stop-color="#1f4e98"/><stop offset=".2" stop-color="#2a76e8"/><stop offset=".3" stop-color="#3d9cff"/>
    <stop offset=".5" stop-color="#2f6fd0"/><stop offset=".7" stop-color="#3d9cff"/><stop offset=".8" stop-color="#2a76e8"/><stop offset="1" stop-color="#1f4e98"/>
  </linearGradient>
</defs>
<path d="{MINI_SIL}" fill="url(#mrails)"/>
<g clip-path="url(#msil)">
  <!-- top rim: a bright line one pixel in, with two glints -->
  <path d="{MINI_SIL}" fill="none" stroke="url(#mrimtop)" stroke-width="4.6" stroke-opacity=".95" clip-path="url(#mtopclip)"/>
  <path d="{MINI_SIL}" fill="none" stroke="#030305" stroke-width="2.2"/>
  <rect x="0" y="2.6" width="146" height="2.4" fill="#27497d" opacity=".6"/>
  <!-- display: bright blue rim, black glass (the content is HTML) -->
  <rect x="21.7" y="4.8" width="102.8" height="37.4" rx="4" fill="#3a67a5"/>
  <rect x="22.4" y="6" width="101.4" height="34" rx="3.6" fill="#5490e5"/>
  <rect x="23.4" y="4.8" width="99.4" height="1.4" fill="url(#mlip)"/>
  <rect x="23.4" y="39.8" width="99.4" height="1.2" fill="#4472be"/>
  <rect x="22.4" y="41" width="101.6" height="1.2" fill="url(#mliplo)"/>
  <rect x="24.1" y="6" width="97.8" height="33.8" rx="3.2" fill="#000"/>
  <!-- key band, then the blue tube under it and the grille below -->
  <path d="{tube}" fill="#14305e"/>
  <path d="{tube_mid}" fill="none" stroke="url(#mtube)" stroke-width="2.4"/>
  <path d="{tube_hi}" fill="none" stroke="#7cc4ff" stroke-width=".7" stroke-opacity=".7"/>
  <path d="{grille_top}L150 100L-4 100Z" fill="url(#mmesh)"/>
  <path d="{grille_top}L150 100L-4 100Z" fill="url(#mmeshshade)"/>
  <path d="{band}" fill="#050505"/>
  <g clip-path="url(#mskirt)">
    <path d="{MINI_SIL}" fill="none" stroke="#6e6e6e" stroke-width="2.8" stroke-opacity=".7"/>
    <path d="{MINI_SIL}" fill="none" stroke="#000" stroke-width="1.2"/>
  </g>
</g>
<defs>
  <clipPath id="mtopclip"><rect x="-2" y="-2" width="150" height="5"/></clipPath>
  <clipPath id="mskirt"><rect x="-2" y="60" width="150" height="40"/></clipPath>
</defs>
</svg>
"""


def mini_oval_svg() -> str:
    """The deck's oval rings, drawn above the keys (the ring overlaps the bottoms of the middle keys)."""
    cx, cy = MINI_OVAL
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{MINI_W}" height="{MINI_H}" viewBox="0 0 {MINI_W} {MINI_H}">
<defs>
  <radialGradient id="mob" cx=".5" cy=".5" r=".5">
    <stop offset=".66" stop-color="#1c3c70"/>
    <stop offset=".76" stop-color="#2a4c7c"/>
    <stop offset=".86" stop-color="#305389"/>
    <stop offset=".93" stop-color="#3a62a4"/>
    <stop offset=".975" stop-color="#4682d6"/>
    <stop offset="1" stop-color="#2c4c86"/>
  </radialGradient>
  <clipPath id="mnotube"><rect x="0" y="0" width="146" height="70"/><rect x="0" y="79" width="146" height="20"/><rect x="45" y="60" width="56" height="30"/></clipPath>
  <linearGradient id="moc" x1=".3" y1="0" x2=".7" y2="1">
    <stop offset="0" stop-color="#fff"/><stop offset=".42" stop-color="#f2f2f2"/><stop offset=".6" stop-color="#c8c8c8"/>
    <stop offset=".8" stop-color="#959595"/><stop offset="1" stop-color="#7a7a7a"/>
  </linearGradient>
</defs>
  <ellipse cx="{cx}" cy="{cy + .3}" rx="34.9" ry="17.4" fill="#030a16" clip-path="url(#mnotube)"/>
  <ellipse cx="{cx}" cy="{cy + .3}" rx="34" ry="16.4" fill="url(#mob)"/>
  <ellipse cx="{cx}" cy="{cy}" rx="24.1" ry="13.2" fill="#061633"/>
  <ellipse cx="{cx}" cy="{cy}" rx="23.5" ry="12.7" fill="url(#moc)"/>
  <ellipse cx="{cx}" cy="{cy}" rx="21.4" ry="11.8" fill="#111c00" stroke="#6e6e6e" stroke-width=".6"/>
</svg>
"""


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "panel-shell.svg"), "w") as f:
        f.write(panel_svg())
    with open(os.path.join(OUT, "mini-shell.svg"), "w") as f:
        f.write(mini_svg())
    with open(os.path.join(OUT, "mini-oval.svg"), "w") as f:
        f.write(mini_oval_svg())
    # the outlines are also needed by CSS clip-path
    with open(os.path.join(OUT, "outlines.css"), "w") as f:
        f.write("/* generated by tools/make_shell.py */\n")
        f.write("#panel { clip-path: path('%s'); }\n" % SIL)
        f.write("#mini { clip-path: path('%s'); }\n" % MINI_SIL)
        f.write(".mkeys { clip-path: path('%s'); }\n" % mini_band_path())
    print("wrote", OUT)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render the app icon: a seal's head, drawn with the same code as the app.

Writes icons/seal-pomodoro.svg plus PNGs at the usual hicolor sizes.
"""

import math
import os

import cairo

from seal_pomodoro import (
    COAT, COAT_HI, COAT_LO, COAT_TOP, INK, MOTTLE, draw_face, ellipse,
    rgba, smooth_closed,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "icons")
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)

# Local units: a 200x200 box centred on (0, 0). The head sits slightly high
# with a hint of shoulders, so the silhouette reads as a seal, not a blob.
HEAD_OUTLINE = [
    (0, -86), (46, -76), (74, -44), (82, -4), (74, 36), (52, 62),
    (20, 76), (-20, 76), (-52, 62), (-74, 36), (-82, -4), (-74, -44), (-46, -76),
]
SPECKLES = [(-34, -46, 18, 8), (16, -56, 20, 8), (48, -22, 14, 7),
            (-52, -10, 13, 6), (34, 22, 15, 6)]


def draw_icon(cr, px):
    """Draw the icon into a px-by-px surface."""
    scale = px / 200.0
    cr.save()
    cr.translate(px / 2.0, px / 2.0)
    cr.scale(scale, scale)

    # soft contact shadow so the icon has some weight on light panels
    ellipse(cr, 0, 74, 62, 12)
    cr.set_source_rgba(0.16, 0.13, 0.09, 0.18)
    cr.fill()

    smooth_closed(cr, HEAD_OUTLINE)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    for width, alpha in ((10, 0.07), (5, 0.11)):
        cr.set_line_width(width)
        cr.set_source_rgba(0.10, 0.08, 0.06, alpha)
        cr.stroke_preserve()

    lg = cairo.LinearGradient(0, -90, 0, 80)
    lg.add_color_stop_rgb(0.00, *COAT_TOP)
    lg.add_color_stop_rgb(0.28, *COAT_HI)
    lg.add_color_stop_rgb(0.68, *COAT)
    lg.add_color_stop_rgb(1.00, *COAT_LO)
    cr.set_source(lg)
    cr.fill_preserve()

    cr.save()
    cr.clip_preserve()
    for sx, sy, rx, ry in SPECKLES:
        ellipse(cr, sx, sy, rx, ry, -0.15)
        rgba(cr, MOTTLE, 0.16)
        cr.fill()
    cr.restore()

    cr.set_line_width(2.2)
    rgba(cr, INK, 0.42)
    cr.stroke()

    # The face is drawn at the app's own scale, so shrink it onto this head.
    cr.save()
    cr.translate(0, 6)
    cr.scale(1.55, 1.55)
    # Tiny renders lose the whiskers to antialiasing and just look muddy.
    draw_face(cr, 0, 0, eyes_open=False, whiskers=px >= 32)
    cr.restore()

    cr.restore()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    svg_path = os.path.join(OUT_DIR, "seal-pomodoro.svg")
    surface = cairo.SVGSurface(svg_path, 200, 200)
    draw_icon(cairo.Context(surface), 200)
    surface.finish()
    print("wrote", svg_path)

    for px in SIZES:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
        draw_icon(cairo.Context(surface), px)
        path = os.path.join(OUT_DIR, "seal-pomodoro-%d.png" % px)
        surface.write_to_png(path)
        print("wrote", path)


if __name__ == "__main__":
    main()

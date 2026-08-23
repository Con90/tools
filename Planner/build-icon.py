#!/usr/bin/env python3
"""Generates the Planner app icon (build/icon.png + smaller sizes).

Draws a calendar glyph in the app's accent colours, rendered 4x and
downsampled for anti-aliasing. Pure stdlib, so it runs anywhere.

    python3 build-icon.py
"""
import math
import os
import struct
import zlib

SIZE = 512          # final icon size
SS = 4              # supersampling factor
S = SIZE * SS

BLUE = (0x4F, 0x6D, 0xF5)
BLUE_DARK = (0x2F, 0x49, 0xC4)
WHITE = (0xFF, 0xFF, 0xFF)
AMBER = (0xE8, 0xA1, 0x3A)

buf = bytearray(S * S * 4)


def rrect(x0, y0, x1, y1, r, color, round_top=True, round_bottom=True):
    """Fill a rounded rectangle (coords in final-icon space)."""
    x0, y0, x1, y1, r = (v * SS for v in (x0, y0, x1, y1, r))
    cr, cg, cb = color
    px = bytes((cr, cg, cb, 255))
    for y in range(int(y0), int(y1)):
        dy_top = y - y0
        dy_bot = y1 - 1 - y
        inset = 0.0
        if round_top and dy_top < r:
            inset = max(inset, r - math.sqrt(max(r * r - (r - dy_top) ** 2, 0)))
        if round_bottom and dy_bot < r:
            inset = max(inset, r - math.sqrt(max(r * r - (r - dy_bot) ** 2, 0)))
        xs = int(round(x0 + inset))
        xe = int(round(x1 - inset))
        if xe <= xs:
            continue
        off = (y * S + xs) * 4
        buf[off:off + (xe - xs) * 4] = px * (xe - xs)


# Tile background
rrect(0, 0, 512, 512, 112, BLUE)
# Calendar card
rrect(96, 128, 416, 416, 32, WHITE)
# Header band (square bottom corners so it meets the card body)
rrect(96, 128, 416, 200, 32, BLUE_DARK, round_bottom=False)
# Binder rings, drawn last so they cross the header band
rrect(176, 88, 208, 152, 16, WHITE)
rrect(304, 88, 208 + 128, 152, 16, WHITE)
# Day dots: 3 columns x 2 rows, last one highlighted
for row, cy in enumerate((250, 336)):
    for col, cx in enumerate((160, 256, 352)):
        color = AMBER if (row == 1 and col == 2) else BLUE
        rrect(cx - 26, cy - 26, cx + 26, cy + 26, 12, color)


def downsample(src, size, factor):
    out = bytearray(size * size * 4)
    n = factor * factor
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            base = (y * factor) * size * factor + x * factor
            for j in range(factor):
                off = (base + j * size * factor) * 4
                for i in range(factor):
                    p = off + i * 4
                    r += src[p]; g += src[p + 1]; b += src[p + 2]; a += src[p + 3]
            o = (y * size + x) * 4
            out[o] = r // n; out[o + 1] = g // n; out[o + 2] = b // n; out[o + 3] = a // n
    return out


def write_png(path, size, rgba):
    raw = b''.join(b'\x00' + bytes(rgba[y * size * 4:(y + 1) * size * 4]) for y in range(size))

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 9))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)
    print(f'wrote {path} ({size}x{size})')


os.makedirs('build', exist_ok=True)
icon = downsample(buf, SIZE, SS)
write_png('build/icon.png', SIZE, icon)

# Smaller copies for the Linux hicolor icon theme (exact halvings of 512).
cur, cur_size = icon, SIZE
for target in (256, 128, 64, 32):
    while cur_size > target:
        cur = downsample(cur, cur_size // 2, 2)
        cur_size //= 2
    write_png(f'build/icon-{target}.png', cur_size, cur)

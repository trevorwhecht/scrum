#!/usr/bin/env python3
"""Draw the Trevskills Scrum app icon (a tiny kanban board) as a 1024px PNG, stdlib only.

  python3 app/icon.py out.png
"""
import math, struct, sys, zlib

SIZE = 1024
BG = (0x1d, 0x1c, 0x1a)
GREEN, BLUE, RED, GREY = (0x1e, 0x84, 0x49), (0x24, 0x57, 0xd6), (0xd3, 0x2f, 0x2f), (0x4a, 0x48, 0x43)
# Three stage columns of cards, echoing the dashboard: (column, top, height, colour).
CARDS = [(0, 280, 150, GREEN), (0, 466, 150, GREEN), (0, 652, 110, GREY),
         (1, 280, 150, BLUE), (1, 466, 190, GREEN),
         (2, 280, 230, RED), (2, 546, 150, GREY)]


def fill_round_rect(rows, x0, y0, x1, y1, r, rgb):
    pixel = bytes(rgb) + b"\xff"
    for y in range(y0, y1):
        dy = max(y0 + r - y - 0.5, y - (y1 - r) + 0.5, 0)
        inset = r - math.sqrt(max(r * r - dy * dy, 0)) if dy else 0
        a, b = int(x0 + inset), int(x1 - inset)
        rows[y][a * 4:b * 4] = pixel * (b - a)


def draw():
    rows = [bytearray(SIZE * 4) for _ in range(SIZE)]  # transparent
    fill_round_rect(rows, 100, 100, 924, 924, 185, BG)  # macOS icon grid: 824px body
    for col, top, height, rgb in CARDS:
        x = 190 + col * 227
        fill_round_rect(rows, x, top, x + 190, top + height, 28, rgb)
    return rows


def png(rows):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        f.write(png(draw()))

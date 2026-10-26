"""
The sea chart's frame: a painted square of dark wood under brass, with a map, a compass, a sail, a ship's model and an
anchor in its corners on dark blue (hud/source/chart_frame.png, cut out on a transparent background), which the game
draws round the sea chart. The chart shows through the diamond opening in its middle: the world turned like the
screen is a diamond too. The small dark square in its top right corner is the close button's slot.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python hud/build_chart_frame.py
or with any Python 3 that has numpy and Pillow:
    python hud/build_chart_frame.py

The picture keeps its size (the game shows it nearly as tall as the screen) and is written to
canvas/public/sprites/hud/chart_frame.webp. The script prints what the game needs to know of it, in its pixels: its
size, the opening's middle and half diagonals (the diamond the chart fills; its tips, under the brass spikes, are
found from its straight edges), and the close button's slot (the middle and half size of its dark inside). They go into
FRAME in canvas/src/client/hud/SeaChart.ts.
"""

import os
import sys

import numpy as np

try:
    import bpy
except ImportError:
    bpy = None

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()
if bpy:
    for _text in bpy.data.texts:
        if _text.filepath and os.path.basename(_text.filepath) == "build_chart_frame.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

SOURCE = os.path.join(SCRIPT_DIR, "source", "chart_frame.png")
OUT = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "hud", "chart_frame.webp"))
QUALITY = 90
SOLID = 0.5  # alpha from which a pixel is the frame's
# The opening's edges are fitted along these shares of each half of it, away from the spikes at its tips and sides
EDGE_ROWS = (0.15, 0.4)
SLOT_CORNER = 0.2  # the slot is in this share of the picture, from its top and from its right
SLOT_WINDOW = 24  # pixels: a square this big, nearly all flat dark blue, is inside the slot
SLOT_FILL = 0.9  # the share of such a square's pixels that must be
# How much a pixel of the slot's flat inside may differ from its four neighbours (summed over them and red, green, blue)
FLAT = 0.12


def opening(alpha):
    """The see-through pixels reached from the picture's middle: the opening, as its middle and half diagonals (pixels).
    A diamond's width shrinks evenly from its middle row to its tips: a line is fitted to the widths of the rows in each
    half, and the tips are where the lines come to nothing"""
    h, w = alpha.shape
    clear = alpha < SOLID
    seed = np.zeros_like(clear)
    seed[h // 2, w // 2] = True
    if not clear[h // 2, w // 2]:
        raise ValueError("the picture's middle is not see-through: where is the opening?")
    inside = cutout.grow(seed, clear)
    rows = np.flatnonzero(inside.any(axis=1))
    top, bottom = rows.min(), rows.max() + 1
    lefts = np.array([np.flatnonzero(inside[y]).min() if inside[y].any() else 0 for y in range(h)])
    rights = np.array([np.flatnonzero(inside[y]).max() + 1 if inside[y].any() else 0 for y in range(h)])
    half = (bottom - top) / 2
    tips = []
    for sign, start in ((1, top), (-1, bottom - 1)):
        ys = np.arange(int(half * EDGE_ROWS[0]), int(half * EDGE_ROWS[1]))
        ys = start + sign * ys
        width = rights[ys] - lefts[ys]
        slope, at = np.polyfit(ys, width, 1)
        tips.append(-at / slope)
    cy = (tips[0] + tips[1]) / 2
    ry = (tips[1] - tips[0]) / 2
    middle = slice(int(top + half * 0.5), int(bottom - half * 0.5))
    cx = float(np.median((lefts[middle] + rights[middle]) / 2))
    # The width at the middle row, from the upper half's line (the side spikes hide the real one)
    ys = top + np.arange(int(half * EDGE_ROWS[0]), int(half * EDGE_ROWS[1]))
    slope, at = np.polyfit(ys, rights[ys] - lefts[ys], 1)
    rx = (slope * cy + at) / 2
    return cx, cy, rx, ry


def close_slot(picture):
    """The flat dark blue square in the top right corner: the middle and half size of its inside (pixels). Its middle is
    where such pixels are thickest, and it is grown from there through the dark blue up to the brass rim round it"""
    h, w, _ = picture.shape
    r, b, a = picture[..., 0], picture[..., 2], picture[..., 3]
    rgb = picture[..., :3].sum(axis=2)
    navy = (a > 0.8) & (b > r + 0.05) & (rgb > 0.15) & (rgb < 0.5)
    navy[int(h * SLOT_CORNER):] = False
    navy[:, :int(w * (1 - SLOT_CORNER))] = False
    flat = np.zeros((h, w), bool)
    flat[1:-1, 1:-1] = (np.abs(rgb[1:-1, 1:-1] - rgb[:-2, 1:-1]) + np.abs(rgb[1:-1, 1:-1] - rgb[2:, 1:-1]) +
                        np.abs(rgb[1:-1, 1:-1] - rgb[1:-1, :-2]) + np.abs(rgb[1:-1, 1:-1] - rgb[1:-1, 2:])) < FLAT
    # How many flat dark blue pixels each SLOT_WINDOW square holds, from a summed table
    table = np.pad((navy & flat).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    n = SLOT_WINDOW
    counts = table[n:, n:] - table[:-n, n:] - table[n:, :-n] + table[:-n, :-n]
    y, x = np.unravel_index(np.argmax(counts), counts.shape)
    if counts[y, x] < n * n * SLOT_FILL:
        raise ValueError("no close button's slot in the top right corner")
    seed = np.zeros_like(navy)
    seed[y + n // 2, x + n // 2] = True
    rows, cols = np.nonzero(cutout.grow(seed, navy))
    x0, x1, y0, y1 = cols.min(), cols.max() + 1, rows.min(), rows.max() + 1
    return (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0 + y1 - y0) / 4


def main():
    picture = cutout.load_rgba(SOURCE)
    cx, cy, rx, ry = opening(picture[..., 3])
    sx, sy, half = close_slot(picture)
    cutout.save_webp(OUT, picture, QUALITY)
    h, w, _ = picture.shape
    print(f"Wrote {OUT}")
    print(f"size {w} x {h}")
    print(f"opening x {cx:.1f}, y {cy:.1f}, rx {rx:.1f}, ry {ry:.1f}")
    print(f"close slot x {sx:.1f}, y {sy:.1f}, half {half:.1f}")


if __name__ == "__main__":
    main()

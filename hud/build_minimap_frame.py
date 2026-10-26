"""
The minimap's frame: a painted ring of dark wood under brass, rope and studs (hud/source/minimap_frame.png, cut out on a
transparent background), which the game draws round the minimap in the bottom right corner of the screen. The map
shows through the oval opening in its middle.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python hud/build_minimap_frame.py
or with any Python 3 that has numpy and Pillow:
    python hud/build_minimap_frame.py

The picture is shrunk by SCALE (the game shows it about 280 pixels wide, so a screen of twice the pixels still has its
own) and written to canvas/public/sprites/hud/minimap_frame.webp. The script prints what the game needs to know of it,
in the written picture's pixels: its size, the opening's middle and radii (the oval the map fills), how far the ring
reaches out round it (the part a click lands on), and the middles and radius of the four dark slots on top (the game's
buttons, build_minimap_buttons.py's, go in them). They go into FRAME in canvas/src/client/hud/Minimap.ts.
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_minimap_frame.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

SOURCE = os.path.join(SCRIPT_DIR, "source", "minimap_frame.png")
OUT = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "hud", "minimap_frame.webp"))
SCALE = 0.5
QUALITY = 90
SOLID = 0.5  # alpha from which a pixel is the frame's
RAYS = 720  # rays from the opening's middle the ring's outer edge is found along
SLOTS_ABOVE = 0.28  # the slots are in this share of the picture, from its top
SLOT_PIXELS = 20  # a column or row of the slots' dark blue this many pixels long is a slot's, not a stray one


def opening(alpha):
    """The see-through pixels reached from the picture's middle: the opening, as its middle and radii (pixels)"""
    h, w = alpha.shape
    clear = alpha < SOLID
    seed = np.zeros_like(clear)
    seed[h // 2, w // 2] = True
    if not clear[h // 2, w // 2]:
        raise ValueError("the picture's middle is not see-through: where is the opening?")
    rows, cols = np.nonzero(cutout.grow(seed, clear))
    x0, x1, y0, y1 = cols.min(), cols.max() + 1, rows.min(), rows.max() + 1
    return (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2


def ring_reach(alpha, cx, cy, rx, ry):
    """How far out the ring reaches, in the opening's radii: the median of its outer edge along rays from the middle,
    so that the spikes and the slots on top, which stand out of it here and there, are left out"""
    h, w = alpha.shape
    reach = []
    steps = np.linspace(1, 2, 400)
    for angle in np.linspace(0, 2 * np.pi, RAYS, endpoint=False):
        xs = np.clip((cx + np.cos(angle) * rx * steps).astype(int), 0, w - 1)
        ys = np.clip((cy + np.sin(angle) * ry * steps).astype(int), 0, h - 1)
        solid = np.nonzero(alpha[ys, xs] >= SOLID)[0]
        if len(solid):
            reach.append(steps[solid[-1]])
    return float(np.median(reach))


def slots(picture):
    """The dark blue discs on top of the frame, left to right: each one's middle and the radius of them all (pixels)"""
    r, g, b, a = (picture[..., k] for k in range(4))
    navy = (a > 0.8) & (b > r + 0.05) & (r + g + b < 0.8)
    navy[int(picture.shape[0] * SLOTS_ABOVE):] = False
    columns = navy.sum(axis=0) > SLOT_PIXELS
    # Runs of such columns, one a slot
    edges = np.flatnonzero(np.diff(np.concatenate([[0], columns.astype(np.int8), [0]])))
    found = []
    for x0, x1 in zip(edges[::2], edges[1::2]):
        rows = np.flatnonzero(navy[:, x0:x1].sum(axis=1) > SLOT_PIXELS)
        found.append(((x0 + x1) / 2, (rows.min() + rows.max() + 1) / 2, (x1 - x0 + rows.max() + 1 - rows.min()) / 4))
    return [(x, y) for x, y, _ in found], float(np.mean([radius for _, _, radius in found]))


def main():
    picture = cutout.load_rgba(SOURCE)
    cx, cy, rx, ry = opening(picture[..., 3])
    reach = ring_reach(picture[..., 3], cx, cy, rx, ry)
    middles, radius = slots(picture)
    small = cutout.resize(picture, SCALE)
    cutout.save_webp(OUT, small, QUALITY)
    h, w, _ = small.shape
    print(f"Wrote {OUT}")
    print(f"size {w} x {h}")
    print(f"opening x {cx * SCALE:.1f}, y {cy * SCALE:.1f}, rx {rx * SCALE:.1f}, ry {ry * SCALE:.1f}")
    print(f"ring reach {reach:.3f} (of the opening's radii)")
    print("slots", ", ".join(f"[{x * SCALE:.1f}, {y * SCALE:.1f}]" for x, y in middles), f"radius {radius * SCALE:.1f}")


if __name__ == "__main__":
    main()

"""
The skills' pictures on the skill bar: painted square buttons, each a picture on dark blue in a brass frame (hud/source/
skill_<id>.png, cut out on a transparent background): the repair (a wrench and a hammer), Full sail (a sail and an arrow
up) and a lock (a skill not open yet). The bar's wells have brass frames of their own, so only what is inside a
button's frame is taken: the box of its dark blue, its corners rounded as the frame's inside is, shrunk to a TILE-pixel
tile. The game stretches it over a well, about 26 pixels across.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python hud/build_skill_icons.py
or with any Python 3 that has numpy and Pillow:
    python hud/build_skill_icons.py

Output, in canvas/public/sprites/hud/:
  skill_icons.webp  the pictures in a row, TILE pixels each
  skill_icons.json  the tile's size and each picture's tile (its column and row), as the icons' atlases have them
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_skill_icons.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "hud"))
NAME = "skill_icons"
# The game's ids (SkillIconId in canvas/src/client/hud/iconAtlas.ts) and their pictures in hud/source/
SOURCES = {"repair": "skill_repair.png", "fullSail": "skill_full_sail.png", "locked": "skill_locked.png"}
TILE = 96  # pixels a side of a picture
QUALITY = 90
EDGE = 0.5  # the inside's edge rows and columns are at least this share as full of dark blue as the fullest one
ARC = 1 - 1 / np.sqrt(2)  # how far in along a corner's diagonal its rounding meets it, in the rounding's radius


def inside(navy):
    """The box of the frame's inside (left, top, right, bottom): its first and last rows and columns that are mostly
    dark blue (the picture in the middle leaves less of it showing, but never along the edges)"""
    rows = navy.sum(axis=1)
    cols = navy.sum(axis=0)
    rows = np.flatnonzero(rows >= EDGE * rows.max())
    cols = np.flatnonzero(cols >= EDGE * cols.max())
    return cols[0], rows[0], cols[-1] + 1, rows[-1] + 1


def rounding(navy):
    """The radius of the inside's corners (pixels): how far along each corner's diagonal the dark blue starts, the
    median of the four"""
    h, w = navy.shape
    reaches = []
    for flip_y in (False, True):
        for flip_x in (False, True):
            corner = navy[::-1 if flip_y else 1, ::-1 if flip_x else 1]
            steps = np.flatnonzero(corner[np.arange(min(h, w)), np.arange(min(h, w))])
            if len(steps):
                reaches.append(steps[0] / ARC)
    return float(np.median(reaches))


def rounded(picture, radius):
    """The picture with its corners cut round, `radius` pixels, their edges soft"""
    h, w, _ = picture.shape
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    dx = np.maximum(np.maximum(radius - xs, xs - (w - radius)), 0)
    dy = np.maximum(np.maximum(radius - ys, ys - (h - radius)), 0)
    alpha = np.clip(radius - np.hypot(dx, dy) + 0.5, 0, 1)
    out = picture.copy()
    out[..., 3] *= alpha
    return out


def square(picture):
    """The picture in the middle of a transparent square as wide as its longer side"""
    h, w, _ = picture.shape
    side = max(h, w)
    out = np.zeros((side, side, 4), np.float32)
    out[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = picture
    return out


def main():
    sheet = np.zeros((TILE, TILE * len(SOURCES), 4), np.float32)
    for i, (key, file) in enumerate(SOURCES.items()):
        picture = cutout.load_rgba(os.path.join(SCRIPT_DIR, "source", file))
        r, g, b, a = (picture[..., k] for k in range(4))
        navy = (a > 0.8) & (b > r + 0.03) & (r + g + b < 0.9)
        x0, y0, x1, y1 = inside(navy)
        radius = rounding(navy[y0:y1, x0:x1])
        cut = rounded(picture[y0:y1, x0:x1], radius)
        tile = cutout.resize(square(cut), TILE / max(cut.shape[:2]))
        sheet[:, i * TILE:(i + 1) * TILE] = tile[:TILE, :TILE]
        print(f"{key}: inside {x1 - x0} x {y1 - y0} at ({x0}, {y0}), corners {radius:.0f} px")
    cutout.save_webp(os.path.join(OUT_DIR, f"{NAME}.webp"), sheet, QUALITY)
    cutout.save_json(os.path.join(OUT_DIR, f"{NAME}.json"), {
        "file": f"{NAME}.webp",
        "tile": TILE,
        "icons": {key: [i, 0] for i, key in enumerate(SOURCES)},
    })
    print(f"Wrote {NAME}.webp and {NAME}.json in {OUT_DIR}")


if __name__ == "__main__":
    main()

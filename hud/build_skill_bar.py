"""
The skill bar's frame: a painted board of dark wood under brass, rope and rivets (hud/source/skill_bar.png, cut out on a
transparent background), which the game draws at the bottom of the screen. Its dark blue wells are where the game puts
its buttons: a row of ten quick slots on top, their keys 1…0 painted on them; under it on the left four squares, the
ship's skills; on the right two long plates, a weapon's each, with its two places for ammo hanging under it.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python hud/build_skill_bar.py
or with any Python 3 that has numpy and Pillow:
    python hud/build_skill_bar.py

The picture is cropped to the board, shrunk by SCALE (the game shows it about 450 pixels wide, so a screen of twice the
pixels still has its own) and written to canvas/public/sprites/hud/skill_bar.webp. The script prints what the game needs
to know of it, in the written picture's pixels: its size and each well's box (left, top, width, height), in groups.
They go into FRAME in canvas/src/client/hud/SkillBar.ts.
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_skill_bar.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

SOURCE = os.path.join(SCRIPT_DIR, "source", "skill_bar.png")
OUT = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "hud", "skill_bar.webp"))
SCALE = 0.4
QUALITY = 90
VISIBLE = 0.02  # alpha from which a pixel is the board's, for the crop
MARGIN = 2  # pixels of the picture kept round the board
WELL_PIXELS = 20  # a row or column with this many pixels of the wells' dark blue crosses a well, not a stray speck
BODY = 0.5  # a well's body: its rows and columns at least this full of its blue (a key's tab on top is left out)
GROUPS = {"quick": 10, "skills": 4, "plates": 2, "ammo": 4}


def board(alpha):
    """The box round what is there to see (left, top, right, bottom), MARGIN pixels out"""
    rows = np.flatnonzero((alpha > VISIBLE).any(axis=1))
    cols = np.flatnonzero((alpha > VISIBLE).any(axis=0))
    h, w = alpha.shape
    return (max(0, cols[0] - MARGIN), max(0, rows[0] - MARGIN),
            min(w, cols[-1] + 1 + MARGIN), min(h, rows[-1] + 1 + MARGIN))


def runs(profile, least):
    """Where the profile is over `least`, as (start, end) pairs"""
    on = (profile > least).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], on, [0]])))
    return list(zip(edges[::2], edges[1::2]))


def wells(navy, x0, y0, x1, y1):
    """The wells in a part of the picture, as boxes (left, top, right, bottom): it is cut along the rows, else the
    columns, that cross none, and each piece again, until a piece won't cut: that is a well"""
    part = navy[y0:y1, x0:x1]
    rows = runs(part.sum(axis=1), WELL_PIXELS)
    if len(rows) > 1:
        return [w for r0, r1 in rows for w in wells(navy, x0, y0 + r0, x1, y0 + r1)]
    cols = runs(part.sum(axis=0), WELL_PIXELS)
    if len(cols) > 1:
        return [w for c0, c1 in cols for w in wells(navy, x0 + c0, y0, x0 + c1, y1)]
    if not rows or not cols:
        return []
    (r0, r1), (c0, c1) = rows[0], cols[0]
    well = part[r0:r1, c0:c1]
    body_rows = np.flatnonzero(well.sum(axis=1) >= BODY * (c1 - c0))
    body_cols = np.flatnonzero(well.sum(axis=0) >= BODY * (r1 - r0))
    return [(x0 + c0 + body_cols[0], y0 + r0 + body_rows[0], x0 + c0 + body_cols[-1] + 1, y0 + r0 + body_rows[-1] + 1)]


def grouped(boxes):
    """The wells by what they are for: the quick slots (the top row) and the long plates left to right, the skills'
    squares row by row, and the ammo's places left to right (the first plate's two, then the second's)"""
    top = min(y0 for _, y0, _, _ in boxes)
    height = min(y1 - y0 for _, y0, _, y1 in boxes)
    quick = sorted((b for b in boxes if b[1] - top < height / 2), key=lambda b: b[0])
    rest = [b for b in boxes if b not in quick]
    plates = sorted((b for b in rest if b[2] - b[0] > 2 * (b[3] - b[1])), key=lambda b: b[0])
    if not plates:
        raise ValueError("no long plates found under the quick slots")
    rest = [b for b in rest if b not in plates]
    first = plates[0][0]
    skills = sorted((b for b in rest if b[2] <= first), key=lambda b: (round(b[1] / height), b[0]))
    ammo = sorted((b for b in rest if b[0] >= first), key=lambda b: b[0])
    found = {"quick": quick, "skills": skills, "plates": plates, "ammo": ammo}
    for name, count in GROUPS.items():
        if len(found[name]) != count:
            raise ValueError(f"{len(found[name])} wells for {name}, {count} wanted")
    return found


def main():
    picture = cutout.load_rgba(SOURCE)
    x0, y0, x1, y1 = board(picture[..., 3])
    picture = picture[y0:y1, x0:x1]
    r, g, b, a = (picture[..., k] for k in range(4))
    navy = (a > 0.8) & (b > r + 0.03) & (r + g + b < 0.8)
    h, w = navy.shape
    found = grouped(wells(navy, 0, 0, w, h))
    small = cutout.resize(picture, SCALE)
    cutout.save_webp(OUT, small, QUALITY)
    sh, sw, _ = small.shape
    print(f"Wrote {OUT}")
    print(f"size {sw} x {sh}")
    for name, boxes in found.items():
        cells = ", ".join(
            f"[{bx0 * SCALE:.1f}, {by0 * SCALE:.1f}, {(bx1 - bx0) * SCALE:.1f}, {(by1 - by0) * SCALE:.1f}]"
            for bx0, by0, bx1, by1 in boxes
        )
        print(f"{name}: [{cells}],")


if __name__ == "__main__":
    main()

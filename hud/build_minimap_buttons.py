"""
The buttons in the four slots on top of the minimap's frame: painted medallions in a row (hud/source/minimap_buttons.png,
cut out on a transparent background), left to right a crate of goods and gold (the hold), a cannon (the loadout), a ship
under three stars (the ship's talents) and a captain under three stars (the captain's mastery, the account's tree).

Run it with Blender's own Python, like the other scripts here:
    blender --background --python hud/build_minimap_buttons.py
or with any Python 3 that has numpy and Pillow:
    python hud/build_minimap_buttons.py

Each medallion is found by the picture's alpha (a run of columns with something solid in them), taken square round its
middle and shrunk to a TILE-pixel tile. The game shows them about 30 pixels across, a little bigger under the pointer.

Output, in canvas/public/sprites/hud/:
  minimap_buttons.webp  the medallions in a row, TILE pixels each, on a transparent background
  minimap_buttons.json  the tile's size and each button's tile (its column and row), as the icons' atlases have them
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_minimap_buttons.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

SOURCE = os.path.join(SCRIPT_DIR, "source", "minimap_buttons.png")
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "hud"))
NAME = "minimap_buttons"
# The game's ids (MinimapButtonId in canvas/src/client/hud/Minimap.ts), the medallions' order on the picture
BUTTONS = ["hold", "loadout", "talents", "mastery"]
TILE = 128  # pixels a side of a button
QUALITY = 90
SOLID = 0.5  # alpha from which a pixel is a medallion's


def medallions(alpha):
    """Each medallion's box (left, top, right, bottom), left to right"""
    solid = alpha >= SOLID
    columns = solid.any(axis=0)
    edges = np.flatnonzero(np.diff(np.concatenate([[0], columns.astype(np.int8), [0]])))
    boxes = []
    for x0, x1 in zip(edges[::2], edges[1::2]):
        rows = np.flatnonzero(solid[:, x0:x1].any(axis=1))
        boxes.append((x0, rows.min(), x1, rows.max() + 1))
    return boxes


def square(picture, box):
    """The medallion on a transparent square round its box's middle, as wide as its box's longer side"""
    x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0)
    out = np.zeros((side, side, 4), np.float32)
    left = (side - (x1 - x0)) // 2
    top = (side - (y1 - y0)) // 2
    out[top:top + y1 - y0, left:left + x1 - x0] = picture[y0:y1, x0:x1]
    return out


def main():
    picture = cutout.load_rgba(SOURCE)
    boxes = medallions(picture[..., 3])
    if len(boxes) != len(BUTTONS):
        raise ValueError(f"{len(boxes)} medallions on the picture, {len(BUTTONS)} buttons wanted")
    sheet = np.zeros((TILE, TILE * len(BUTTONS), 4), np.float32)
    for i, box in enumerate(boxes):
        piece = square(picture, box)
        sheet[:, i * TILE:(i + 1) * TILE] = cutout.resize(piece, TILE / piece.shape[0])[:TILE, :TILE]
    cutout.save_webp(os.path.join(OUT_DIR, f"{NAME}.webp"), sheet, QUALITY)
    cutout.save_json(os.path.join(OUT_DIR, f"{NAME}.json"), {
        "file": f"{NAME}.webp",
        "tile": TILE,
        "icons": {button: [i, 0] for i, button in enumerate(BUTTONS)},
    })
    print(f"Wrote {NAME}.webp and {NAME}.json to {OUT_DIR}")


if __name__ == "__main__":
    main()

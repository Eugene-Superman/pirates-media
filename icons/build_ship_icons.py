"""
The ships' icons, for the shipyard's cards and a ship's info window: painted ships (or a render of a ship's model)
cut out of their pictures (icons/source/ship_<id>.webp, one ship each, on a dark background) and packed into one
picture.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python icons/build_ship_icons.py
or with any Python 3 that has numpy and Pillow:
    python icons/build_ship_icons.py

Each ship (its id in canvas/src/game/ships/shipLines.ts) takes its own picture: SHEETS says where it stands on it
(pixels: left, top, right, bottom). The background its rigging encloses (between the masts, the sails and the ropes)
is cut out too. How a picture is cut out is cutout.py's. Each fills its tile across, in its middle.

Output, in canvas/public/sprites/icons/:
  ships.webp   the icons in a grid, TILE pixels each, on a transparent background
  ships.json   the tile's size and each ship's tile (its column and row)
"""

import os
import sys

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
        if _text.filepath and os.path.basename(_text.filepath) == "build_ship_icons.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
sys.path.insert(0, SCRIPT_DIR)
import cutout  # noqa: E402 (found through the path above)

ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "icons"))

# A picture a ship, and where the ship is on it
SHEETS = {
    "ship_sloop.webp": {"sloop": (187, 22, 1353, 934)},
    "ship_coastalBark.webp": {"coastalBark": (28, 13, 1435, 974)},
    "ship_corsair.webp": {"corsair": (310, 70, 1210, 870)},
}
TILE = 256  # pixels a side of an icon: the info window shows it 236 wide
PAD = 6  # pixels round a ship inside its tile
COLUMNS = 6
QUALITY = 90


def main():
    pictures = {key for places in SHEETS.values() for key in places}
    cutout.build_atlas(os.path.join(SCRIPT_DIR, "source"), SHEETS, OUT_DIR, "ships", TILE, PAD, COLUMNS, QUALITY,
                       pictures, stand=False)


if __name__ == "__main__":
    main()

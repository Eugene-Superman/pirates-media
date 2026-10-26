"""
The ammo's icons, for the arsenal's cards and an ammo's info window: painted cannonballs and harpoons cut out of sheets
of them (icons/source/cannonballs.webp, icons/source/harpoon_ammo.webp) and packed into one picture.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python icons/build_ammo_icons.py
or with any Python 3 that has numpy and Pillow:
    python icons/build_ammo_icons.py

Each of the game's ammo (its id in canvas/src/game/combat/arsenal.ts) takes one picture of a sheet. A cannonball is
given by its circle on the sheet (pixels: its middle's x and y, its radius), as its dark iron is close to the sheet's
colour; a harpoon by its box (pixels: left, top, right, bottom). How a picture is cut out is cutout.py's. The pictures
of a sheet keep their sizes on it, all scaled alike (its biggest fills its tile).

Output, in canvas/public/sprites/icons/:
  ammo.webp   the icons in a grid, TILE pixels each, on a transparent background
  ammo.json   the tile's size and each ammo's tile (its column and row)
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_ammo_icons.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
sys.path.insert(0, SCRIPT_DIR)
import cutout  # noqa: E402 (found through the path above)

ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "icons"))

# The sheets in source/, and where each ammo is on its sheet, weakest first. The sheets' skull-marked ones are left out
SHEETS = {
    # Rusty iron at tier 1, banded halves (the chain shot), smooth black iron, the navy's bronze with its anchor,
    # glowing lava (heated), black glass in a brass cage (explosive), a sapphire under the royal compass star
    "cannonballs.webp": {
        "ball1": (1065.2, 132.9, 110.7),
        "chainShot": (152.6, 362.3, 109.6),
        "ball2": (1379.7, 132.1, 110.1),
        "ball3": (754.7, 367.2, 113.3),
        "heatedShot": (1062.0, 602.7, 116.4),
        "explosiveShell": (754.6, 848.9, 125.1),
        "royalShot": (1069.3, 854.4, 126.0),
    },
    # Plain iron at tier 1, barbs all along, a leather grip, the navy's bronze, violet venom, lava, verdigris tentacles
    "harpoon_ammo.webp": {
        "harpoon1": (1247, 15, 1519, 237),
        "barbedHarpoon": (1244, 245, 1522, 466),
        "harpoon2": (324, 247, 611, 466),
        "harpoon3": (626, 248, 909, 469),
        "poisonHarpoon": (16, 722, 307, 971),
        "explosiveHarpoon": (932, 480, 1220, 713),
        "leviathanHarpoon": (317, 722, 612, 970),
    },
}
TILE = 192  # pixels a side of an icon
PAD = 8  # pixels round the biggest icon inside its tile
COLUMNS = 7
QUALITY = 90


def main():
    cutout.build_atlas(os.path.join(SCRIPT_DIR, "source"), SHEETS, OUT_DIR, "ammo", TILE, PAD, COLUMNS, QUALITY)


if __name__ == "__main__":
    main()

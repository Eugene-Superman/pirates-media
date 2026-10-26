"""
The guns' icons, for the arsenal's cards and a gun's info window: painted cannons and harpoon guns cut out of sheets
of them (icons/source/cannons.webp, icons/source/harpoons.webp) and packed into one picture.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python icons/build_gun_icons.py
or with any Python 3 that has numpy and Pillow:
    python icons/build_gun_icons.py

Each of the game's guns (its id in canvas/src/game/combat/arsenal.ts) takes one picture of a sheet: SHEETS says where it
stands on it (pixels: left, top, right, bottom). How a picture is cut out is cutout.py's. The guns of a sheet keep
their sizes on it, all scaled alike: a heavy gun is drawn bigger than a light one (each sheet is scaled so that its
biggest gun fills its tile).

Output, in canvas/public/sprites/icons/:
  guns.webp   the icons in a grid, TILE pixels each, on a transparent background
  guns.json   the tile's size and each gun's tile (its column and row)
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_gun_icons.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
sys.path.insert(0, SCRIPT_DIR)
import cutout  # noqa: E402 (found through the path above)

ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "icons"))

# The sheets in source/, and where each gun stands on its sheet (pixels: left, top, right, bottom), weakest first
SHEETS = {
    # Plain wood and iron at tier 1, green bronze, blue steel, purple and silver, red and gold, all gold at tier 6
    "cannons.webp": {
        "cannon1": (490, 851, 700, 990),
        "swivelGun": (252, 850, 490, 990),
        "cannon2": (490, 665, 700, 815),
        "carronade": (19, 452, 252, 630),
        "longNine": (26, 244, 251, 435),
        "cannon3": (912, 662, 1128, 820),
        "pounder24": (252, 461, 490, 630),
        "culverin": (1128, 49, 1323, 225),
        "pounder32": (256, 32, 490, 226),
        "pounder42": (261, 250, 487, 436),
    },
    # Plain wood at tier 1, a green frame and a heavy winch, blue frames, carved and barbed, a shark's head, a kraken
    "harpoons.webp": {
        "harpoonGun1": (14, 34, 274, 233),
        "deckCrossbow": (1206, 28, 1523, 238),
        "harpoonGun2": (885, 25, 1204, 237),
        "whalingGun": (20, 241, 324, 454),
        "harpoonGun3": (580, 239, 915, 459),
        "ballista": (1203, 240, 1527, 460),
        "barbedLauncher": (877, 472, 1216, 713),
        "twinLauncher": (586, 473, 905, 712),
        "leviathanLance": (16, 720, 319, 976),
        "krakenBane": (1189, 710, 1527, 997),
    },
}
TILE = 192  # pixels a side of an icon
PAD = 8  # pixels round the biggest icon inside its tile
COLUMNS = 5
QUALITY = 90


def main():
    cutout.build_atlas(os.path.join(SCRIPT_DIR, "source"), SHEETS, OUT_DIR, "guns", TILE, PAD, COLUMNS, QUALITY)


if __name__ == "__main__":
    main()

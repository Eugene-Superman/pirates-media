"""
The harbour view from painted art: the picture the game shows in a window while the player's ship is in port, and a
medallion for each of the port's buildings, which the game puts over the picture where the building stands. The
painting (port/source/harbour.webp) is taken as it is; the medallions are cut out of a sheet of them
(port/source/medallions.webp), each round its gold rim.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python port/build_harbour_art.py
or with any Python 3 that has numpy and Pillow:
    python port/build_harbour_art.py

It writes what build_harbour.py (the harbour rendered in Blender from the port's scene) does, so the last of the two
run is what the game shows.

What it makes, in canvas/public/sprites/port/:
  harbour.webp     the picture
  medallions.webp  the buildings' medallions in a row, each MEDALLION pixels square
  harbour.json     the picture's size; for each building where on the picture it stands (shares of the picture's width
                   and height, from the top left corner) and which medallion is its own
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_harbour_art.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

SOURCE_DIR = os.path.join(SCRIPT_DIR, "source")
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "port"))

# Each building's medallion on the sheet: its rim's circle (pixels: its middle's x and y, its radius), in the order
# they are put in the row
MEDALLIONS = {
    "guild": (194.6, 263.9, 188.7),  # a crowned shield over crossed sabres
    "auction": (576.0, 264.0, 189.0),  # a gavel and stacks of coins
    "workshop": (957.1, 264.1, 189.5),  # a hammer, a wrench and an anvil
    "market": (1338.3, 263.6, 188.0),  # a sack of gold, bolts of cloth and a crate
    "tavern": (315.5, 705.5, 208.1),  # two tankards of ale
    "shipyard": (765.4, 706.5, 208.3),  # a hull on the stocks
    "arsenal": (1215.4, 708.0, 210.2),  # a cannon and its balls
}
# Where each building stands on the painting (shares of its width and height, from the top left corner)
SPOTS = {
    "guild": (0.555, 0.215),  # the castle on the hill
    "auction": (0.265, 0.38),  # the tall house with a spire in the town on the left
    "workshop": (0.16, 0.485),  # the quay below the windmill
    "market": (0.475, 0.49),  # the stalls on the quay in the middle
    "tavern": (0.635, 0.47),  # the town on the right
    "shipyard": (0.945, 0.545),  # the wooden slip on the right
    "arsenal": (0.826, 0.875),  # the round tower at the end of the harbour wall
}
MEDALLION = 256  # pixels a side of a medallion
RIM = 246  # pixels across a medallion's rim, in it
PICTURE_QUALITY = 82
MEDALLION_QUALITY = 86


def medallion(sheet, circle):
    """A medallion: the sheet inside its rim's circle (what pokes out of the rim, a tankard's handle, is let go), its
    rim RIM pixels across in a MEDALLION square"""
    cx, cy, r = circle
    x0, y0, color = cutout.crop(sheet, (cx - r, cy - r, cx + r, cy + r), margin=2)
    # A pixel inside the rim's edge: its outermost one is half the sheet's dark background
    alpha = cutout.disc(x0, y0, color.shape[0], color.shape[1], (cx, cy, r - 1))
    small = cutout.resize(cutout.trim(color, alpha), RIM / (2 * r))
    h, w, _ = small.shape
    tile = np.zeros((MEDALLION, MEDALLION, 4), np.float32)
    y, x = (MEDALLION - h) // 2, (MEDALLION - w) // 2
    tile[y:y + h, x:x + w] = small
    return tile


def main():
    picture = cutout.load_rgb(os.path.join(SOURCE_DIR, "harbour.webp"))
    h, w, _ = picture.shape
    cutout.save_webp(os.path.join(OUT_DIR, "harbour.webp"), picture, PICTURE_QUALITY)
    sheet = cutout.load_rgb(os.path.join(SOURCE_DIR, "medallions.webp"))
    row = np.concatenate([medallion(sheet, circle) for circle in MEDALLIONS.values()], axis=1)
    cutout.save_webp(os.path.join(OUT_DIR, "medallions.webp"), row, MEDALLION_QUALITY)
    order = list(MEDALLIONS)
    cutout.save_json(os.path.join(OUT_DIR, "harbour.json"), dict(
        picture=dict(file="harbour.webp", w=w, h=h),
        medallions=dict(file="medallions.webp", size=MEDALLION),
        buildings={key: dict(at=list(SPOTS[key]), medallion=order.index(key)) for key in SPOTS},
    ))
    print(f"harbour: {w}x{h}, {len(order)} medallions", flush=True)


if __name__ == "__main__":
    main()

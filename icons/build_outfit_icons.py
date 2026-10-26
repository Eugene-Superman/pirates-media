"""
The outfit's icons, for the workshop's cards and a piece's info window: painted sails, hull planking and plating,
rudders and wheels, spyglasses and crow's nests cut out of sheets of them (icons/source/outfit_<slot>.webp) and packed
into one picture.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python icons/build_outfit_icons.py
or with any Python 3 that has numpy and Pillow:
    python icons/build_outfit_icons.py

Each piece of outfit (its id in canvas/src/game/ships/outfit.ts) takes one picture of its slot's sheet: SHEETS says
where it stands on it (pixels: left, top, right, bottom), with how to cut out a dark one (cutout.cut). How a picture is
cut out is cutout.py's. The pictures of a sheet keep their sizes on it, all scaled alike (its biggest fills its
tile).

Output, in canvas/public/sprites/icons/:
  outfit.webp   the icons in a grid, TILE pixels each, on a transparent background
  outfit.json   the tile's size and each piece's tile (its column and row)
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_outfit_icons.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
sys.path.insert(0, SCRIPT_DIR)
import cutout  # noqa: E402 (found through the path above)

ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "icons"))

# The sheets in source/, a slot's each, and where each piece is on its sheet, by tier. Left out: the sheets' black sail
# with a skull, a plain wheel (the tiller is the plain rudder) and a telescope on a dark tripod
SHEETS = {
    "outfit_sails.webp": {
        "canvasSails": (324, 53, 662, 409),  # plain canvas
        "patchedJib": (19, 47, 308, 412),  # a patched triangle
        "cottonSails": (673, 49, 1043, 409),  # tan cotton, leather at the corners
        "stormSails": (373, 436, 668, 852),  # a junk's battened sail
        "silkSails": (998, 442, 1375, 852),  # violet silk under a crescent moon
        "lateenRig": (1055, 13, 1408, 422),  # a red lateen
        "admiraltySails": (9, 441, 361, 838),  # navy blue, a compass rose
        "dragonSails": (671, 440, 1028, 852),  # green, a golden dragon
        "krakenSails": (1385, 436, 1763, 852),  # a golden kraken
    },
    "outfit_hull.webp": {
        "oakPlanking": (397, 44, 763, 358),
        "pinePlanking": (19, 52, 390, 356),
        "doublePlanking": (1581, 46, 1969, 359),  # planks in layers, iron strips
        "copperSheathing": (398, 407, 778, 733),
        # Black with tar, iron bands: as dark as the sheet, so taken by a closer likeness and its notches filled
        "tarredPlanking": dict(box=(1178, 35, 1575, 360), like_bg=0.04, close=5),
        "teakHull": (782, 43, 1163, 362),
        "ironPlates": dict(box=(20, 405, 406, 726), like_bg=0.04, close=3),
        "steelPlates": dict(box=(778, 400, 1163, 742), close=3),
        "brassPlating": (1178, 399, 1573, 745),
        "krakenPlating": (1578, 398, 1971, 750),
    },
    "outfit_rudder.webp": {
        "tiller": (1194, 17, 1527, 369),  # a plain rudder and its tiller
        "seaAnchor": (386, 407, 759, 768),  # a canvas drogue
        "shipsWheel": (383, 10, 739, 377),
        "dragAnchor": (789, 402, 1175, 768),  # a red drogue
        "ironRudder": (20, 402, 323, 771),
        "balancedRudder": (1555, 19, 1964, 377),
        "captainsWheel": (782, 11, 1137, 376),  # mahogany, a brass compass at its hub
        "krakenWheel": (1184, 379, 1563, 780),
        "leviathanRudder": (1596, 392, 1964, 774),
    },
    "outfit_lookout.webp": {
        "spyglass": (52, 85, 361, 318),  # wood
        "brassSpyglass": (408, 62, 792, 323),
        "crowsNest": (1646, 20, 1927, 367),
        "coveredNest": (35, 360, 335, 772),
        "officersGlass": (792, 56, 1183, 325),  # brass and red wood
        "telescope": (392, 391, 788, 748),  # navy blue on a brass tripod
        "admiralsGlass": (782, 414, 1172, 732),  # red, an anchor on it
        "starTelescope": (1196, 396, 1567, 746),
        "krakenEye": (1576, 395, 1966, 762),
    },
}
# The pieces the sheet's background shows through, enclosed: between a sail and its ropes, a drogue and its lines, a
# wheel's spokes, a crow's nest's rails, a tripod's legs. (Not the stacks of planks and plates: the dark between them
# is their own shadow)
POCKETS = {*SHEETS["outfit_sails.webp"], "seaAnchor", "dragAnchor", "shipsWheel", "captainsWheel", "krakenWheel",
           "crowsNest", "coveredNest", "telescope"}
TILE = 192  # pixels a side of an icon
PAD = 8  # pixels round the biggest icon inside its tile
COLUMNS = 10
QUALITY = 90


def main():
    cutout.build_atlas(os.path.join(SCRIPT_DIR, "source"), SHEETS, OUT_DIR, "outfit", TILE, PAD, COLUMNS, QUALITY,
                       POCKETS)


if __name__ == "__main__":
    main()

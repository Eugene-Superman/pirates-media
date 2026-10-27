"""
Each island's coast as a picture to paint the island over: a black line on white, seen as the game sees it (its
camera's pitch and yaw, at the scale the port's art has), so a painting made over it fits the island in the game.

Reads islands/islands.json (export_islands.mjs writes it from the game). Run it with any Python 3 that has Pillow:
    python islands/build_outlines.py [folder]
or with Blender's own Python, like the other scripts here:
    blender --background --python islands/build_outlines.py -- [folder]
The folder is islands/outlines/ unless one is given.

What it makes there:
  island_NN_<square>.png  an island's coast at the water's level: room round it for its shallows, and above it for its
                          cliffs, hill and palms, which rise up the picture
  map.png                 the whole sea from above, north at the top, with the squares A1…H8 and each island's number:
                          which island is which
  outlines.json           the scale and the camera, and where each island's centre is in its picture: where the painting
                          goes in the game
"""

import json
import math
import os
import sys

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()

# The game's camera (canvas/src/client/scene/SceneView.ts, CAMERA) and the scale the port's art has (port.json)
PITCH = 30.0  # degrees
YAW = 45.0
PX_PER_UNIT = 2.8  # pixels per world unit: the game's ×2 zoom
SHALLOWS = 1.4  # the island's room round its coast, as a share of its reach: the game's shallows reach 1.35
PALM = 26  # world units: the palms' height over the land (island3d.ts), the tallest thing on an island
MARGIN = 24  # pixels round everything
LINE = 4  # pixels: the coast's line
SUPERSAMPLE = 3  # drawn this many times bigger, then shrunk: a smooth line
SMOOTH = 8  # points a curve puts between two of the coast's: the game's 48 points as a round coast
MAP = {"size": 1200, "world": 8000, "squares": 8}  # the map's pixels, the world's units across, squares a side

SIN_P = math.sin(math.radians(PITCH))
COS_P = math.cos(math.radians(PITCH))
FWD = (math.sin(math.radians(YAW)), -math.cos(math.radians(YAW)))
RIGHT = (math.cos(math.radians(YAW)), math.sin(math.radians(YAW)))


def project(x, y, z=0.0):
    """A world point, from the island's centre, to pixels from where the centre is in the picture (Camera3D.project)"""
    u = x * RIGHT[0] + y * RIGHT[1]
    v = x * FWD[0] + y * FWD[1]
    return u * PX_PER_UNIT, -(v * SIN_P + z * COS_P) * PX_PER_UNIT


def smooth(points):
    """A closed curve through the points (centripetal Catmull-Rom): the game's coast without its corners"""
    out = []
    n = len(points)
    for i in range(n):
        p0, p1, p2, p3 = (points[(i + k) % n] for k in (-1, 0, 1, 2))

        def knot(t, a, b):
            return t + max(math.dist(a, b), 1e-6) ** 0.5

        t0 = 0.0
        t1 = knot(t0, p0, p1)
        t2 = knot(t1, p1, p2)
        t3 = knot(t2, p2, p3)
        for s in range(SMOOTH):
            t = t1 + (t2 - t1) * s / SMOOTH

            def lerp(a, b, ta, tb):
                return tuple(((tb - t) * a[k] + (t - ta) * b[k]) / (tb - ta) for k in range(2))

            a1, a2, a3 = lerp(p0, p1, t0, t1), lerp(p1, p2, t1, t2), lerp(p2, p3, t2, t3)
            b1, b2 = lerp(a1, a2, t0, t2), lerp(a2, a3, t1, t3)
            out.append(lerp(b1, b2, t1, t2))
    return out


def frame(island):
    """The island's picture without drawing it: its size, where its centre is in it, and its coast in it (pixels from
    the picture's top left)"""
    cx, cy = island["x"], island["y"]
    coast = smooth([(x - cx, y - cy) for x, y in island["coast"]])
    line = [project(x, y) for x, y in coast]
    room = [project(x * SHALLOWS, y * SHALLOWS) for x, y in coast]
    top = max(island["height"] + island["hillHeight"], island["height"]) + PALM
    # The highest point a hill or a palm can reach, over any point of the land: the picture's top
    rise = top * COS_P * PX_PER_UNIT
    left = min(x for x, _ in room) - MARGIN
    right = max(x for x, _ in room) + MARGIN
    bottom = max(y for _, y in room) + MARGIN
    upper = min(min(y for _, y in room), min(y for _, y in line) - rise) - MARGIN
    width, height = math.ceil(right - left), math.ceil(bottom - upper)
    origin = (-left, -upper)
    return (width, height), origin, [(x + origin[0], y + origin[1]) for x, y in line]


def outline(island):
    """The island's picture and where its centre is in it"""
    from PIL import Image, ImageDraw

    (width, height), origin, line = frame(island)
    big = Image.new("L", (width * SUPERSAMPLE, height * SUPERSAMPLE), 255)
    draw = ImageDraw.Draw(big)
    points = [(x * SUPERSAMPLE, y * SUPERSAMPLE) for x, y in line]
    draw.line(points + points[:1], fill=0, width=LINE * SUPERSAMPLE, joint="curve")
    picture = big.resize((width, height), Image.LANCZOS)
    return picture, (round(origin[0], 1), round(origin[1], 1))


def font(size):
    from PIL import ImageFont

    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def overview(islands, port):
    """The sea from above, north at the top: the squares, the port, and each island filled with its number"""
    from PIL import Image, ImageDraw

    k = MAP["size"] / MAP["world"]
    picture = Image.new("RGB", (MAP["size"], MAP["size"]), (233, 241, 247))
    draw = ImageDraw.Draw(picture)
    step = MAP["size"] / MAP["squares"]
    small, big = font(16), font(22)
    for i in range(MAP["squares"] + 1):
        draw.line([(i * step, 0), (i * step, MAP["size"])], fill=(180, 196, 210), width=1)
        draw.line([(0, i * step), (MAP["size"], i * step)], fill=(180, 196, 210), width=1)
    for col in range(MAP["squares"]):
        for row in range(MAP["squares"]):
            draw.text((col * step + 6, row * step + 4), f"{chr(65 + col)}{row + 1}", fill=(140, 160, 180), font=small)
    draw.polygon([(x * k, y * k) for x, y in port["coast"]], fill=(196, 160, 110), outline=(0, 0, 0))
    draw.text((port["x"] * k, port["y"] * k), "PORT", fill="white", font=small, anchor="mm", stroke_width=3,
              stroke_fill="black")
    for island in islands:
        coast = [(x * k, y * k) for x, y in smooth(island["coast"])]
        draw.polygon(coast, fill=(120, 120, 120), outline=(0, 0, 0))
        label = island["id"].split("_")[1]
        box = draw.textbbox((0, 0), label, font=big)
        x, y = island["x"] * k, island["y"] * k
        draw.text((x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - box[1]), label, fill="white", font=big,
                  stroke_width=3, stroke_fill="black")
    return picture


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out_dir = args[0] if args else os.path.join(SCRIPT_DIR, "outlines")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(SCRIPT_DIR, "islands.json")) as fh:
        data = json.load(fh)
    islands = data["islands"]
    pictures = []
    for island in islands:
        picture, centre = outline(island)
        name = f"{island['id']}_{island['square']}.png"
        picture.save(os.path.join(out_dir, name), optimize=True)
        pictures.append({
            "id": island["id"],
            "file": name,
            "square": island["square"],
            "w": picture.width,
            "h": picture.height,
            "centre": centre,
            "at": [island["x"], island["y"]],
        })
        print(f"{name}: {picture.width} × {picture.height}")
    overview(islands, data["port"]).save(os.path.join(out_dir, "map.png"), optimize=True)
    with open(os.path.join(out_dir, "outlines.json"), "w") as fh:
        json.dump({
            "note": "centre: where the island's centre (at, world units) is in its picture, pixels from its top left",
            "pxPerUnit": PX_PER_UNIT,
            "pitch": PITCH,
            "yaw": YAW,
            "islands": pictures,
        }, fh, indent=1)
        fh.write("\n")
    print(f"{out_dir}: {len(pictures)} islands, map.png, outlines.json")


# build_island_art.py takes the outlines' frames from here (frame), without drawing them or needing Pillow
if __name__ == "__main__":
    main()

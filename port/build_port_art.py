"""
The port in the game from painted art: a painting of the island, its town, castle and harbour
(port/source/island.webp), painted over the port as build_port.py renders it, cut the way the game needs the
port's pictures.

Run it with Blender's own Python, like the other scripts here:
    blender --background --python port/build_port_art.py
or with any Python 3 that has numpy and Pillow:
    python port/build_port_art.py

The game sorts the port with the ships, slice by slice (see build_port.py): a ship sails behind the hill, between the
harbour walls and in front of the town. A painting knows nothing of that, so the render it was painted over, kept in
port/source/render/ (what build_port.py wrote into the game), says it: each painted pixel goes where the render's
pixel at its place went, into the ground under the ships or into a slice; what the painting has and the render
hadn't (a painted boat in the bay, a flag) into the slice next to it, or the ground. The painting doesn't lie on the
render exactly: align_port_art.py fitted it, its coast and its walls onto the render's, and port/source/island_warp.json
is where each pixel of the render's frame takes the painting from.

It writes what build_port.py does, so the last of the two run is what the game shows. The lighthouse's lamp and the
flags the game animates over the render are left out: the painting has its own.

What it makes, in canvas/public/sprites/port/:
  ground.webp     what lies at the water's level, under the ships
  raised_<n>.webp the slices, packed into pages
  port.json       the scale, where the island's centre is, the slices: each one's place on its page, where it goes and
                  the point it is sorted by
"""

import json
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_port_art.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import cutout  # noqa: E402 (icons/cutout.py, found through the path above)

SOURCE_DIR = os.path.join(SCRIPT_DIR, "source")
RENDER_DIR = os.path.join(SOURCE_DIR, "render")
OUT_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas", "public", "sprites", "port"))

MARGIN = 48  # pixels round the render's pictures in the frame the painting is laid on: it may reach past them
REACH = 6  # pixels: a painted pixel the render has nothing at goes into the slice this near, else into the ground
SEAM = 2  # pixels of the nearer slices round a slice's edge it holds too, so no seam opens when mipmaps shrink them
FEATHER = 5  # pixels over which the painting's outer edge fades into the sea
PAGE = 2048  # pixels: the widest a page of slices is
PAGE_HEIGHT = 4096  # pixels: the tallest
GAP = 2  # pixels between two slices on a page
QUALITY = 86


# ---------------------------------------------------------------------------
# The render: its frame, and where each of its pixels went
# ---------------------------------------------------------------------------


def render_frame():
    """The render's pictures laid out round the island's centre: (its port.json, the frame's size, where the centre is
    in it, the labels: -1 nothing, 0 the ground, 1 + k the slice k; and the render itself, for align_port_art.py)"""
    with open(os.path.join(RENDER_DIR, "port.json")) as fh:
        art = json.load(fh)
    ground = art["ground"]
    boxes = [(-ground["x"], -ground["y"], -ground["x"] + ground["w"], -ground["y"] + ground["h"])]
    for piece in art["slices"]:
        _, _, w, h = piece["frame"]
        boxes.append((piece["x"], piece["y"], piece["x"] + w, piece["y"] + h))
    left = min(b[0] for b in boxes) - MARGIN
    top = min(b[1] for b in boxes) - MARGIN
    width = int(np.ceil(max(b[2] for b in boxes) - left + MARGIN))
    height = int(np.ceil(max(b[3] for b in boxes) - top + MARGIN))
    anchor = (-left, -top)
    labels = np.full((height, width), -1, np.int32)
    render = np.zeros((height, width, 4), np.float32)

    def lay(picture, x, y, label):
        h, w, _ = picture.shape
        x, y = int(round(x + anchor[0])), int(round(y + anchor[1]))
        a = picture[..., 3:]
        render[y:y + h, x:x + w] = picture * a + render[y:y + h, x:x + w] * (1 - a)
        labels[y:y + h, x:x + w][picture[..., 3] > 0.5] = label

    lay(cutout.load_rgba(os.path.join(RENDER_DIR, ground["file"])), -ground["x"], -ground["y"], 0)
    pages = [cutout.load_rgba(os.path.join(RENDER_DIR, page)) for page in art["pages"]]
    # Far to near, so a pixel is the nearest slice's that has it (the far ones hold a few of the nearer ones' too)
    for k in sorted(range(len(art["slices"])), key=lambda k: -depth(art["slices"][k]["at"], art)):
        piece = art["slices"][k]
        fx, fy, fw, fh = piece["frame"]
        lay(pages[piece["page"]][fy:fy + fh, fx:fx + fw], piece["x"], piece["y"], 1 + k)
    return art, (width, height), anchor, labels, render


def depth(at, art):
    """How far a point on the water is from the camera, as the game sorts by (larger: farther)"""
    yaw = np.radians(art["yaw"])
    return (at[0] - art["centre"][0]) * np.sin(yaw) - (at[1] - art["centre"][1]) * np.cos(yaw)


# ---------------------------------------------------------------------------
# The painting on the render's frame
# ---------------------------------------------------------------------------


def lay_painting(size):
    """The painting warped onto the render's frame (premultiplied while sampled, so its edge doesn't darken)"""
    with open(os.path.join(SOURCE_DIR, "island_warp.json")) as fh:
        warp = json.load(fh)
    width, height = size
    assert warp["size"] == [width, height], "island_warp.json is for another render: run align_port_art.py"
    step = warp["step"]
    gx, gy = np.asarray(warp["x"], np.float32), np.asarray(warp["y"], np.float32)
    # Where each pixel takes the painting from: the grid, bilinear
    sx = sample(gx, np.arange(width)[None, :] / step, np.arange(height)[:, None] / step)
    sy = sample(gy, np.arange(width)[None, :] / step, np.arange(height)[:, None] / step)
    paint = cutout.load_rgba(os.path.join(SOURCE_DIR, "island.webp"))
    pre = np.concatenate([paint[..., :3] * paint[..., 3:], paint[..., 3:]], axis=2)
    out = np.stack([sample(pre[..., c], sx, sy) for c in range(4)], axis=2)
    a = out[..., 3:]
    return np.concatenate([np.where(a > 0, out[..., :3] / np.maximum(a, 1e-6), 0), a], axis=2)


def sample(grid, x, y):
    """A grid's values at (x, y), bilinear; 0 outside it"""
    h, w = grid.shape
    x, y = np.broadcast_arrays(x, y)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    tx, ty = x - x0, y - y0
    out = np.zeros(x.shape, np.float32)
    for dy, wy in ((0, 1 - ty), (1, ty)):
        for dx, wx in ((0, 1 - tx), (1, tx)):
            xi, yi = x0 + dx, y0 + dy
            inside = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            out += np.where(inside, grid[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], 0) * wx * wy
    return out


def shifts(mask):
    """A mask moved a pixel each way (4-connected)"""
    up, down, left, right = (np.zeros_like(mask) for _ in range(4))
    up[:-1], down[1:], left[:, :-1], right[:, 1:] = mask[1:], mask[:-1], mask[:, 1:], mask[:, :-1]
    return up, down, left, right


def dilate(mask, n):
    for _ in range(n):
        up, down, left, right = shifts(mask)
        mask = mask | up | down | left | right
    return mask


def assign(labels, painted):
    """Each painted pixel's label: the render's; one the render has nothing at, or only the ground, takes the nearest
    slice within REACH (nearer slices first, where two meet), else the ground"""
    out = labels.copy()
    raised = out > 0
    for _ in range(REACH):
        best = np.zeros_like(out)
        for shifted in (np.roll(out, s, axis=a) for a in (0, 1) for s in (-1, 1)):
            ok = shifted > 0
            best = np.where(ok & ((best == 0) | (shifted < best)), shifted, best)
        grow = painted & ~raised & (best > 0)
        out = np.where(grow, best, out)
        raised = out > 0
    return np.where(painted & ~raised, 0, out)


# ---------------------------------------------------------------------------
# The pictures
# ---------------------------------------------------------------------------


def crop(picture):
    """A picture cropped to what shows: (it, its left, its top), or None if nothing does"""
    rows, cols = np.nonzero(picture[..., 3] > 0.002)
    if len(rows) == 0:
        return None
    t, b, l, r = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    return picture[t:b, l:r], int(l), int(t)


def pack(pieces):
    """Shelves of slices on pages PAGE wide, the tallest first: [(page, x, y)] in the pieces' order, and the pages'
    sizes"""
    order = sorted(range(len(pieces)), key=lambda k: -pieces[k].shape[0])
    places = [None] * len(pieces)
    pages = [[0, 0]]
    x = y = shelf = 0
    for k in order:
        h, w, _ = pieces[k].shape
        if x + w > PAGE:
            x, y, shelf = 0, y + shelf + GAP, 0
        if y + h > PAGE_HEIGHT:
            pages.append([0, 0])
            x = y = shelf = 0
        places[k] = (len(pages) - 1, x, y)
        pages[-1] = [max(pages[-1][0], x + w), max(pages[-1][1], y + h)]
        x += w + GAP
        shelf = max(shelf, h)
    return places, pages


def main():
    art, size, anchor, labels, _ = render_frame()
    painting = lay_painting(size)
    painted = painting[..., 3] > 0.02
    owner = assign(labels, painted)
    # The painting's coast, into the sea: the ground's alpha fades over its last FEATHER pixels (the walls and the
    # towers keep the painting's own edge)
    inside = painted.copy()
    fade = np.zeros(inside.shape, np.float32)
    for _ in range(FEATHER):
        up, down, left, right = shifts(inside)
        inside = inside & up & down & left & right
        fade += inside
    painting[..., 3] *= np.where(owner == 0, np.minimum(1, (fade + 1) / (FEATHER + 1)), 1)

    # The ground: what lies at the water's level, and the slices' edges round it
    near_raised = dilate(owner == 0, SEAM) & (owner > 0)
    ground = painting * ((owner == 0) | near_raised)[..., None]
    ground_crop = crop(ground)
    assert ground_crop, "nothing of the painting is at the water's level"
    ground_picture, gl, gt = ground_crop
    os.makedirs(OUT_DIR, exist_ok=True)
    cutout.save_webp(os.path.join(OUT_DIR, "ground.webp"), ground_picture, QUALITY)

    # The slices: each its own pixels and its nearer neighbours' round its edge
    slices, pieces = [], []
    for k, info in enumerate(art["slices"]):
        mine = owner == 1 + k
        if not mine.any():
            continue
        band = dilate(mine, SEAM) & (owner > 0) & (owner < 1 + k)
        piece = crop(painting * (mine | band)[..., None])
        if not piece:
            continue
        picture, l, t = piece
        pieces.append(picture)
        slices.append(dict(x=round(l - anchor[0], 1), y=round(t - anchor[1], 1), at=info["at"]))
    places, page_sizes = pack(pieces)
    pages = [np.zeros((h, w, 4), np.float32) for w, h in page_sizes]
    for piece, place, info in zip(pieces, places, slices):
        page, x, y = place
        h, w, _ = piece.shape
        pages[page][y:y + h, x:x + w] = piece
        info["page"] = page
        info["frame"] = [x, y, w, h]
    names = [f"raised_{n}.webp" for n in range(len(pages))]
    for name, page in zip(names, pages):
        cutout.save_webp(os.path.join(OUT_DIR, name), page, QUALITY)
    cutout.save_json(os.path.join(OUT_DIR, "port.json"), dict(
        pxPerUnit=art["pxPerUnit"],
        pitch=art["pitch"],
        yaw=art["yaw"],
        centre=art["centre"],
        ground=dict(file="ground.webp", w=int(ground_picture.shape[1]), h=int(ground_picture.shape[0]),
                    x=round(anchor[0] - gl, 1), y=round(anchor[1] - gt, 1)),
        pages=names,
        slices=[dict(page=s["page"], frame=s["frame"], x=s["x"], y=s["y"], at=s["at"]) for s in slices],
    ))
    print(f"port: ground {ground_picture.shape[1]}x{ground_picture.shape[0]}, {len(slices)} slices on "
          f"{len(pages)} page(s) {page_sizes}", flush=True)


if __name__ == "__main__":
    main()

"""
The painted islands in the game: each painting made over an island's outline (build_outlines.py) laid on the island,
cleaned of what its cut-out left round it, cut the way the game needs it, and its beach made the island's coast.

The paintings are in islands/source/painted/, named after their outline (island_01_C4.png, or island_01.png), the
island on a transparent sea. Run it with Blender's own Python, like the other scripts here:
    blender --background --python islands/build_island_art.py
or with any Python 3 that has numpy and Pillow:
    python islands/build_island_art.py
ISLAND_ONLY=island_01,island_07 in the environment makes only those (the rest is kept). Then, in the game's folder,
`npm run check`: the coasts are the game's logic.

A painting needn't keep its outline's size, nor lie on its coast exactly. It is never bent or stretched, which would
make it look melted; the island is changed to fit it instead:
1. Cleaned: the cut-out's halo round the island (all but transparent, red and yellow) is dropped, the island made fully
   opaque (the cut-out left it a little see-through), specks apart from it left out and pinholes in it filled.
2. Laid on the island: made smaller, the same in both directions, and moved, until its silhouette covers the
   island's coast best (what stands out of it narrower than twice TRIM, a rock or a crown, isn't counted).
3. Its beach made the coast: how far from the island's centre the silhouette's edge is on the water, at COAST_POINTS
   angles, goes into the game (canvas/src/game/world/paintedCoasts.json), so a ship runs aground where it sees the
   beach, and sails round it, and the minimap draws it.
4. Cut like the port (port/build_port_art.py): each pixel goes with the ground it stands on (on the water's level; what
   rises over the far beach with the beach under it) into slices SLICE units deep along the camera's view, each
   sorted with the ships by its depth: a ship behind the island goes behind its trees, one in front of it over its
   beach.
5. Given its shallows: light water lying round its new coast, under the ships, fading smoothly out into the sea, a
   little wider in some places than others.

What it makes:
  canvas/public/sprites/islands/island_NN.webp  an island's slices, packed into one page
  canvas/public/sprites/islands/island_NN_shallows.webp  its shallows, small: the game smooths them out
  canvas/public/sprites/islands/islands.json    the scale and the camera, and for each island its centre in the game,
                                                its slices (each one's place on the page, where its top left goes from
                                                the island's centre, and the point it is sorted by) and its shallows
                                                (their scale, and where their top left goes)
  canvas/src/game/world/paintedCoasts.json      each painted island's centre, size and coast (its radius at angles
                                                round it from east, clockwise on the map, as shares of its size)
  frames/islands/painted/island_NN.webp         for a look: each painting as laid on its island, over the sea, the
                                                coast the game takes drawn over it
An island with no painting stays vector-drawn in the game, with the coast it was made up with.
"""

import glob
import json
import math
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
        if _text.filepath and os.path.basename(_text.filepath) == "build_island_art.py":
            SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(ASSETS_DIR, "icons"))
import build_outlines  # noqa: E402 (islands/build_outlines.py, found through the path above)
import cutout  # noqa: E402 (icons/cutout.py)

PAINTED_DIR = os.path.join(SCRIPT_DIR, "source", "painted")
GAME_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas"))
OUT_DIR = os.path.join(GAME_DIR, "public", "sprites", "islands")
COASTS = os.path.join(GAME_DIR, "src", "game", "world", "paintedCoasts.json")
PREVIEW_DIR = os.path.join(ASSETS_DIR, "frames", "islands", "painted")

HALO = 0.1  # alpha: less is the cut-out's halo round the island, dropped
SOLID = 0.9  # alpha: more is the island itself, made fully opaque
TRIM = 3  # picture pixels: what stands out of the silhouette narrower than twice this isn't its edge
COAST_POINTS = 96  # points round a painted island's coast (a made-up one has 48): close to its painted beach
COAST_ANGLES = 1440  # angles the painted beach is measured at, before it is smoothed and cut down to COAST_POINTS
COAST_SMOOTH = 1.5  # degrees each way: the beach's distance smoothed round by this, so a rock on it isn't a cape
COAST_STEP = 0.25  # world units: how finely the beach's distance from the centre is measured
FEATHER = 2  # picture pixels over which the painting's edge fades into the sea
SHALLOWS_PX = 0.7  # pixels a world unit of an island's shallows: a smooth fade needs few, the game's filtering
# smooths them out
SHALLOWS_WIDTH = 75.0  # world units: how far out from the beach the shallows fade into the sea
SHALLOWS_WOBBLE = 0.35  # how much wider or narrower than that they are round the coast, as a share, changing slowly
SHALLOWS_WAVES = (2, 5)  # the slowest and the quickest of the waves of that wobble, times round the coast
SHALLOWS_ALPHA = 0.62  # how much of the light water's colour lies over the sea at the beach
SHALLOWS_EASE = 1.7  # how it fades out from the beach: more, the quicker by the beach and the softer far out
SHALLOWS_NEAR = (0.56, 0.9, 0.88)  # the light water's colour by the beach
SHALLOWS_FAR = (0.36, 0.78, 0.86)  # and where it fades into the sea
SLICE = 16.0  # world units of ground each slice covers along the camera's view, as the port's
SEAM = 2  # pixels of the nearer slices round a slice's edge it holds too, so no seam opens when mipmaps shrink them
GAP = 4  # pixels between two slices on a page: the game's mipmaps don't bleed one into the next
PAGE = 2048  # pixels: the widest a page is
QUALITY = 88
SEA = (0.15, 0.42, 0.55)  # the previews' sea
COAST = (1.0, 0.15, 0.1)  # the previews' coast


# ---------------------------------------------------------------------------
# Masks
# ---------------------------------------------------------------------------


def shift(mask, dx, dy, fill=False):
    """A mask moved dx right and dy down; what comes in from outside is `fill`"""
    out = np.full_like(mask, fill)
    h, w = mask.shape
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = mask[max(-dy, 0):h - max(dy, 0),
                                                                     max(-dx, 0):w - max(dx, 0)]
    return out


def dilate(mask, n):
    """A mask grown by n pixels each way, roundish (alternately by its 4 and its 8 neighbours)"""
    for i in range(n):
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1)) + (((1, 1), (1, -1), (-1, 1), (-1, -1)) if i % 2 else ())
        grown = mask.copy()
        for dx, dy in steps:
            grown |= shift(mask, dx, dy)
        mask = grown
    return mask


def erode(mask, n):
    return ~dilate(~mask, n)


def flood(free, seed):
    """The pixels of `free` joined to `seed` (4-connected): runs along rows, then along columns, that touch what is
    reached so far are reached, until nothing more is"""
    reached = seed & free
    count = -1
    while reached.sum() != count:
        count = reached.sum()
        reached = runs(free, reached)
        reached = runs(free.T, reached.T).T
    return reached


def runs(free, reached):
    """Along each row, the whole run of `free` pixels any of whose pixels is reached"""
    starts = free & ~np.concatenate([np.zeros((free.shape[0], 1), bool), free[:, :-1]], axis=1)
    ids = np.where(free, np.cumsum(starts.ravel()).reshape(free.shape), 0)
    hit = np.zeros(ids.max() + 1, bool)
    hit[ids[reached]] = True
    hit[0] = False
    return hit[ids]


def box(values, r):
    """The mean of each pixel's (2r + 1)² square, summed through an integral image"""
    pad = np.pad(values, ((r + 1, r), (r + 1, r)) + ((0, 0),) * (values.ndim - 2), mode="edge")
    total = pad.cumsum(0).cumsum(1)
    n = 2 * r + 1
    return (total[n:, n:] - total[:-n, n:] - total[n:, :-n] + total[:-n, :-n]) / (n * n)


def fill_polygon(points, size):
    """Which pixels of a picture `size` have their centres inside a closed polygon (pixels, from the top left)"""
    width, height = size
    p = np.asarray(points, np.float64)
    q = np.roll(p, -1, axis=0)
    inside = np.zeros((height, width), bool)
    xs = np.arange(width) + 0.5
    for row in range(height):
        y = row + 0.5
        crosses = (p[:, 1] <= y) != (q[:, 1] <= y)
        if not crosses.any():
            continue
        a, b = p[crosses], q[crosses]
        cut = np.sort(a[:, 0] + (y - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1]))
        inside[row] = (np.searchsorted(cut, xs) % 2) == 1
    return inside


def gather(mask, x, y):
    """A mask at points (pixels from its top left); nothing outside it"""
    h, w = mask.shape
    xi, yi = np.floor(x).astype(int), np.floor(y).astype(int)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    return np.where(ok, mask[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], False)


# ---------------------------------------------------------------------------
# A painting laid on its island
# ---------------------------------------------------------------------------


def clean(paint):
    """The painting with what its cut-out left gone, premultiplied; and its silhouette"""
    alpha = np.clip((paint[..., 3] - HALO) / (SOLID - HALO), 0, 1)
    solid = alpha > 0.5
    ys, xs = np.nonzero(solid)
    seed = np.zeros_like(solid)
    k = np.argmin((xs - xs.mean()) ** 2 + (ys - ys.mean()) ** 2)
    seed[ys[k], xs[k]] = True
    island = flood(solid, seed)
    border = np.zeros_like(solid)
    border[[0, -1], :] = border[:, [0, -1]] = True
    holes = ~flood(~island, border) & ~island
    alpha = np.where(dilate(island, 2), alpha, 0)
    pre = paint[..., :3] * alpha[..., None]
    if holes.any():
        # A pinhole takes the colour round it
        near = box(pre, 2) / np.maximum(box(alpha, 2), 1e-6)[..., None]
        pre = np.where(holes[..., None], near, pre)
        alpha = np.where(holes, 1.0, alpha)
    return np.concatenate([pre, alpha[..., None]], axis=2).astype(np.float32), island | holes


def fit(trimmed, coast):
    """How the painting lies on the island's picture, with no stretch: a point p of the picture takes the painting at
    scale * p + shift. The scale and shift whose silhouette shares the most with the coast, tried a little either way
    from the one of the same area at the same middle"""
    ys, xs = np.nonzero(trimmed)
    cy, cx = np.nonzero(coast)
    centre_in = np.array([xs.mean(), ys.mean()]) + 0.5
    centre_out = np.array([cx.mean(), cy.mean()]) + 0.5
    scale = math.sqrt(trimmed.sum() / max(coast.sum(), 1))
    # Every other pixel of the island's picture is enough to measure by
    gy, gx = np.mgrid[0:coast.shape[0]:2, 0:coast.shape[1]:2]
    px, py = gx + 0.5, gy + 0.5
    target = coast[gy, gx]

    def lay(p):
        s, tx, ty = p
        return s, centre_in + np.array([tx, ty]) - s * centre_out

    def overlap(p):
        s, b = lay(p)
        got = gather(trimmed, s * px + b[0], s * py + b[1])
        return (got & target).sum() / max((got | target).sum(), 1)

    params = np.array([scale, 0.0, 0.0])
    best = overlap(params)
    steps = np.array([0.02 * scale, 2 * scale, 2 * scale])
    least = steps / 32
    while (steps > least).any():
        better = False
        for i in range(3):
            for sign in (1, -1):
                tried = params.copy()
                tried[i] += sign * steps[i]
                score = overlap(tried)
                if score > best:
                    params, best, better = tried, score, True
                    break
        if not better:
            steps /= 2
    return lay(params), best


def lanczos(x, a=3):
    x = np.abs(x)
    return np.where(x < a, np.sinc(x) * np.sinc(x / a), 0.0)


def place_matrix(n_in, n_out, scale, offset):
    """Rows of weights that make n_out pixels, the one at p (its centre) the painting's at scale * p + offset (Lanczos,
    widened as it shrinks, so nothing aliases)"""
    wide = min(1 / scale, 1.0)
    at = scale * (np.arange(n_out) + 0.5) + offset
    w = lanczos(((np.arange(n_in) + 0.5)[None, :] - at[:, None]) * wide)
    return (w / np.maximum(w.sum(axis=1, keepdims=True), 1e-9)).astype(np.float32)


def place(picture, scale, offset, size):
    """The painting shrunk and moved into a picture `size`, in one pass"""
    width, height = size
    rows = place_matrix(picture.shape[0], height, scale, offset[1])
    cols = place_matrix(picture.shape[1], width, scale, offset[0])
    out = np.tensordot(rows, picture, axes=(1, 0))
    return np.ascontiguousarray(np.tensordot(out, cols, axes=(1, 1)).transpose(0, 2, 1))


def to_picture(x, y, centre, k=build_outlines.PX_PER_UNIT):
    """Points on the water (world units from the island's centre) in the island's picture (pixels, k a world unit)"""
    u = x * build_outlines.RIGHT[0] + y * build_outlines.RIGHT[1]
    v = x * build_outlines.FWD[0] + y * build_outlines.FWD[1]
    return centre[0] + u * k, centre[1] - v * build_outlines.SIN_P * k


def to_water(px, py, centre, k=build_outlines.PX_PER_UNIT):
    """Pixels of an island's picture (k a world unit) on the water: world units from the island's centre"""
    u = (px - centre[0]) / k
    v = -(py - centre[1]) / (k * build_outlines.SIN_P)
    return u * build_outlines.RIGHT[0] + v * build_outlines.FWD[0], u * build_outlines.RIGHT[1] + v * build_outlines.FWD[1]


def painted_coast(trimmed, scale, offset, centre, reach):
    """The beach the painting lies on, as the game's coast: its radius (a circle of its area) and its distance from the
    centre at COAST_POINTS angles from east, clockwise on the map, as shares of it"""
    angles = np.arange(COAST_ANGLES) * 2 * np.pi / COAST_ANGLES
    r = np.arange(0, reach * 2, COAST_STEP)
    x, y = to_picture(np.cos(angles)[:, None] * r[None, :], np.sin(angles)[:, None] * r[None, :], centre)
    land = gather(trimmed, scale * x + offset[0], scale * y + offset[1])
    # The farthest of the land along each line from the centre: a bay the line crosses twice is the sea
    edge = r[np.where(land.any(axis=1), land.shape[1] - 1 - np.argmax(land[:, ::-1], axis=1), 0)]
    half = max(1, round(COAST_SMOOTH * COAST_ANGLES / 360))
    wrapped = np.concatenate([edge[-half:], edge, edge[:half]])
    windows = np.lib.stride_tricks.sliding_window_view(wrapped, 2 * half + 1)
    smooth = np.median(windows, axis=1)
    radius = math.sqrt(np.mean(smooth ** 2))
    pick = np.arange(COAST_POINTS) * COAST_ANGLES // COAST_POINTS
    return radius, smooth[pick] / radius


def lay_painting(paint, island_data):
    """The painting laid on its island's picture (the outline's frame), straight alpha; where the island's centre is in
    it, the coast the game takes from it, and how much of the island's coast its silhouette shared"""
    size, centre, line = build_outlines.frame(island_data)
    pre, silhouette = clean(paint)
    n = max(1, round(TRIM * math.sqrt(silhouette.sum() / max(fill_polygon(line, size).sum(), 1))))
    trimmed = dilate(erode(silhouette, n), n)
    (scale, offset), score = fit(trimmed, fill_polygon(line, size))
    out = place(pre, scale, offset, size)
    alpha = np.clip(out[..., 3], 0, 1)
    rgb = np.clip(out[..., :3], 0, alpha[..., None]) / np.maximum(alpha, 1e-4)[..., None]

    # The edge fades into the sea over its last FEATHER pixels
    inside = alpha > 0.5
    fade = np.zeros(alpha.shape, np.float32)
    for _ in range(FEATHER):
        inside = erode(inside, 1)
        fade += inside
    alpha = np.where(alpha > 1e-3, alpha * np.minimum(1, (fade + 1) / (FEATHER + 1)), 0)
    picture = np.concatenate([np.clip(rgb, 0, 1), alpha[..., None]], axis=2)

    cx, cy = island_data["x"], island_data["y"]
    reach = max(math.hypot(x - cx, y - cy) for x, y in island_data["coast"])
    radius, shape = painted_coast(trimmed, scale, offset, centre, reach)
    return picture, centre, (radius, shape), score


# ---------------------------------------------------------------------------
# Slices
# ---------------------------------------------------------------------------


def coast_line(radius, shape, centre):
    """The game's coast in the island's picture: straight between its points, as ships meet it"""
    angles = np.arange(len(shape)) * 2 * np.pi / len(shape)
    x, y = to_picture(np.cos(angles) * shape * radius, np.sin(angles) * shape * radius, centre)
    return list(zip(x, y))


def shallows(radius, shape, seed):
    """The light water round the island, a picture on the water as the camera sees it (SHALLOWS_PX a world unit): from
    under the island out over the sea, fading smoothly from the beach the farther from it, wider in some places than
    others; and where the island's centre is in it"""
    angles = np.arange(len(shape)) * 2 * np.pi / len(shape)
    cx, cy = np.cos(angles) * shape * radius, np.sin(angles) * shape * radius
    extent = radius * max(shape) + SHALLOWS_WIDTH * (1 + SHALLOWS_WOBBLE) + 4 / SHALLOWS_PX
    width = math.ceil(2 * extent * SHALLOWS_PX)
    height = math.ceil(2 * extent * build_outlines.SIN_P * SHALLOWS_PX)
    centre = (width / 2, height / 2)
    gy, gx = np.mgrid[0:height, 0:width]
    x, y = to_water(gx + 0.5, gy + 0.5, centre, SHALLOWS_PX)
    # How far each pixel is from the beach: from the nearest of the coast's edges
    far = np.full(x.shape, np.inf)
    for i in range(len(shape)):
        ax, ay = cx[i], cy[i]
        ex, ey = cx[(i + 1) % len(shape)] - ax, cy[(i + 1) % len(shape)] - ay
        t = np.clip(((x - ax) * ex + (y - ay) * ey) / (ex * ex + ey * ey), 0, 1)
        far = np.minimum(far, np.hypot(x - ax - t * ex, y - ay - t * ey))
    inside = fill_polygon(list(zip(*to_picture(cx, cy, centre, SHALLOWS_PX))), (width, height))
    # Wider and narrower round the coast in a few slow waves, its own for each island
    rng = np.random.default_rng(seed)
    turn = np.arctan2(y, x)
    wobble = sum(rng.normal() / m * np.cos(m * turn + rng.uniform(0, 2 * np.pi))
                 for m in range(SHALLOWS_WAVES[0], SHALLOWS_WAVES[1] + 1))
    wobble /= max(np.abs(wobble).max(), 1e-6)
    t = np.where(inside, 0, np.clip(far / (SHALLOWS_WIDTH * (1 + SHALLOWS_WOBBLE * wobble)), 0, 1))
    alpha = SHALLOWS_ALPHA * (1 - t) ** SHALLOWS_EASE
    colour = np.asarray(SHALLOWS_NEAR) * (1 - t[..., None]) + np.asarray(SHALLOWS_FAR) * t[..., None]
    return np.concatenate([colour, alpha[..., None]], axis=2).astype(np.float32), centre


def ground_along(alpha, coast, centre):
    """For each pixel of the island's picture, how far forward along the camera's view on the water (world units from
    the centre) the ground it stands on is: on the water's level under it, or for what rises over the far beach the
    beach under it"""
    height, width = alpha.shape
    along = -((np.arange(height) + 0.5 - centre[1]) / (build_outlines.SIN_P * build_outlines.PX_PER_UNIT))
    ground = np.broadcast_to(along[:, None], alpha.shape).copy()
    far = np.argmax(coast, axis=0)
    over = coast.any(axis=0)[None, :] & (np.arange(height)[:, None] < far[None, :]) & ~coast
    ground[over] = np.broadcast_to(along[far][None, :], alpha.shape)[over]
    return ground


def cut(picture, coast, centre, island_data):
    """The slices, near to far: each one's picture, its top left from the island's centre and the point it is sorted
    by"""
    alpha = picture[..., 3]
    shown = alpha > 0.002
    ground = ground_along(alpha, coast, centre)
    near = ground[shown].min()
    band = np.where(shown, np.floor((ground - near) / SLICE).astype(int), -1)
    opaque = alpha > 0.99
    fwd = build_outlines.FWD
    slices = []
    for k in range(band.max() + 1):
        mine = band == k
        if not mine.any():
            continue
        # The nearer slices' opaque pixels round its edge: drawn over it again by them
        held = mine | (dilate(mine, SEAM) & opaque & (band >= 0) & (band < k))
        rows, cols = np.nonzero(held)
        top, bottom, left, right = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
        middle = near + (k + 0.5) * SLICE
        slices.append(dict(
            picture=picture[top:bottom, left:right] * held[top:bottom, left:right, None],
            x=round(float(left - centre[0]), 1),
            y=round(float(top - centre[1]), 1),
            at=[round(island_data["x"] + middle * fwd[0], 2), round(island_data["y"] + middle * fwd[1], 2)],
        ))
    return slices


def pack(pieces):
    """Shelves of slices on one page at most PAGE wide, the tallest first: each one's (x, y), and the page's size"""
    width = min(PAGE, max(p.shape[1] for p in pieces))
    order = sorted(range(len(pieces)), key=lambda k: -pieces[k].shape[0])
    places = [None] * len(pieces)
    x = y = shelf = used = 0
    for k in order:
        h, w, _ = pieces[k].shape
        if x and x + w > width:
            x, y, shelf = 0, y + shelf + GAP, 0
        places[k] = (x, y)
        used = max(used, x + w)
        x += w + GAP
        shelf = max(shelf, h)
    return places, (used, y + shelf)


# ---------------------------------------------------------------------------


def preview(picture, centre, water, water_centre, line):
    """The island over its shallows over the sea, the game's coast drawn over it"""
    h, w, _ = picture.shape
    scale = SHALLOWS_PX / build_outlines.PX_PER_UNIT
    offset = np.asarray(water_centre) - scale * np.asarray(centre)
    pre = np.concatenate([water[..., :3] * water[..., 3:], water[..., 3:]], axis=2)
    light = np.clip(place(pre, scale, offset, (w, h)), 0, 1)
    out = light[..., :3] + np.asarray(SEA, np.float32) * (1 - light[..., 3:])
    a = picture[..., 3:]
    out = picture[..., :3] * a + out * (1 - a)
    p = np.asarray(line)
    q = np.roll(p, -1, axis=0)
    for s in np.linspace(0, 1, 12, endpoint=False):
        x = (p[:, 0] + (q[:, 0] - p[:, 0]) * s).astype(int)
        y = (p[:, 1] + (q[:, 1] - p[:, 1]) * s).astype(int)
        ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        out[y[ok], x[ok]] = COAST
    return out


def write_coasts(coasts):
    """paintedCoasts.json, an island a line: a change to one painting is a change to one line"""
    lines = [json.dumps(coasts[k], separators=(", ", ": ")) for k in sorted(coasts)]
    with open(COASTS, "w", newline="\n") as fh:
        fh.write('{\n  "islands": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n")


def main():
    with open(os.path.join(SCRIPT_DIR, "islands.json")) as fh:
        islands = {island["id"]: island for island in json.load(fh)["islands"]}
    only = [name for name in os.environ.get("ISLAND_ONLY", "").split(",") if name]
    os.makedirs(OUT_DIR, exist_ok=True)
    index = os.path.join(OUT_DIR, "islands.json")
    made, coasts = {}, {}
    if only and os.path.exists(index) and os.path.exists(COASTS):
        with open(index) as fh:
            made = {island["id"]: island for island in json.load(fh)["islands"]}
        with open(COASTS) as fh:
            coasts = {island["id"]: island for island in json.load(fh)["islands"]}
    for path in sorted(glob.glob(os.path.join(PAINTED_DIR, "island_*.png"))):
        island_id = "_".join(os.path.basename(path).split(".")[0].split("_")[:2])
        if only and island_id not in only:
            continue
        island = islands.get(island_id)
        if not island:
            print(f"{path}: no {island_id} in islands.json, left out", flush=True)
            continue
        picture, centre, (radius, shape), score = lay_painting(cutout.load_rgba(path), island)
        line = coast_line(radius, shape, centre)
        water, water_centre = shallows(radius, shape, seed=int(island_id.split("_")[1]))
        water_name = f"{island_id}_shallows.webp"
        cutout.save_webp(os.path.join(OUT_DIR, water_name), water, QUALITY)
        cutout.save_webp(os.path.join(PREVIEW_DIR, f"{island_id}.webp"),
                         preview(picture, centre, water, water_centre, line), QUALITY)
        slices = cut(picture, fill_polygon(line, picture.shape[1::-1]), centre, island)
        places, (w, h) = pack([s["picture"] for s in slices])
        page = np.zeros((h, w, 4), np.float32)
        for s, (x, y) in zip(slices, places):
            ph, pw, _ = s["picture"].shape
            page[y:y + ph, x:x + pw] = s["picture"]
            s["frame"] = [x, y, pw, ph]
        name = f"{island_id}.webp"
        cutout.save_webp(os.path.join(OUT_DIR, name), page, QUALITY)
        at = [island["x"], island["y"]]
        made[island_id] = dict(
            id=island_id,
            at=at,
            page=name,
            slices=[dict(frame=s["frame"], x=s["x"], y=s["y"], at=s["at"]) for s in slices],
            shallows=dict(file=water_name, pxPerUnit=SHALLOWS_PX, x=round(-water_centre[0], 1),
                          y=round(-water_centre[1], 1)),
        )
        coasts[island_id] = dict(id=island_id, at=at, radius=round(radius, 3),
                                 shape=[round(float(k), 4) for k in shape])
        print(f"{name}: {len(slices)} slices on {w}x{h}; the painting shared {score:.1%} with the coast, its own coast "
              f"{radius / island['radius'] - 1:+.1%} in size", flush=True)
    cutout.save_json(index, dict(
        pxPerUnit=build_outlines.PX_PER_UNIT,
        pitch=build_outlines.PITCH,
        yaw=build_outlines.YAW,
        islands=[made[k] for k in sorted(made)],
    ))
    write_coasts(coasts)
    print(f"{OUT_DIR}: {len(made)} painted islands; their coasts in {COASTS}", flush=True)


main()

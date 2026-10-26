"""
The port, Saltwind Harbour: its island, town, castle and harbour, rendered for the game's isometric camera.

Run in a background Blender (about 10 minutes on a GTX 1060):
    blender --background --python port/build_port.py
or in Blender: Scripting -> Open -> port/build_port.py -> Run Script (Blender is busy until it is done; progress is
printed to the system console). PORT_PREVIEW=1 in the environment renders a small, quick picture into
frames/port/preview.png instead, and writes nothing into the game.

Input: port/layout.json, the port's geometry exported from the game (src/game/world/port.ts): the island's coast with
the harbour walls, the quay, the basin. The picture must match it: after a change there, export it again
(cd canvas && node ../blender-assets/port/export_layout.mjs) and run this.

What it makes, in canvas/public/sprites/port/:
  ground.webp     everything at the water's level: the sea floor seen through the shallows and the basin, the wet
                  sand, the shadows on the water. Drawn under the ships
  raised_<n>.webp the land and everything on it, cut into SLICE-deep slices along the camera's view (by where they
                  stand on the ground), packed into pages. Each slice is sorted with the ships by its depth, so a
                  ship sails behind the hill, between the harbour walls, in front of the town
  port.json       the scale, where the island's centre is in the pictures, each slice's frame, page, place and depth,
                  and where the lighthouse's lamp and the flagstaff's top are (the game animates them)
and port/port.blend, the scene.

Built in the harbour's frame: u to the right of the screen, v up it (away from the camera), z up, round the island's
centre; every object is turned -45 degrees about z into Blender's world (x east, y north). Game coordinates have y
pointing south, so Blender's y is the game's negated, as for the ships and the islands.

Three renders, all from the same camera: the colour; every pixel's position on its surface (one sample, no
filtering), which says whether a pixel is at the water's level or which slice it belongs to; and the shadows on the
water (a shadow catcher at z = 0). Textures from Poly Haven (polyhaven.com, CC0), downloaded into
textures/polyhaven/ on the first run.
"""

import json
import math
import os
import sys
import time
import traceback
import urllib.request

import bpy
import numpy as np
from mathutils import Matrix, Vector

PREVIEW = bool(os.environ.get("PORT_PREVIEW"))
PX_PER_UNIT = float(os.environ.get("PORT_PX") or (1.0 if PREVIEW else 2.8))  # sprite pixels per world unit, as the ships'
SAMPLES = int(os.environ.get("PORT_SAMPLES") or (16 if PREVIEW else 48))
CAM_PITCH = 30.0
CAM_YAW = 45.0
LIGHT_GAME = (-0.6, 0.1, 0.8)
SUN_STRENGTH = 2.0
SUN_ANGLE = 1.2
AMBIENT = 0.72
WATER_SHADOW = 0.32  # how dark a shadow on the water is
SLICE = 16.0  # world units of ground each raised slice covers along the camera's view
CUT = 0.6  # world units: a surface lower than this is at the water's level ("ground")
MARGIN = 4  # pixels round a cropped picture
PAGE = 4096  # pixels: the largest page of slices
GUTTER = 4  # pixels of air between slices on a page: the game's mipmaps don't bleed one into the next
UNDER = -0.3  # world units: what stands in the water starts just under it (deeper, it would show through it)
UNDERLAP = 3  # pixels: what each picture also holds of the nearer ones round its edge (see cut_up)
S2 = math.sqrt(0.5)

# Terrain, world units
GRID = 1.5  # between terrain vertices
SHELF = 50  # how far out from the coast the sea floor is seen
DEPTH = 6.0  # how deep the sea floor goes there
BASIN_DEPTH = 4.8  # the harbour basin's floor, below the water: deep, the sea's own colour
WALL_FOOT = 4.8  # the sea floor at the foot of a harbour wall: the walls rise out of deep water
BEACH_HEIGHT = 1.6
BEACH_WIDTH = 9
LAND = 5.0  # the land's plateau above the water
QUAY_TOP = 2.6  # the quay and the waterfront, above the water
TOWN_SLOPE = 0.09  # the town climbs this much a unit up from the quay
HILL = dict(u=0.0, v=30.0, ru=175.0, rv=140.0, height=50.0, top=0.36, ledge=7.0)  # ledge: rock steps, world units  # the castle's hill: centre, radii, height
ROAD_WIDTH = 3.4  # half
WALL_HEIGHT = 6.0  # the harbour walls' top above the water (as the game's vector port)
WALL_THICKNESS = 14.0  # as port.ts

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()
for _text in bpy.data.texts:
    if _text.filepath and os.path.basename(_text.filepath) == "build_port.py":
        SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
TEX_DIR = os.path.join(ASSETS_DIR, "textures", "polyhaven")
GAME_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas"))
SPRITES_DIR = os.path.join(GAME_DIR, "public", "sprites", "port")
FRAMES_DIR = os.path.join(ASSETS_DIR, "frames", "port")
LAYOUT = os.path.join(SCRIPT_DIR, "layout.json")
BLEND = os.path.join(SCRIPT_DIR, "port.blend")

with open(LAYOUT) as _fh:
    LAYOUT_DATA = json.load(_fh)
CX, CY = LAYOUT_DATA["island"]["x"], LAYOUT_DATA["island"]["y"]


def local(p):
    """A game point (x, y) in the harbour's frame (u, v) round the island's centre"""
    dx, dy = p[0] - CX, p[1] - CY
    return (S2 * (dx + dy), S2 * (dx - dy))


def game(u, v):
    """A point of the harbour's frame back in game coordinates"""
    return (CX + S2 * (u + v), CY + S2 * (u - v))


TURN = Matrix.Rotation(math.radians(-45), 4, "Z")  # the harbour's frame into Blender's world


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Signed distances and noise (numpy, any shape of points)
# ---------------------------------------------------------------------------


def signed_distance(px, py, poly):
    """Distance from points to a polygon's edge: positive inside"""
    P = np.asarray(poly, float)
    d2 = np.full(np.shape(px), np.inf)
    inside = np.zeros(np.shape(px), bool)
    for (ax, ay), (bx, by) in zip(P, np.roll(P, -1, 0)):
        ex, ey = bx - ax, by - ay
        t = np.clip(((px - ax) * ex + (py - ay) * ey) / max(ex * ex + ey * ey, 1e-12), 0, 1)
        dx, dy = px - (ax + t * ex), py - (ay + t * ey)
        d2 = np.minimum(d2, dx * dx + dy * dy)
        with np.errstate(divide="ignore", invalid="ignore"):
            cross = (ay > py) != (by > py)
            xs = ax + (py - ay) * ex / np.where(ey == 0, 1e-12, ey)
        inside ^= cross & (px < xs)
    d = np.sqrt(d2)
    return np.where(inside, d, -d)


def polyline_distance(px, py, line):
    """Distance from points to a polyline, and how far along it (world units) the nearest point is"""
    P = np.asarray(line, float)
    best = np.full(np.shape(px), np.inf)
    along = np.zeros(np.shape(px))
    start = 0.0
    for (ax, ay), (bx, by) in zip(P[:-1], P[1:]):
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey)
        t = np.clip(((px - ax) * ex + (py - ay) * ey) / max(length * length, 1e-12), 0, 1)
        d = np.hypot(px - (ax + t * ex), py - (ay + t * ey))
        closer = d < best
        best = np.where(closer, d, best)
        along = np.where(closer, start + t * length, along)
        start += length
    return best, along


def waves_noise(x, y, seed, scale, octaves=4):
    """Smooth noise from a few plane waves per octave: cheap, and the same for a seed"""
    rng = np.random.default_rng(seed)
    out = np.zeros(np.shape(x))
    amp, freq = 1.0, 1 / scale
    for _ in range(octaves):
        for _ in range(3):
            ang = rng.uniform(0, 2 * np.pi)
            out += amp * np.sin((x * math.cos(ang) + y * math.sin(ang)) * freq * 2 * np.pi + rng.uniform(0, 2 * np.pi))
        amp *= 0.5
        freq *= 2.03
    return out / 3


# ---------------------------------------------------------------------------
# The layout, in the harbour's frame
# ---------------------------------------------------------------------------

BAY_SPLICE = 165  # world units across the harbour where the bay's shore runs into the island's own coast (port.ts)


def normals_of(line):
    """Unit normals of a polyline at its points, to the left of its way"""
    P = np.asarray(line, float)
    ahead = np.gradient(P, axis=0)
    ahead /= np.linalg.norm(ahead, axis=1, keepdims=True) + 1e-12
    return np.stack([-ahead[:, 1], ahead[:, 0]], 1)


def lengths_of(line):
    """How far along a polyline each of its points is"""
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(np.asarray(line, float), axis=0).T))])


def turned_to(line, normals, polygon, inside=True):
    """The normals turned to point into a polygon (or out of it)"""
    probe = np.asarray(line) + normals * 4
    into = (signed_distance(probe[:, 0], probe[:, 1], polygon) > 0).mean() > 0.5
    return normals if into == inside else -normals


def harbour_layout():
    L = LAYOUT_DATA
    land = [local(p) for p in L["shore"]]
    # The bay's shore from headland to headland: the shore's first points, up to where it runs into the island's own
    # coast (as port.ts makes it)
    n = 0
    while n < len(land) and abs(land[n][0]) <= BAY_SPLICE + 0.5:
        n += 1
    bay = np.asarray(land[:n])
    quay = np.asarray([local(p) for p in L["quay"]])
    basin = [local(p) for p in L["basin"]]
    walls = []
    for wall in L["walls"]:
        line = np.asarray([local(p) for p in wall])
        # The side of the wall the sea is on: away from the basin
        walls.append(dict(line=line, sea=turned_to(line, normals_of(line), basin, inside=False)))
    return dict(coast=[local(p) for p in L["island"]["coast"]], land=land, bay=bay,
                inland=turned_to(bay, normals_of(bay), land), quay=quay,
                quay_inland=turned_to(quay, normals_of(quay), land), walls=walls, basin=basin,
                mooring=local(L["mooring"]))


H = harbour_layout()


def along_line(line, normals, share, out=0.0):
    """A point `share` of the way along a polyline, moved `out` along its normals there, and the line's heading"""
    s = lengths_of(line)
    at = share * s[-1]
    i = int(np.clip(np.searchsorted(s, at) - 1, 0, len(line) - 2))
    t = (at - s[i]) / max(s[i + 1] - s[i], 1e-9)
    p = line[i] + (line[i + 1] - line[i]) * t
    n = normals[i] + (normals[i + 1] - normals[i]) * t
    n /= np.linalg.norm(n)
    d = line[i + 1] - line[i]
    return p + n * out, math.atan2(d[1], d[0])


# ---------------------------------------------------------------------------
# The ground: the town round the bay, the road and the castle, and the heights
# ---------------------------------------------------------------------------

WATERFRONT = 11.0  # world units of paved quay between the water and the first houses
ROW_STEP = 20.0  # world units between rows of houses, up from the bay
FIRST_ROW = WATERFRONT + 7  # world units inland from the bay's shore: the middle of the first row
TOWN_ROWS = 6
TOWN_DEPTH = FIRST_ROW + (TOWN_ROWS - 0.5) * ROW_STEP  # how far up from the bay the town reaches
TOWN_WIDTH = 190  # world units either side of the harbour's middle
LANES = (0.17, 0.33, 0.66, 0.82)  # lanes climbing from the waterfront up through the town: shares along the bay
SQUARE_SIZE = (44.0, 24.0)  # the market square: along the quay and back from it, world units
_square, _square_angle = along_line(H["quay"], H["quay_inland"], 0.5, WATERFRONT + SQUARE_SIZE[1] / 2 + 1)
SQUARE = dict(u=float(_square[0]), v=float(_square[1]), angle=_square_angle)
CASTLE = dict(u=0.0, v=34.0, half_u=44.0, half_v=34.0)
# Dirt paths out of the town: to the windmill and the fields, to the shipyard
PATHS = [[(-165, -130), (-190, -105), (-207, -72), (-212, -52)], [(-190, -105), (-232, -112)],
         [(170, -140), (195, -126), (215, -126)]]
# Fields on the plateau either side of the hill: centre u, v and size, world units
FIELDS = [(-238, -98, 40, 28), (-262, -40, 30, 40), (222, -110, 44, 28), (250, -55, 36, 44), (-200, 70, 40, 30),
          (215, 40, 44, 34)]
CASTLE_Z = HILL["height"]
# The road from the back of the market square up the town and in switchbacks up the hill to the castle's gate
_back = (SQUARE["u"] - math.sin(SQUARE["angle"]) * (SQUARE_SIZE[1] / 2 + 2),
         SQUARE["v"] + math.cos(SQUARE["angle"]) * (SQUARE_SIZE[1] / 2 + 2))
ROAD = [_back, (0, -96), (-74, -76), (64, -50), (-44, -26), (-6, -10), (0, CASTLE["v"] - CASTLE["half_v"] - 1)]


def in_square(u, v, margin=0.0):
    c, s = math.cos(SQUARE["angle"]), math.sin(SQUARE["angle"])
    du, dv = np.asarray(u) - SQUARE["u"], np.asarray(v) - SQUARE["v"]
    a, b = du * c + dv * s, -du * s + dv * c
    return (np.abs(a) < SQUARE_SIZE[0] / 2 + margin) & (np.abs(b) < SQUARE_SIZE[1] / 2 + margin)


def town_share(u, v, bay_dist, d):
    """How much a point is in the town: round the bay, up to TOWN_DEPTH from its shore, on the land"""
    return (smoothstep(TOWN_DEPTH + 14, TOWN_DEPTH - 2, bay_dist) * smoothstep(TOWN_WIDTH + 12, TOWN_WIDTH - 12,
            np.abs(u)) * smoothstep(-2, 2, d))


def lane_lines():
    """The lanes climbing up through the town, straight up from the bay's shore"""
    lines = []
    for share in LANES:
        p, _ = along_line(H["bay"], H["inland"], share)
        q, _ = along_line(H["bay"], H["inland"], share, TOWN_DEPTH)
        lines.append([tuple(p), tuple(q)])
    return lines


LANE_LINES = lane_lines()


def hill_height(u, v):
    r = np.hypot((u - HILL["u"]) / HILL["ru"], (v - HILL["v"]) / HILL["rv"])
    lumps = waves_noise(u, v, 77, 60, 3)
    r = r * (1 + 0.07 * lumps)
    # A steep mount on a gentle foot
    profile = 0.86 * (1 - smoothstep(HILL["top"], 0.8, r)) + 0.14 * (1 - smoothstep(0.7, 1.05, r))
    z = HILL["height"] * profile
    # Rocky ledges: steep steps of rock between flatter shelves, wandering round the mount
    broken = waves_noise(u, v, 78, 24, 3)
    q = (z + 5 * broken) / HILL["ledge"]
    stepped = (np.floor(q) + smoothstep(0.6, 1.0, q - np.floor(q))) * HILL["ledge"] - 5 * broken
    slope_zone = smoothstep(HILL["top"] + 0.03, HILL["top"] + 0.12, r) * smoothstep(1.0, 0.8, r)
    # Rock in some places, plain slope in others
    rocky = smoothstep(-0.2, 0.4, waves_noise(u, v, 79, 70, 2))
    z = mix(z, stepped, 0.6 * slope_zone * rocky)
    return z, r


def base_heights(u, v):
    """Heights before the road is cut in: the sea floor, the beaches, the land, the town, the hill"""
    d = signed_distance(u, v, H["land"])
    d_walls = signed_distance(u, v, H["coast"])  # the game's coast: the land and the walls
    noise = waves_noise(u, v, 5, 90)
    fine = waves_noise(u, v, 6, 9, 3)
    # The sea floor: shelving away from the coast; the walls stand in deep water, and so does the basin
    shelf = DEPTH * smoothstep(0, SHELF, -d_walls) ** 0.7
    z_sea = -np.maximum(shelf, WALL_FOOT * smoothstep(-2, -12, d)) + 0.15 * fine
    in_basin = smoothstep(-14, 8, signed_distance(u, v, H["basin"]))
    z_sea = mix(z_sea, -BASIN_DEPTH + 0.25 * fine, in_basin)
    # The land: a beach, then the plateau
    z_beach = BEACH_HEIGHT * np.clip(d / BEACH_WIDTH, 0, 1) ** 1.2
    rise = smoothstep(BEACH_WIDTH * 0.8, BEACH_WIDTH + 24, d)
    z_land = z_beach + rise * (LAND + 2.2 * noise + 0.3 * fine)
    # The town climbing from the quay round the bay, like the seats of a theatre
    bay_dist, _ = polyline_distance(u, v, H["bay"])
    town = town_share(u, v, bay_dist, d)
    z_town = QUAY_TOP + np.clip(bay_dist - WATERFRONT - 2, 0, None) * TOWN_SLOPE + 0.12 * fine
    z_land = mix(z_land, z_town, town)
    hill, _ = hill_height(u, v)
    z_land = np.maximum(z_land, hill * smoothstep(0, 30, d) + 0.4 * fine * smoothstep(5, 30, hill))
    # The castle's yard, flat
    cu, cv = CASTLE["u"], CASTLE["v"]
    yard = smoothstep(6, 0, np.maximum(np.abs(u - cu) - CASTLE["half_u"], np.abs(v - cv) - CASTLE["half_v"]))
    z_land = mix(z_land, CASTLE_Z, yard)
    z = np.where(d >= 0, z_land, z_sea)
    return z, d, town, bay_dist


def road_profile():
    """The road's height along it: the ground under it, smoothed, never going down towards the castle"""
    P = np.asarray(ROAD, float)
    lengths = np.hypot(*np.diff(P, axis=0).T)
    total = lengths.sum()
    s = np.linspace(0, total, int(total / 2) + 1)
    seg = np.searchsorted(np.cumsum(lengths), s, side="right").clip(0, len(lengths) - 1)
    t = (s - np.concatenate([[0], np.cumsum(lengths)])[seg]) / lengths[seg]
    pts = P[seg] + (P[seg + 1] - P[seg]) * t[:, None]
    z = base_heights(pts[:, 0], pts[:, 1])[0]
    z = np.maximum.accumulate(z)
    kernel = np.ones(15) / 15
    z = np.convolve(np.pad(z, 7, mode="edge"), kernel, mode="valid")
    z[-1] = CASTLE_Z
    return s, z


ROAD_S, ROAD_Z = None, None


def heights(u, v):
    """The final heights and the masks the terrain's material reads: road, paving, fields, paths"""
    global ROAD_S, ROAD_Z
    if ROAD_S is None:
        ROAD_S, ROAD_Z = road_profile()
    z, d, town, bay_dist = base_heights(u, v)
    dist, along = polyline_distance(u, v, ROAD)
    z_road = np.interp(along, ROAD_S, ROAD_Z)
    road = smoothstep(ROAD_WIDTH + 1.0, ROAD_WIDTH - 0.5, dist) * (d > 2)
    bank = smoothstep(ROAD_WIDTH + 9, ROAD_WIDTH, dist) * (d > 2)
    z = mix(z, z_road, bank * (1 - town))
    # Paving: the waterfront, the market square, the lanes, the castle's yard
    quay_dist, _ = polyline_distance(u, v, H["quay"])
    waterfront = (quay_dist < WATERFRONT) & (d > -1)
    yard = (np.abs(u - CASTLE["u"]) < CASTLE["half_u"]) & (np.abs(v - CASTLE["v"]) < CASTLE["half_v"])
    lanes = np.zeros(np.shape(u))
    for row in range(TOWN_ROWS - 1):
        middle = FIRST_ROW + (row + 0.5) * ROW_STEP
        lanes = np.maximum(lanes, smoothstep(2.8, 1.8, np.abs(bay_dist - middle)))
    for line in LANE_LINES:
        lane_dist, _ = polyline_distance(u, v, line)
        lanes = np.maximum(lanes, smoothstep(2.4, 1.4, lane_dist))
    lanes *= town > 0.5
    paved = np.maximum.reduce([waterfront.astype(float), in_square(u, v).astype(float), yard.astype(float), road,
                               lanes])
    path = np.zeros(np.shape(u))
    for line in PATHS:
        dist, _ = polyline_distance(u, v, line)
        path = np.maximum(path, smoothstep(2.6, 1.2, dist))
    path *= (d > 4) * (1 - town)
    field = np.zeros(np.shape(u))
    crop = np.zeros(np.shape(u))
    for k, (fu, fv, fw, fh) in enumerate(FIELDS):
        inside = smoothstep(1.5, 0, np.maximum(np.abs(u - fu) - fw / 2, np.abs(v - fv) - fh / 2))
        field = np.maximum(field, inside)
        crop = np.where(inside > 0, (k * 0.37) % 1, crop)
    field *= (d > 8) * (1 - road) * (1 - town)
    return z, d, dict(road=road, paved=paved, town=town, field=field, crop=crop, path=path)


# ---------------------------------------------------------------------------
# Meshes: a builder of vertices and faces with a material each, mapped flat on every face
# ---------------------------------------------------------------------------


class Builder:
    """Vertices and faces of one object, in the harbour's frame. A face's UVs are its plane's: along it level, then
    up it, in world units (so a roof's tiles run along its ridge and down its slope, a wall's courses level)"""

    def __init__(self):
        self.verts = []
        self.faces = []
        self.mats = []

    def add(self, points, mat):
        start = len(self.verts)
        self.verts.extend(tuple(map(float, p)) for p in points)
        self.faces.append(tuple(range(start, start + len(points))))
        self.mats.append(mat)

    def quad(self, a, b, c, d, mat):
        self.add((a, b, c, d), mat)

    def box(self, x, y, z0, along, across, height, angle, mat, top=None, bottom=False):
        c, s = math.cos(angle), math.sin(angle)
        corners = [(-along / 2, -across / 2), (along / 2, -across / 2), (along / 2, across / 2), (-along / 2, across / 2)]
        lo = [(x + a * c - b * s, y + a * s + b * c, z0) for a, b in corners]
        hi = [(p[0], p[1], z0 + height) for p in lo]
        for i in range(4):
            j = (i + 1) % 4
            self.quad(lo[i], lo[j], hi[j], hi[i], mat)
        if top is not False:
            self.add(hi, mat if top is None else top)
        if bottom:
            self.add(list(reversed(lo)), mat)
        return hi

    def prism(self, outline, z0, z1, mat, top=None):
        """An upright prism over a polygon (counter-clockwise), its top flat"""
        n = len(outline)
        for i in range(n):
            a, b = outline[i], outline[(i + 1) % n]
            self.quad((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1), mat)
        if top is not False:
            self.add([(p[0], p[1], z1) for p in outline], mat if top is None else top)

    def cylinder(self, x, y, z0, z1, r0, r1, mat, top=None, segments=16):
        ring0 = [(x + r0 * math.cos(a), y + r0 * math.sin(a), z0) for a in np.linspace(0, 2 * math.pi, segments, endpoint=False)]
        ring1 = [(x + r1 * math.cos(a), y + r1 * math.sin(a), z1) for a in np.linspace(0, 2 * math.pi, segments, endpoint=False)]
        for i in range(segments):
            j = (i + 1) % segments
            self.quad(ring0[i], ring0[j], ring1[j], ring1[i], mat)
        if top is not False:
            self.add(ring1, mat if top is None else top)

    def cone(self, x, y, z0, height, r, mat, segments=16):
        apex = (x, y, z0 + height)
        ring = [(x + r * math.cos(a), y + r * math.sin(a), z0) for a in np.linspace(0, 2 * math.pi, segments, endpoint=False)]
        for i in range(segments):
            self.add((ring[i], ring[(i + 1) % segments], apex), mat)

    def gable_roof(self, x, y, z, along, across, rise, angle, roof, gable, overhang=0.7):
        """A pitched roof over a house: its ridge along the house, the gables filled with the walls' material"""
        c, s = math.cos(angle), math.sin(angle)
        p = lambda a, b, h: (x + a * c - b * s, y + a * s + b * c, h)  # noqa: E731
        ha, hb = along / 2 + overhang, across / 2 + overhang
        drop = rise * overhang / (across / 2)
        r0, r1 = p(-ha, 0, z + rise), p(ha, 0, z + rise)
        self.quad(p(-ha, -hb, z - drop), p(ha, -hb, z - drop), r1, r0, roof)
        self.quad(p(ha, hb, z - drop), p(-ha, hb, z - drop), r0, r1, roof)
        # The gables, flush with the walls
        self.add((p(-along / 2, -across / 2, z), p(-along / 2, across / 2, z), p(-along / 2, 0, z + rise)), gable)
        self.add((p(along / 2, across / 2, z), p(along / 2, -across / 2, z), p(along / 2, 0, z + rise)), gable)

    def hip_roof(self, x, y, z, along, across, rise, angle, roof, overhang=0.6):
        c, s = math.cos(angle), math.sin(angle)
        p = lambda a, b, h: (x + a * c - b * s, y + a * s + b * c, h)  # noqa: E731
        ha, hb = along / 2 + overhang, across / 2 + overhang
        ridge = max(ha - hb, 0.05)
        e = [p(-ha, -hb, z), p(ha, -hb, z), p(ha, hb, z), p(-ha, hb, z)]
        r0, r1 = p(-ridge, 0, z + rise), p(ridge, 0, z + rise)
        self.quad(e[0], e[1], r1, r0, roof)
        self.quad(e[2], e[3], r0, r1, roof)
        self.add((e[1], e[2], r1), roof)
        self.add((e[3], e[0], r0), roof)

    def band(self, line, width, z0, z1, mat, top=None, closed=False):
        """A wall of some width along a polyline: a box for every leg, overlapping at the corners"""
        pts = list(line) + ([line[0]] if closed else [])
        for a, b in zip(pts[:-1], pts[1:]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            self.box((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, z0, length + width * 0.98, width, z1 - z0, angle, mat, top)

    def ribbon(self, line, width, z0, z1, mat, top=None, normals=None):
        """A wall of some width along a curved line, its sides and top unbroken round the bends"""
        P = np.asarray(line, float)
        n = normals_of(P) if normals is None else normals
        left, right = P + n * width / 2, P - n * width / 2
        for i in range(len(P) - 1):
            a, b = left[i], left[i + 1]
            self.quad((b[0], b[1], z0), (a[0], a[1], z0), (a[0], a[1], z1), (b[0], b[1], z1), mat)
            a, b = right[i], right[i + 1]
            self.quad((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1), mat)
            if top is not False:
                self.quad((right[i][0], right[i][1], z1), (right[i + 1][0], right[i + 1][1], z1),
                          (left[i + 1][0], left[i + 1][1], z1), (left[i][0], left[i][1], z1), mat if top is None else top)
        for k, (l, r) in ((0, (left[0], right[0])), (-1, (left[-1], right[-1]))):
            self.quad((l[0], l[1], z0), (r[0], r[1], z0), (r[0], r[1], z1), (l[0], l[1], z1), mat)

    def merlons(self, line, z, mat, closed=False, size=(1.3, 1.1), gap=1.2, width=0.9, offset=0.0):
        """Battlements along a wall's top: a block every size + gap, `offset` out from the line"""
        pts = list(line) + ([line[0]] if closed else [])
        for a, b in zip(pts[:-1], pts[1:]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            n = max(1, int(length / (size[0] + gap)))
            nx, ny = -math.sin(angle), math.cos(angle)
            for k in range(n):
                t = (k + 0.5) / n
                x = a[0] + (b[0] - a[0]) * t + nx * offset
                y = a[1] + (b[1] - a[1]) * t + ny * offset
                self.box(x, y, z, size[0], width, size[1], angle, mat)

    def object(self, name, materials):
        mesh = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
        mesh.clear_geometry()
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.materials.clear()
        for m in materials:
            mesh.materials.append(m)
        mesh.polygons.foreach_set("material_index", np.asarray(self.mats, np.int32))
        mesh.update()
        planar_uvs(mesh)
        obj = bpy.data.objects.get(name) or bpy.data.objects.new(name, mesh)
        obj.data = mesh
        obj.matrix_world = TURN
        return obj


def planar_uvs(mesh):
    """Every face mapped flat in its own plane, in world units: level along it, then up it"""
    uv = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    n = len(mesh.loops)
    co = np.zeros(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    loop_vert = np.zeros(n, np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vert)
    normals = np.zeros(len(mesh.polygons) * 3)
    mesh.polygons.foreach_get("normal", normals)
    normals = normals.reshape(-1, 3)
    starts = np.zeros(len(mesh.polygons), np.int32)
    totals = np.zeros(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", totals)
    face_of_loop = np.repeat(np.arange(len(mesh.polygons)), totals)
    nrm = normals[face_of_loop]
    flat = np.abs(nrm[:, 2]) > 0.97
    tangent = np.cross(np.array([0.0, 0.0, 1.0]), nrm)
    tangent[flat] = (1.0, 0.0, 0.0)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True) + 1e-12
    bitangent = np.cross(nrm, tangent)
    bitangent[flat] = (0.0, 1.0, 0.0)
    p = co[loop_vert]
    uvs = np.stack([(p * tangent).sum(1), (p * bitangent).sum(1)], 1)
    uv.data.foreach_set("uv", uvs.astype(np.float32).ravel())


# ---------------------------------------------------------------------------
# Textures and materials
# ---------------------------------------------------------------------------


def download(asset):
    """Poly Haven's 1k diffuse map of an asset, into textures/polyhaven/ (seen from this far, bumps come from it too)"""
    os.makedirs(TEX_DIR, exist_ok=True)
    path = os.path.join(TEX_DIR, f"{asset}_diff_1k.jpg")
    if os.path.exists(path):
        return path
    req = urllib.request.Request(f"https://api.polyhaven.com/files/{asset}", headers={"User-Agent": "blender-assets"})
    files = json.load(urllib.request.urlopen(req, timeout=60))
    url = files["Diffuse"]["1k"]["jpg"]["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "blender-assets"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as fh:
        fh.write(r.read())
    print("downloaded", os.path.basename(path), flush=True)
    return path


class Nodes:
    def __init__(self, mat):
        mat.use_nodes = True
        self.tree = mat.node_tree
        self.tree.nodes.clear()
        self.x = 0

    def add(self, kind, **inputs):
        node = self.tree.nodes.new(kind)
        node.location = (self.x, 0)
        self.x += 40
        for key, value in inputs.items():
            if isinstance(value, bpy.types.NodeSocket):
                self.tree.links.new(value, node.inputs[key])
            else:
                if isinstance(value, (tuple, list)) and len(value) == 3 and len(node.inputs[key].default_value) == 4:
                    value = (*value, 1)
                node.inputs[key].default_value = value
        return node

    def link(self, a, b):
        self.tree.links.new(a, b)

    def math(self, op, a, b=None, clamp=False):
        n = self.add("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                self.link(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    def mix(self, factor, a, b, blend="MIX"):
        n = self.add("ShaderNodeMix")
        n.data_type = "RGBA"
        n.blend_type = blend
        for sock, v in ((n.inputs[0], factor), (n.inputs[6], a), (n.inputs[7], b)):
            if isinstance(v, bpy.types.NodeSocket):
                self.link(v, sock)
            else:
                sock.default_value = v if not isinstance(v, (tuple, list)) else (*v[:3], 1)
        return n.outputs[2]

    def smooth(self, value, e0, e1):
        n = self.add("ShaderNodeMapRange")
        n.interpolation_type = "SMOOTHSTEP"
        self.link(value, n.inputs["Value"])
        n.inputs["From Min"].default_value = e0
        n.inputs["From Max"].default_value = e1
        return n.outputs["Result"]

    def texture(self, coords, asset, tile, tint, box=False):
        """A Poly Haven texture tiled every `tile` world units and tinted; and its brightness, for bumps"""
        mapping = self.add("ShaderNodeMapping", Vector=coords)
        mapping.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
        tex = self.add("ShaderNodeTexImage", Vector=mapping.outputs[0])
        tex.image = bpy.data.images.load(download(asset), check_existing=True)
        if box:
            # From three sides, blended: on a cliff a texture laid from above would be smeared into streaks
            tex.projection = "BOX"
            tex.projection_blend = 0.35
        color = self.mix(1.0, tex.outputs["Color"], tint, blend="MULTIPLY")
        bw = self.add("ShaderNodeRGBToBW", Color=tex.outputs["Color"])
        return color, bw.outputs[0]

    def shade(self, color, height=None, bump=0.5, rough=0.85, emit=None):
        normal = None
        if height is not None:
            b = self.add("ShaderNodeBump", Height=height)
            b.inputs["Strength"].default_value = bump
            b.inputs["Distance"].default_value = 0.2
            normal = b.outputs["Normal"]
        bsdf = self.add("ShaderNodeBsdfPrincipled", **{"Base Color": color})
        if normal is not None:
            self.link(normal, bsdf.inputs["Normal"])
        bsdf.inputs["Roughness"].default_value = rough
        if emit is not None:
            bsdf.inputs["Emission Color"].default_value = (*emit[:3], 1)
            bsdf.inputs["Emission Strength"].default_value = emit[3]
        out = self.add("ShaderNodeOutputMaterial")
        self.link(bsdf.outputs[0], out.inputs["Surface"])
        return bsdf


def new_material(name):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    return mat, Nodes(mat)


def textured(name, asset, tile, tint=(1, 1, 1), bump=0.5, rough=0.85, vary=0.0):
    """A material from a Poly Haven texture on the faces' own UVs (Builder's); `vary`: how much each object's (and
    each face's, by where it is) colour wanders, so a row of houses isn't one colour"""
    mat, n = new_material(name)
    uv = n.add("ShaderNodeTexCoord").outputs["UV"]
    color, height = n.texture(uv, asset, tile, tint)
    if vary:
        geo = n.add("ShaderNodeNewGeometry")
        noise = n.add("ShaderNodeTexNoise", Vector=geo.outputs["Position"])
        noise.inputs["Scale"].default_value = 0.08
        hsv = n.add("ShaderNodeHueSaturation", Color=color)
        n.link(n.math("ADD", n.math("MULTIPLY", noise.outputs["Fac"], vary), 1 - vary / 2), hsv.inputs["Value"])
        color = hsv.outputs["Color"]
    n.shade(color, height, bump, rough)
    return mat


def flat(name, color, rough=0.8, emit=None, metallic=0.0):
    mat, n = new_material(name)
    bsdf = n.shade(color, rough=rough, emit=emit)
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def striped(name, color, stripe=(0.9, 0.88, 0.8), width=0.9):
    """Awning cloth: stripes across it"""
    mat, n = new_material(name)
    uv = n.add("ShaderNodeTexCoord").outputs["UV"]
    sep = n.add("ShaderNodeSeparateXYZ", Vector=uv)
    wave = n.math("SINE", n.math("MULTIPLY", sep.outputs["X"], math.pi / width))
    color_out = n.mix(n.math("GREATER_THAN", wave, 0.0), color, stripe)
    n.shade(color_out, rough=0.9)
    return mat


# Colours are linear (Blender's), not sRGB: 0.2 linear is about 0.48 on screen
MATERIALS = {}


def materials():
    if MATERIALS:
        return MATERIALS
    M = MATERIALS
    M["harbour"] = textured("port_harbour_stone", "rustic_stone_wall", 5.5, (0.95, 0.93, 0.88), bump=0.7)
    M["paving"] = textured("port_paving", "cobblestone_floor_04", 4.0, (0.95, 0.92, 0.86), bump=0.6)
    M["castle_stone"] = textured("port_castle_stone", "castle_wall_slates", 6.0, (0.95, 0.95, 0.92), bump=0.7)
    M["brick"] = textured("port_brick", "castle_brick_02_red", 3.5, (1.05, 0.95, 0.9), bump=0.6, vary=0.15)
    M["white_stone"] = textured("port_white_stone", "white_sandstone_blocks_02", 4.0, (1.05, 1.03, 0.98), bump=0.5)
    M["roof"] = textured("port_roof_clay", "clay_roof_tiles_02", 3.0, (1.0, 0.9, 0.85), bump=0.8, vary=0.35)
    M["roof_dark"] = textured("port_roof_dark", "clay_roof_tiles", 3.0, (1.1, 0.72, 0.62), bump=0.8, vary=0.2)
    M["thatch"] = textured("port_thatch", "thatch_roof_angled", 4.0, (1.55, 1.25, 0.8), bump=0.9, vary=0.25)
    M["plaster"] = textured("port_plaster_white", "medieval_wall_01", 4.0, (1.0, 0.97, 0.9), bump=0.4, vary=0.18)
    M["plaster_warm"] = textured("port_plaster_warm", "yellow_plaster", 4.0, (1.15, 1.0, 0.8), bump=0.3, vary=0.2)
    M["whitewash"] = textured("port_whitewash", "whitewashed_brick", 3.0, (1.0, 0.98, 0.94), bump=0.4, vary=0.15)
    M["logs"] = textured("port_logs", "wood_trunk_wall", 3.0, (1.1, 1.0, 0.9), bump=0.8)
    M["planks"] = textured("port_planks", "weathered_planks", 3.0, (1.0, 0.95, 0.85), bump=0.6)
    M["planks_dark"] = textured("port_planks_dark", "old_planks_02", 3.0, (0.8, 0.75, 0.7), bump=0.6)
    M["barrel"] = textured("port_barrel", "wooden_barrel", 2.0, (1.0, 0.95, 0.9), bump=0.4)
    M["window"] = flat("port_window", (0.02, 0.025, 0.03), rough=0.3)
    M["door"] = flat("port_door", (0.08, 0.045, 0.02), rough=0.8)
    M["shutter_blue"] = flat("port_shutter_blue", (0.05, 0.12, 0.25))
    M["shutter_green"] = flat("port_shutter_green", (0.05, 0.16, 0.07))
    M["iron"] = flat("port_iron", (0.03, 0.03, 0.035), rough=0.5, metallic=0.6)
    M["copper"] = flat("port_copper", (0.08, 0.2, 0.15), rough=0.5, metallic=0.3)
    M["glass"] = flat("port_lamp_glass", (1.0, 0.85, 0.5), rough=0.2, emit=(1.0, 0.8, 0.4, 3.0))
    M["rope"] = flat("port_rope", (0.35, 0.27, 0.15))
    M["cloth_red"] = striped("port_awning_red", (0.55, 0.05, 0.03))
    M["cloth_blue"] = striped("port_awning_blue", (0.05, 0.12, 0.45))
    M["cloth_green"] = striped("port_awning_green", (0.06, 0.3, 0.08))
    M["cloth_yellow"] = striped("port_awning_yellow", (0.75, 0.5, 0.06))
    M["sail"] = flat("port_sail", (0.75, 0.7, 0.6), rough=0.95)
    M["goods"] = flat("port_goods", (0.6, 0.25, 0.05))
    M["greens"] = flat("port_greens", (0.1, 0.35, 0.05))
    return M


# ---------------------------------------------------------------------------
# The terrain
# ---------------------------------------------------------------------------


def material_terrain():
    mat, n = new_material("port_terrain")
    tc = n.add("ShaderNodeTexCoord")
    coords = tc.outputs["Object"]
    geo = n.add("ShaderNodeNewGeometry")
    z = n.add("ShaderNodeSeparateXYZ", Vector=geo.outputs["Position"]).outputs["Z"]
    nz = n.add("ShaderNodeSeparateXYZ", Vector=geo.outputs["Normal"]).outputs["Z"]
    noise = n.add("ShaderNodeTexNoise", Vector=coords)
    noise.inputs["Scale"].default_value = 0.05
    noise.inputs["Detail"].default_value = 6
    wobble = n.math("SUBTRACT", noise.outputs["Fac"], 0.5)

    sand, sand_h = n.texture(coords, "aerial_beach_01", 30, (1.2, 1.12, 0.95), box=True)
    land, land_h = n.texture(coords, "grass_ground", 30, (0.66, 1.1, 0.45), box=True)
    patch, _ = n.texture(coords, "aerial_grass_rock", 36, (0.8, 1.0, 0.7), box=True)
    rock, rock_h = n.texture(coords, "mossy_rock", 18, (0.95, 0.98, 0.95), box=True)
    town_ground, _ = n.texture(coords, "forrest_ground_01", 24, (1.0, 0.95, 0.85), box=True)
    paving, paving_h = n.texture(coords, "cobblestone_floor_04", 4.0, (0.95, 0.92, 0.86), box=True)
    patches = n.add("ShaderNodeTexNoise", Vector=coords)
    patches.inputs["Scale"].default_value = 0.025
    patches.inputs["Detail"].default_value = 4
    land = n.mix(n.smooth(patches.outputs["Fac"], 0.4, 0.65), land, patch)
    town = n.add("ShaderNodeAttribute")
    town.attribute_name = "town"
    land = n.mix(n.math("MULTIPLY", town.outputs["Fac"], 0.7), land, town_ground)
    # Fields: furrows across them, each its own crop's colour
    field = n.add("ShaderNodeAttribute")
    field.attribute_name = "field"
    crop = n.add("ShaderNodeAttribute")
    crop.attribute_name = "crop"
    rows = n.add("ShaderNodeTexWave", Vector=coords)
    rows.wave_type = "BANDS"
    rows.bands_direction = "X"
    rows.inputs["Scale"].default_value = 0.06
    rows.inputs["Distortion"].default_value = 0.3
    ramp = n.add("ShaderNodeValToRGB", Fac=crop.outputs["Fac"])
    stops = ramp.color_ramp.elements
    stops[0].color = (0.22, 0.16, 0.05, 1)
    stops[1].color = (0.1, 0.17, 0.03, 1)
    stops.new(0.5).color = (0.3, 0.24, 0.07, 1)
    furrow = n.mix(n.smooth(rows.outputs["Fac"], 0.3, 0.7), ramp.outputs["Color"],
                   n.mix(1.0, ramp.outputs["Color"], (0.7, 0.62, 0.5), blend="MULTIPLY"))
    land = n.mix(field.outputs["Fac"], land, n.mix(0.25, furrow, land))

    zb = n.math("ADD", z, n.math("MULTIPLY", wobble, 2.4))
    land_share = n.smooth(zb, BEACH_HEIGHT - 0.2, BEACH_HEIGHT + 1.4)
    steep = n.smooth(nz, 0.8, 0.64)
    upper = n.mix(steep, land, rock)
    color = n.mix(land_share, sand, upper)
    path = n.add("ShaderNodeAttribute")
    path.attribute_name = "path"
    color = n.mix(n.math("MULTIPLY", path.outputs["Fac"], 0.85), color,
                  n.mix(1.0, town_ground, (0.85, 0.78, 0.65), blend="MULTIPLY"))
    paved = n.add("ShaderNodeAttribute")
    paved.attribute_name = "paved"
    paved_share = n.math("MULTIPLY", paved.outputs["Fac"], n.math("SUBTRACT", 1.0, steep), clamp=True)
    color = n.mix(paved_share, color, paving)
    wet = n.smooth(z, 0.5, 0.0)
    color = n.mix(wet, color, n.mix(1.0, color, (0.8, 0.77, 0.72), blend="MULTIPLY"))

    upper_h = n.math("ADD", n.math("MULTIPLY", land_h, n.math("SUBTRACT", 1.0, steep)), n.math("MULTIPLY", rock_h, steep))
    height = n.math("ADD", n.math("MULTIPLY", sand_h, n.math("SUBTRACT", 1.0, land_share)),
                    n.math("MULTIPLY", upper_h, land_share))
    height = n.math("ADD", n.math("MULTIPLY", height, n.math("SUBTRACT", 1.0, paved_share)),
                    n.math("MULTIPLY", paving_h, paved_share))
    bump = n.add("ShaderNodeBump", Height=height)
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.3
    lit = n.add("ShaderNodeBsdfPrincipled", **{"Base Color": color, "Normal": bump.outputs["Normal"]})
    lit.inputs["Roughness"].default_value = 0.9

    # Under the water: the sea floor seen through it, unlit (the shadows on the water come from their own render),
    # fading into the game's sea with depth; a broken line of surf at the waterline
    depth = n.math("MULTIPLY", z, -1)
    under = n.smooth(depth, 0.0, 0.5)
    murk = n.smooth(depth, 0.2, DEPTH * 0.8)
    seabed = n.mix(1.0, sand, (0.62, 0.66, 0.6), blend="MULTIPLY")
    water_color = (0.02, 0.2, 0.24)
    seafloor = n.mix(murk, seabed, water_color)
    glow = n.add("ShaderNodeEmission", Color=seafloor)
    glow.inputs["Strength"].default_value = 1.0
    foam_noise = n.add("ShaderNodeTexNoise", Vector=coords)
    foam_noise.inputs["Scale"].default_value = 0.35
    foam_noise.inputs["Detail"].default_value = 5
    band = n.math("MULTIPLY", n.smooth(z, -0.4, -0.15), n.smooth(z, 0.02, -0.08))
    foam = n.math("MULTIPLY", band, n.smooth(foam_noise.outputs["Fac"], 0.5, 0.7), clamp=True)
    foam = n.math("MULTIPLY", foam, 0.55)
    foam_shader = n.add("ShaderNodeEmission", Color=(0.85, 0.9, 0.9, 1))
    under_shader = n.add("ShaderNodeMixShader", Fac=foam)
    n.link(glow.outputs[0], under_shader.inputs[1])
    n.link(foam_shader.outputs[0], under_shader.inputs[2])
    surface = n.add("ShaderNodeMixShader", Fac=under)
    n.link(lit.outputs[0], surface.inputs[1])
    n.link(under_shader.outputs[0], surface.inputs[2])
    # Solid on land and in the shallows, fading out over the deeper sea floor
    alpha = n.math("SUBTRACT", 1.0, n.smooth(depth, 0.6, BASIN_DEPTH - 0.4))
    alpha = n.math("MAXIMUM", alpha, foam)
    transparent = n.add("ShaderNodeBsdfTransparent")
    final = n.add("ShaderNodeMixShader", Fac=alpha)
    n.link(transparent.outputs[0], final.inputs[1])
    n.link(surface.outputs[0], final.inputs[2])
    out = n.add("ShaderNodeOutputMaterial")
    n.link(final.outputs[0], out.inputs["Surface"])
    return mat


def build_terrain(scene):
    coast = np.asarray(H["coast"])
    lo = coast.min(axis=0) - SHELF - 4
    hi = coast.max(axis=0) + SHELF + 4
    us = np.arange(lo[0], hi[0] + GRID, GRID)
    vs = np.arange(lo[1], hi[1] + GRID, GRID)
    gu, gv = np.meshgrid(us, vs)
    z, d, masks = heights(gu, gv)
    nv, nu = gu.shape
    verts = np.stack([gu, gv, z], -1).reshape(-1, 3)
    idx = np.arange(nu * nv).reshape(nv, nu)
    quads = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], -1).reshape(-1, 4)
    d_walls = signed_distance(gu, gv, H["coast"])
    keep = d_walls.reshape(-1)[quads].max(axis=1) > -SHELF
    quads = quads[keep]
    used = np.unique(quads)
    remap = np.full(len(verts), -1)
    remap[used] = np.arange(len(used))
    mesh = bpy.data.meshes.get("PortTerrain") or bpy.data.meshes.new("PortTerrain")
    mesh.clear_geometry()
    v = verts[used]
    f = remap[quads]
    mesh.vertices.add(len(v))
    mesh.vertices.foreach_set("co", v.astype(np.float32).ravel())
    mesh.loops.add(len(f) * 4)
    mesh.loops.foreach_set("vertex_index", f.astype(np.int32).ravel())
    mesh.polygons.add(len(f))
    mesh.polygons.foreach_set("loop_start", (np.arange(len(f)) * 4).astype(np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(len(f), 4, np.int32))
    mesh.update(calc_edges=True)
    mesh.polygons.foreach_set("use_smooth", np.ones(len(f), bool))
    for name in ("town", "paved", "road", "field", "crop", "path"):
        attr = mesh.attributes.get(name) or mesh.attributes.new(name, "FLOAT", "POINT")
        attr.data.foreach_set("value", masks[name].reshape(-1)[used].astype(np.float32))
    mesh.materials.clear()
    mesh.materials.append(material_terrain())
    obj = bpy.data.objects.get("PortTerrain") or bpy.data.objects.new("PortTerrain", mesh)
    obj.matrix_world = TURN
    link(scene, obj)
    return obj, v


def ground_z(u, v):
    z, _, _ = heights(np.atleast_1d(np.asarray(u, float)), np.atleast_1d(np.asarray(v, float)))
    return z


# ---------------------------------------------------------------------------
# The harbour: walls, quay, lighthouse, the flag's bastion, jetties, boats, the crane
# ---------------------------------------------------------------------------

LAMP = {}  # where the game draws the lighthouse's lamp and the flag (harbour frame)


def build_harbour(scene, rng):
    M = materials()
    mats = [M["harbour"], M["paving"], M["white_stone"], M["iron"], M["glass"], M["copper"], M["planks"],
            M["planks_dark"], M["barrel"], M["rope"], M["window"], M["door"], M["brick"], M["roof_dark"]]
    HARB, PAVE, WHITE, IRON, GLASS, COPPER, PLANKS, DARK, BARREL, ROPE, WIN, DOOR, BRICK, ROOF = range(len(mats))
    b = Builder()
    top = WALL_HEIGHT
    rocks = []  # the rubble heaped along the walls' sea side: (u, v, size)
    for wall in H["walls"]:
        line, sea = wall["line"], wall["sea"]
        b.ribbon(line, WALL_THICKNESS, UNDER, top, HARB, PAVE)
        hx, hy = line[-1]
        b.cylinder(hx, hy, UNDER, top, WALL_THICKNESS / 2, WALL_THICKNESS / 2, HARB, PAVE, segments=24)
        # Where the wall stands in the water (it starts back on the land)
        afloat = np.nonzero(signed_distance(line[:, 0], line[:, 1], H["land"]) < -3)[0]
        first = int(afloat[0])
        # A parapet along its sea side, bollards along the basin's
        b.ribbon(line[first:] + sea[first:] * (WALL_THICKNESS / 2 - 0.9), 1.8, top, top + 1.4, HARB)
        for i in afloat[2:-1:3]:
            q = line[i] - sea[i] * (WALL_THICKNESS / 2 - 1.3)
            b.cylinder(q[0], q[1], top, top + 0.9, 0.45, 0.4, IRON, segments=8)
        # Rubble along its sea side and round its head, against the waves
        s = lengths_of(line)
        for at in np.arange(s[first], s[-1], 2.6):
            p, _ = along_line(line, sea, at / s[-1], WALL_THICKNESS / 2 + rng.uniform(0.2, 2.4))
            rocks.append((p[0], p[1], rng.uniform(0.4, 0.8)))
        d = line[-1] - line[-2]
        heading = math.atan2(d[1], d[0])
        for a in np.linspace(-1.5, 1.5, 9):
            r = WALL_THICKNESS / 2 + rng.uniform(0.3, 2.2)
            rocks.append((hx + math.cos(heading + a) * r, hy + math.sin(heading + a) * r, rng.uniform(0.5, 0.85)))
    # The quay round the back of the bay: an embankment of big stones, paved on top, bollards along its edge
    quay, inward_ = H["quay"], H["quay_inland"]
    b.ribbon(quay + inward_ * 1.2, 4.4, UNDER, QUAY_TOP + 0.05, HARB, PAVE)
    length = lengths_of(quay)[-1]
    for share in np.arange(0.06, 0.97, 22 / length):
        p, _ = along_line(quay, inward_, share, 0.7)
        b.cylinder(p[0], p[1], QUAY_TOP + 0.05, QUAY_TOP + 0.95, 0.45, 0.4, IRON, segments=8)
    # Two wooden jetties out into the bay, rowing boats moored at them
    boats = Builder()
    for k, share in enumerate((0.24, 0.79)):
        p0, _ = along_line(quay, inward_, share)
        out = -inward_[int(round(share * (len(quay) - 1)))]
        side = np.array([-out[1], out[0]])
        angle = math.atan2(out[1], out[0])
        jetty = 26
        centre = p0 + out * jetty / 2
        b.box(centre[0], centre[1], 1.2, jetty, 4.2, 0.45, angle, PLANKS)
        for j in range(int(jetty / 4) + 1):
            for w in (-1.9, 1.9):
                q = p0 + out * (j * 4 + 0.5) + side * w
                b.cylinder(q[0], q[1], UNDER, 1.3, 0.28, 0.28, DARK, segments=6)
        for j, (along, w) in enumerate(((9, 4.4), (18, -4.4), (14, 4.4) if k else (21, 4.4))):
            q = p0 + out * along + side * w
            rowing_boat(boats, q[0], q[1], 0.15, angle + rng.uniform(-0.08, 0.08), j % 2)
    obj = boats.object("PortBoats", [M["planks_dark"], M["planks"]])
    link(scene, obj)
    # The crane on the quay: a post, a jib out over the water, a rope and a crate hanging from it
    p, _ = along_line(quay, inward_, 0.62, 4)
    out = -inward_[int(round(0.62 * (len(quay) - 1)))]
    angle = math.atan2(out[1], out[0])
    b.box(p[0], p[1], QUAY_TOP, 1.0, 1.0, 11, angle, DARK)
    q = p + out * 4
    b.box(q[0], q[1], QUAY_TOP + 10.2, 9.5, 0.7, 0.7, angle, DARK)
    q = p + out * 2
    b.box(q[0], q[1], QUAY_TOP + 7.5, 5.0, 0.5, 0.5, angle, DARK)
    q = p + out * 8.4
    b.box(q[0], q[1], QUAY_TOP + 5.4, 0.12, 0.12, 4.8, 0, ROPE)
    b.box(q[0], q[1], QUAY_TOP + 3.6, 2.0, 2.0, 1.8, 0.3, PLANKS)
    # Crates, barrels and sacks along the waterfront, clear of the square, the jetties and the crane
    for _ in range(34):
        share = rng.uniform(0.04, 0.96)
        if abs(share - 0.5) < 0.14 or min(abs(share - 0.24), abs(share - 0.79), abs(share - 0.62)) < 0.03:
            continue
        p, angle = along_line(quay, inward_, share, rng.uniform(3, WATERFRONT - 2.5))
        if rng.uniform() < 0.5:
            for j in range(int(rng.integers(1, 4))):
                b.cylinder(p[0] + math.cos(angle) * j * 1.5, p[1] + math.sin(angle) * j * 1.5, QUAY_TOP, QUAY_TOP + 1.6,
                           0.65, 0.65, BARREL, segments=10)
        else:
            size = rng.uniform(1.2, 2.0)
            b.box(p[0], p[1], QUAY_TOP, size, size, size, rng.uniform(0, 1), PLANKS)
            if rng.uniform() < 0.5:
                b.box(p[0] + 0.2, p[1], QUAY_TOP + size, size * 0.8, size * 0.8, size * 0.8, rng.uniform(0, 1), PLANKS)
    # The lighthouse on the long wall's head: white stone, its lamp lit
    lx, ly = H["walls"][0]["line"][-1]
    b.cylinder(lx, ly, top - 0.5, top + 24, 6.0, 4.6, WHITE, segments=20)
    b.cylinder(lx, ly, top + 24, top + 25, 6.2, 6.2, WHITE, segments=20)  # the gallery
    b.cylinder(lx, ly, top + 25, top + 25.8, 6.2, 6.2, IRON, top=False, segments=20)  # its railing
    b.cylinder(lx, ly, top + 25, top + 29, 3.0, 3.0, GLASS, segments=12)  # the lantern
    b.cylinder(lx, ly, top + 29, top + 29.4, 3.5, 3.5, COPPER, segments=12)
    b.cone(lx, ly, top + 29.4, 2.6, 3.5, COPPER, segments=12)
    for k, h in enumerate((top + 5, top + 12, top + 19)):
        a = -math.pi / 2 - 0.5 + k * 0.4
        b.box(lx + math.cos(a) * (5.6 - k * 0.45), ly + math.sin(a) * (5.6 - k * 0.45), h, 0.9, 0.3, 1.6, a + math.pi / 2, WIN)
    b.box(lx, ly - 5.9, top, 1.6, 0.3, 2.6, 0, DOOR)
    LAMP["lamp"] = (lx, ly, top + 27)
    # Cannons along the long wall towards its head, looking out to sea
    line, sea = H["walls"][0]["line"], H["walls"][0]["sea"]
    for share in (0.74, 0.8, 0.86):
        p, _ = along_line(line, sea, share, 3.2)
        out = along_line(line, sea, share, 1.0)[0] - along_line(line, sea, share, 0.0)[0]
        angle = math.atan2(out[1], out[0])
        b.box(p[0], p[1], top, 1.5, 2.2, 0.8, angle + math.pi / 2, DARK)
        q = p + out * 1.3
        b.box(q[0], q[1], top + 0.8, 3.0, 0.7, 0.7, angle, IRON)
    # The short wall's head: a round bastion of red brick on a stone foot, a flagstaff and two cannons
    fx, fy = H["walls"][1]["line"][-1]
    b.cylinder(fx, fy, top - 0.5, top + 3, 7.0, 6.8, HARB, segments=20)
    b.cylinder(fx, fy, top + 3, top + 7, 6.8, 6.6, BRICK, PAVE, segments=20)
    ring = [(fx + 6.2 * math.cos(a), fy + 6.2 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 18, endpoint=False)]
    b.merlons(ring, top + 7, BRICK, closed=True, size=(1.4, 1.2), gap=1.0, width=0.9)
    b.cylinder(fx, fy, top + 7, top + 23, 0.4, 0.3, DARK, segments=8)
    LAMP["flag"] = (fx, fy, top + 23)
    for a in (-2.2, -1.2):
        cx_, cy_ = fx + math.cos(a) * 3.6, fy + math.sin(a) * 3.6
        b.box(cx_, cy_, top + 7, 2.2, 1.5, 0.8, a, DARK)
        b.cylinder(cx_ + math.cos(a) * 0.4, cy_ + math.sin(a) * 0.4, top + 7.8, top + 8.3, 0.45, 0.45, IRON, segments=8)
        b.box(cx_ + math.cos(a) * 1.4, cy_ + math.sin(a) * 1.4, top + 7.8, 3.0, 0.7, 0.7, a, IRON)
    obj = b.object("PortHarbour", mats)
    link(scene, obj)
    for k, (u, v, size) in enumerate(rocks):
        rock = bpy.data.objects.new(f"PortRubble_{k}", plant_mesh("rock", k % 3))
        rock.location = TURN @ Vector((u, v, -0.9 + rng.uniform(-0.3, 0.3)))
        rock.rotation_euler = (rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), rng.uniform(0, 2 * math.pi))
        rock.scale = (size * rng.uniform(0.9, 1.3), size * rng.uniform(0.9, 1.3), size)
        link(scene, rock)


def rowing_boat(b, x, y, z, angle, mat, length=5.2, beam=1.8, depth=0.9, upturned=False):
    """A small open boat: its sides as a ring of quads round a pointed outline, a floor, two thwarts"""
    c, s = math.cos(angle), math.sin(angle)
    p = lambda a, w, h: (x + a * c - w * s, y + a * s + w * c, h)  # noqa: E731
    stations = np.linspace(-0.5, 0.5, 9)
    half = [beam / 2 * (1 - (2 * t) ** 2) ** 0.6 + 0.02 for t in stations]
    rim = [p(t * length, h, z + depth) for t, h in zip(stations, half)] + \
          [p(t * length, -h, z + depth) for t, h in zip(stations[::-1], half[::-1])]
    keel = [p(t * length * 0.92, h * 0.55, z) for t, h in zip(stations, half)] + \
           [p(t * length * 0.92, -h * 0.55, z) for t, h in zip(stations[::-1], half[::-1])]
    if upturned:
        rim, keel = [(q[0], q[1], z) for q in rim], [(q[0], q[1], z + depth) for q in keel]
    n = len(rim)
    for i in range(n):
        j = (i + 1) % n
        b.quad(keel[i], keel[j], rim[j], rim[i], mat)
    b.add(list(reversed(keel)) if not upturned else keel, mat)
    if not upturned:
        for t in (-0.12, 0.18):
            b.box(x + t * length * c, y + t * length * s, z + depth * 0.6, 0.35, beam * 0.9, 0.12, angle, 1 - mat)


# ---------------------------------------------------------------------------
# The town: houses in rows up from the quay, the market square, the tavern, the fishermen's huts
# ---------------------------------------------------------------------------

FOOTPRINTS = []  # (u, v, radius) of everything built on the land: no trees there


def house(b, x, y, along, across, storeys, angle, walls, roof, rng, M, z=None, chimney=True, front=-1):
    """A house on the ground at x, y: walls of one or two storeys, windows and a door on the long sides, a pitched
    roof along it, maybe a chimney. `front`: which long side faces the street (-1 the camera's)"""
    if z is None:
        c, s = math.cos(angle), math.sin(angle)
        corners = [(x + a * c - w * s, y + a * s + w * c) for a in (-along / 2, along / 2) for w in (-across / 2, across / 2)]
        zs = ground_z([p[0] for p in corners], [p[1] for p in corners])
        z, base = float(zs.max()), float(zs.min())
    else:
        base = z
    storey = 3.3
    height = storeys * storey + 0.6
    b.box(x, y, base - 1.0, along + 0.3, across + 0.3, z - base + 1.4, angle, M["foot"], top=False)
    b.box(x, y, z, along, across, height, angle, walls)
    rise = across * rng.uniform(0.42, 0.62)
    b.gable_roof(x, y, z + height, along, across, rise, angle, roof, walls)
    c, s = math.cos(angle), math.sin(angle)
    shutters = M["shutter_blue"] if rng.uniform() < 0.5 else M["shutter_green"]
    for side in (-1, 1):
        nx, ny = -s * side, c * side
        off = across / 2 + 0.06
        n = max(1, int(along / 3.4))
        door = int(rng.integers(0, n)) if side == front else -1
        for k in range(n):
            t = (k + 0.5) / n - 0.5
            wx, wy = x + c * t * along + nx * off, y + s * t * along + ny * off
            for f in range(storeys):
                if f == 0 and k == door:
                    b.box(wx, wy, z, 1.5, 0.12, 2.3, angle, M["door"])
                    continue
                if rng.uniform() < 0.12:
                    continue
                zz = z + f * storey + 1.25
                b.box(wx, wy, zz, 1.0, 0.12, 1.35, angle, M["window"])
                if rng.uniform() < 0.6:
                    for d in (-0.8, 0.8):
                        b.box(wx + c * d, wy + s * d, zz, 0.55, 0.14, 1.35, angle, shutters)
    if chimney and rng.uniform() < 0.75:
        t = rng.choice([-0.3, 0.3])
        b.box(x + c * t * along, y + s * t * along, z + height + rise * 0.4, 1.1, 1.1, rise * 0.75 + 1.2, angle, M["foot"])
    FOOTPRINTS.append((x, y, max(along, across) * 0.6 + 2))
    return z


def build_town(scene, rng):
    M = dict(materials())
    M["foot"] = M["harbour"]
    order = list(dict.fromkeys([M["plaster"], M["plaster_warm"], M["whitewash"], M["roof"], M["roof_dark"],
                                M["window"], M["door"], M["shutter_blue"], M["shutter_green"],
                                M["harbour"], M["planks"], M["sail"], M["thatch"], M["logs"],
                                M["cloth_red"], M["cloth_blue"], M["cloth_green"], M["cloth_yellow"],
                                M["goods"], M["greens"], M["barrel"], M["iron"], M["planks_dark"]]))
    index = {m.name: i for i, m in enumerate(order)}
    I = {k: index[m.name] for k, m in M.items() if m.name in index}  # noqa: E741
    walls = [I["plaster"], I["plaster"], I["plaster_warm"], I["whitewash"]]
    roofs = [I["roof"], I["roof"], I["roof"], I["roof_dark"]]
    b = Builder()
    bay, inland = H["bay"], H["inland"]

    def free(u, v, r):
        here = (np.array([u]), np.array([v]))
        if polyline_distance(*here, ROAD)[0][0] < ROAD_WIDTH + r * 0.7:
            return False
        if any(polyline_distance(*here, lane)[0][0] < 2.2 + r * 0.6 for lane in LANE_LINES):
            return False
        if in_square(u, v, r * 0.6)[()] or abs(u) > TOWN_WIDTH:
            return False
        d = signed_distance(*here, H["land"])[0]
        bay_dist = polyline_distance(*here, bay)[0][0]
        if d < r + 3 or town_share(np.array([u]), np.array([v]), bay_dist, d)[0] < 0.5:
            return False
        # Not on the mount's steep face
        if hill_height(*here)[0][0] > 14:
            return False
        return all(math.hypot(u - x, v - y) > r + rr - 1.5 for x, y, rr in FOOTPRINTS)

    # The church up on the third row, its nave up the slope, its tower looking down on the harbour
    p, _ = along_line(bay, inland, 0.7, FIRST_ROW + 2 * ROW_STEP + 4)
    n = inland[int(round(0.7 * (len(bay) - 1)))]
    church(b, p[0], p[1], math.atan2(n[1], n[0]), I)
    # The tavern and the harbour master's: big houses on the waterfront either side of the square
    for k, (share, wall, roof) in enumerate(((0.37, I["whitewash"], I["roof_dark"]),
                                             (0.63, I["plaster_warm"], I["roof"]))):
        p, angle = along_line(H["quay"], H["quay_inland"], share, FIRST_ROW - 0.5)
        house(b, p[0], p[1], 17, 11, 2, angle, wall, roof, rng, I)
        if k == 0:
            # The tavern's sign, hanging out over the waterfront
            out = -H["quay_inland"][int(round(share * (len(H["quay"]) - 1)))]
            q = p + out * 6.2
            z = float(ground_z(q[0], q[1])[0])
            b.box(q[0], q[1], z + 4.2, 0.2, 1.4, 0.2, angle, I["iron"])
            q = p + out * 6.9
            b.box(q[0], q[1], z + 2.6, 1.6, 0.15, 1.2, angle, I["planks_dark"])
    # Rows of houses round the bay like the seats of a theatre, each a little longer than the one below, the houses
    # along it facing the water
    for row in range(TOWN_ROWS):
        depth = FIRST_ROW + row * ROW_STEP
        curve = bay + inland * depth
        total = lengths_of(curve)[-1]
        pos = rng.uniform(0, 4)
        while pos < total:
            along = rng.uniform(9, 15)
            across = rng.uniform(8, 10.5)
            p, angle = along_line(curve, inland, (pos + along / 2) / total, rng.uniform(-1.2, 1.2))
            r = max(along, across) / 2
            if free(p[0], p[1], r) and rng.uniform() > 0.05:  # now and then a garden instead
                storeys = 2 if (row < 3 and rng.uniform() < 0.7) or rng.uniform() < 0.3 else 1
                # Thatch on the cottages at the edge of the town
                outskirts = row >= 3 and abs(p[0]) > TOWN_WIDTH - 45 and rng.uniform() < 0.6
                house(b, p[0], p[1], along, across, storeys, angle + rng.uniform(-0.06, 0.06), int(rng.choice(walls)),
                      I["thatch"] if outskirts else int(rng.choice(roofs)), rng, I)
            pos += along + rng.uniform(1.0, 3.5) + (rng.uniform(4, 8) if rng.uniform() < 0.12 else 0)
    # The market square: stalls with striped awnings round a well
    su, sv, sa = SQUARE["u"], SQUARE["v"], SQUARE["angle"]
    ca, sn = math.cos(sa), math.sin(sa)
    zq = float(ground_z(su, sv)[0])
    b.cylinder(su, sv, zq, zq + 1.0, 2.0, 2.0, I["harbour"], segments=14)
    b.cylinder(su, sv, zq + 1.0, zq + 1.05, 1.5, 1.5, I["window"], top=True, segments=14)
    for k in (-1, 1):
        b.box(su + k * 1.6 * ca, sv + k * 1.6 * sn, zq + 1.0, 0.25, 0.25, 2.4, 0, I["planks_dark"])
    b.box(su, sv, zq + 3.3, 3.6, 0.3, 0.3, sa, I["planks_dark"])
    cloths = [I["cloth_red"], I["cloth_blue"], I["cloth_yellow"], I["cloth_green"]]
    stalls = [(-15, -7), (-5, -8), (5, -8), (15, -7), (-18, 5), (18, 5), (-8, 8), (8, 8)]
    for k, (du, dv) in enumerate(stalls):
        x, y = su + du * ca - dv * sn, sv + du * sn + dv * ca
        z = float(ground_z(x, y)[0])
        angle = math.atan2(sv - y, su - x) + math.pi / 2  # the counter faces the well
        b.box(x, y, z, 3.2, 1.6, 1.0, angle, I["planks"])
        b.box(x, y, z + 1.0, 2.8, 1.2, 0.3, angle, I["goods"] if k % 2 else I["greens"])
        c, s = math.cos(angle), math.sin(angle)
        nx, ny = -s, c
        for a in (-1.5, 1.5):
            for w in (-0.9, 1.4):
                b.box(x + c * a + nx * w, y + s * a + ny * w, z, 0.15, 0.15, 2.6 if w > 0 else 2.2, angle,
                      I["planks_dark"])
        p = lambda a, w, h: (x + c * a + nx * w, y + s * a + ny * w, h)  # noqa: E731
        b.quad(p(-1.8, 1.7, z + 2.65), p(1.8, 1.7, z + 2.65), p(1.8, -1.3, z + 2.15), p(-1.8, -1.3, z + 2.15),
               cloths[k % len(cloths)])
        for j in range(int(rng.integers(1, 3))):
            b.cylinder(x + nx * 2 + c * (j - 0.5) * 1.6, y + ny * 2 + s * (j - 0.5) * 1.6, z, z + 1.4, 0.55, 0.55,
                       I["barrel"], segments=8)
    FOOTPRINTS.append((su, sv, max(SQUARE_SIZE) / 2))
    obj = b.object("PortTown", order)
    link(scene, obj)


def church(b, x, y, angle, I):
    """A whitewashed church: its nave along `angle` (up the slope), its stone tower and spire at the front, below"""
    c, s = math.cos(angle), math.sin(angle)
    P = lambda a, w: (x + a * c - w * s, y + a * s + w * c)  # noqa: E731
    corners = [P(a, w) for a in (-19, 12) for w in (-6, 6)]
    zs = ground_z([q[0] for q in corners], [q[1] for q in corners])
    z, base = float(zs.max()), float(zs.min())
    b.box(x, y, base - 1, 26, 12, z - base + 1.4, angle, I["harbour"], top=False)
    b.box(x, y, z, 24, 11, 9, angle, I["whitewash"])
    b.gable_roof(x, y, z + 9, 24, 11, 6.5, angle, I["roof_dark"], I["whitewash"])
    for k in range(-2, 3):
        for side in (-1, 1):
            q = P(k * 4.4, side * 5.56)
            b.box(q[0], q[1], z + 2.5, 1.1, 0.12, 4.0, angle, I["window"])
    tx, ty = P(-15, 0)
    b.box(tx, ty, base - 1, 7.5, 7.5, z - base + 1, angle, I["harbour"], top=False)
    b.box(tx, ty, z, 7, 7, 21, angle, I["harbour"])
    q = P(-18.56, 0)
    b.box(q[0], q[1], z, 0.12, 1.8, 3.2, angle, I["door"])
    for a, w in ((-3.56, 0), (3.56, 0), (0, -3.56), (0, 3.56)):
        q = P(-15 + a, w)
        b.box(q[0], q[1], z + 16, 0.12 if a else 1.4, 1.4 if a else 0.12, 2.6, angle, I["window"])
    b.cone(tx, ty, z + 21, 12, 4.9, I["roof_dark"], segments=8)
    FOOTPRINTS.append((*P(-3, 0), 17))


def coast_point(u_target, side):
    """The point of the land's coast at u (on the near, harbour side of the island), and its outward normal"""
    land = np.asarray(H["land"])
    best = None
    for (ax, ay), (bx, by) in zip(land, np.roll(land, -1, 0)):
        if (ax - u_target) * (bx - u_target) <= 0 and ax != bx and min(ay, by) < 0:
            t = (u_target - ax) / (bx - ax)
            y = ay + t * (by - ay)
            if best is None or y < best[1]:
                n = np.array([by - ay, -(bx - ax)], float)
                n /= np.linalg.norm(n)
                if n[1] > 0:
                    n = -n
                best = (u_target, y, n)
    return best


def build_shore(scene, rng):
    """Outside the walls: the shipyard on the right beach, fishermen's huts on the left, boats drawn up, the windmill"""
    M = dict(materials())
    M["foot"] = M["harbour"]
    order = [M["planks"], M["planks_dark"], M["thatch"], M["logs"], M["sail"], M["window"], M["door"], M["harbour"],
             M["shutter_blue"], M["shutter_green"], M["rope"], M["plaster"]]
    I = {k: order.index(m) for k, m in M.items() if m in order}  # noqa: E741
    b = Builder()
    # The shipyard: a slipway down the beach with a hull being built on it, a shed and stacks of timber
    u0 = 168
    cu, cv, n = coast_point(u0, 1)
    down = np.array([n[0], n[1]])
    angle = math.atan2(down[1], down[0])
    along = np.array([-down[1], down[0]])
    start = np.array([cu, cv]) - down * 30
    length = 40
    zs = ground_z(start[0], start[1])[0]
    for k in range(int(length / 2.2)):
        p = start + down * (k * 2.2)
        z = float(zs - (zs + 1.2) * k * 2.2 / length)
        b.box(p[0], p[1], z - 0.4, 0.5, 7.5, 0.5, angle + math.pi / 2, I["planks_dark"])
    mid = start + down * 13
    zk = float(ground_z(mid[0], mid[1])[0]) + 0.6
    keel_angle = angle
    b.box(mid[0], mid[1], zk, 22, 0.6, 0.7, keel_angle, I["planks_dark"])
    for k in range(-5, 6):
        t = k / 5.5
        p = mid + down * (t * 10)
        half = 3.4 * (1 - t * t) ** 0.5 + 0.3
        for side in (-1, 1):
            q0 = p + along * side * 0.3
            q1 = p + along * side * half
            q2 = p + along * side * (half * 0.95)
            b.quad((q0[0], q0[1], zk + 0.5), (q1[0], q1[1], zk + 2.2), (q1[0], q1[1], zk + 2.6),
                   (q0[0], q0[1], zk + 0.9), I["planks"])
            b.box(q2[0], q2[1], zk + 2.2, 0.35, 0.35, 3.2, keel_angle, I["planks"])
    # Planks on the lower part of the hull
    for side in (-1, 1):
        for row in range(3):
            pts = []
            for k in range(-5, 6):
                t = k / 5.5
                half = (3.4 * (1 - t * t) ** 0.5 + 0.3) * (0.55 + row * 0.15)
                p = mid + down * (t * 10) + along * side * half
                pts.append((p[0], p[1], zk + 1.0 + row * 0.7))
            for a, c in zip(pts[:-1], pts[1:]):
                if row == 2 and abs(a[0] - mid[0]) + abs(a[1] - mid[1]) < 5:
                    continue
                b.quad(a, c, (c[0], c[1], c[2] + 0.6), (a[0], a[1], a[2] + 0.6), I["planks"])
    for k in range(-4, 5, 2):
        p = mid + down * (k * 2.2) + along * 6.2
        b.box(p[0], p[1], float(ground_z(p[0], p[1])[0]) - 0.5, 0.4, 0.4, 9, angle, I["planks_dark"])
    shed = start + down * 2 - along * 14
    house(b, shed[0], shed[1], 14, 8, 1, angle + math.pi / 2, I["planks"], I["thatch"], rng, I, chimney=False)
    for k in range(3):
        p = start + along * (11 + k * 2.6) + down * 2
        z = float(ground_z(p[0], p[1])[0])
        for j in range(3 - k % 2):
            b.cylinder(p[0], p[1], z + j * 0.5, z + j * 0.5 + 0.5, 0.25, 0.25, I["planks_dark"], segments=6)
            b.box(p[0], p[1], z + j * 0.5, 8, 0.5, 0.5, angle + math.pi / 2, I["planks"])
    FOOTPRINTS.append((mid[0], mid[1], 18))
    FOOTPRINTS.append((shed[0], shed[1], 10))
    # Fishermen's huts on the left beach: log walls, thatched roofs, boats drawn up on the sand
    for k, u in enumerate((-150, -172, -196, -136)):
        cu, cv, n = coast_point(u, -1)
        inland = -np.array([n[0], n[1]])
        p = np.array([cu, cv]) + inland * (BEACH_WIDTH + 10 + (k % 2) * 9)
        ang = math.atan2(inland[1], inland[0]) + math.pi / 2 + rng.uniform(-0.2, 0.2)
        house(b, p[0], p[1], rng.uniform(8, 10), rng.uniform(6, 7), 1, ang, I["logs"], I["thatch"], rng, I)
        q = np.array([cu, cv]) + inland * 3.5 + np.array([n[1], -n[0]]) * rng.uniform(-6, 6)
        zq = float(ground_z(q[0], q[1])[0])
        rowing_boat(b, q[0], q[1], zq + 0.05, math.atan2(inland[1], inland[0]) + rng.uniform(-0.4, 0.4),
                    I["planks_dark"], upturned=k % 2 == 1)
    # Drying racks for the nets
    for k in range(2):
        cu, cv, n = coast_point(-160 - k * 22, -1)
        inland = -np.array([n[0], n[1]])
        p = np.array([cu, cv]) + inland * 9
        side = np.array([n[1], -n[0]])
        z = float(ground_z(p[0], p[1])[0])
        a, c = p - side * 3, p + side * 3
        for q in (a, c):
            b.box(q[0], q[1], z, 0.25, 0.25, 2.6, 0, I["planks_dark"])
        ang = math.atan2(side[1], side[0])
        b.quad((a[0], a[1], z + 2.5), (c[0], c[1], z + 2.5), (c[0], c[1], z + 0.6), (a[0], a[1], z + 0.6), I["rope"])
    # The windmill on the left plateau: a wooden tower, a little roof, four sails
    wx, wy = -212.0, -46.0
    z = float(ground_z(wx, wy)[0])
    ring = [(wx + 4.2 * math.cos(a), wy + 4.2 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    b.prism(ring, z - 1, z + 1.2, I["harbour"])
    b.cylinder(wx, wy, z + 1.2, z + 11, 4.0, 3.0, I["planks"], top=False, segments=8)
    b.cone(wx, wy, z + 11, 4.2, 3.6, I["thatch"], segments=8)
    # The sails turn in a plane facing the camera, on the tower's near side
    hub = np.array([wx, wy - 3.8, z + 10.0])
    for k in range(4):
        a = k * math.pi / 2 + 0.5
        d = np.array([math.cos(a), 0.0, math.sin(a)])
        w = np.array([-math.sin(a), 0.0, math.cos(a)])
        b.quad(hub + d * 1.5 - w * 0.2, hub + d * 9.5 - w * 0.2, hub + d * 9.5 + w * 1.5, hub + d * 1.5 + w * 1.5,
               I["sail"])
        b.quad(hub - w * 0.15, hub + d * 9.6 - w * 0.15, hub + d * 9.6 + w * 0.15, hub + w * 0.15, I["planks_dark"])
    b.box(wx, wy - 3.5, z + 1.2, 1.4, 0.15, 2.2, 0, I["door"])
    FOOTPRINTS.append((wx, wy, 9))
    obj = b.object("PortShore", order)
    link(scene, obj)


# ---------------------------------------------------------------------------
# The castle on the hill: red brick on a stone foot, round towers with conical roofs, a keep, the gatehouse
# ---------------------------------------------------------------------------


def build_castle(scene, rng):
    M = materials()
    order = [M["castle_stone"], M["brick"], M["roof_dark"], M["roof"], M["paving"], M["window"], M["door"],
             M["planks_dark"], M["plaster"]]
    STONE, BRICK, ROOF_D, ROOF, PAVE, WIN, DOOR, WOOD, PLASTER = range(len(order))
    b = Builder()
    cu, cv, hu, hv = CASTLE["u"], CASTLE["v"], CASTLE["half_u"] - 3, CASTLE["half_v"] - 3
    z0 = CASTLE_Z
    corners = [(cu - hu, cv - hv), (cu + hu, cv - hv), (cu + hu * 0.92, cv + hv), (cu - hu * 0.85, cv + hv * 0.95)]
    wall_h = 11.0
    gate = (cu, cv - hv)
    # Curtain walls, leaving the gate's gap; the foot of stone, brick above, battlements
    for a, c in zip(corners, corners[1:] + corners[:1]):
        if a[1] == c[1] == cv - hv:
            legs = [(a, (gate[0] - 6, gate[1])), ((gate[0] + 6, gate[1]), c)]
        else:
            legs = [(a, c)]
        for p, q in legs:
            b.band([p, q], 3.0, z0 - 6, z0 + 4, STONE, PAVE)
            b.band([p, q], 2.6, z0 + 4, z0 + wall_h, BRICK, PAVE)
            b.merlons([p, q], z0 + wall_h, BRICK, size=(1.4, 1.3), gap=1.1, width=0.8, offset=-0.9)
    # Round towers at the corners, conical red roofs
    for k, (x, y) in enumerate(corners):
        r = 5.6 if k < 2 else 5.0
        h = 20 if k < 2 else 18
        b.cylinder(x, y, z0 - 7, z0 + 5, r + 0.5, r, STONE, segments=18)
        b.cylinder(x, y, z0 + 5, z0 + h, r, r, BRICK, segments=18)
        b.cylinder(x, y, z0 + h, z0 + h + 1.0, r + 0.6, r + 0.6, BRICK, segments=18)
        b.cone(x, y, z0 + h + 1.0, r * 2.0, r + 1.0, ROOF_D, segments=18)
        for j in range(3):
            a = -math.pi / 2 + (j - 1) * 0.7
            b.box(x + math.cos(a) * (r + 0.05), y + math.sin(a) * (r + 0.05), z0 + h - 5, 0.7, 0.2, 1.5, a + math.pi / 2, WIN)
    # The gatehouse: a square tower over the gate, a pitched roof
    gx, gy = gate
    b.box(gx, gy, z0 - 7, 14, 10, 7 + 4, 0, STONE)
    b.box(gx, gy, z0 + 4, 13.6, 9.6, 12, 0, BRICK)
    b.hip_roof(gx, gy, z0 + 16, 13.6, 9.6, 6.5, 0, ROOF_D)
    b.box(gx, gy - 5.0, z0, 4.2, 0.3, 5.5, 0, DOOR)
    for k in (-1, 1):
        b.box(gx + k * 3.5, gy - 4.9, z0 + 10, 0.9, 0.2, 1.8, 0, WIN)
    # The keep at the back: tall, red brick on stone, a steep hipped roof and a turret
    kx, ky = cu + 6, cv + 10
    b.box(kx, ky, z0 - 0.5, 24, 19, 7.5, 0.05, STONE)
    b.box(kx, ky, z0 + 7, 23, 18, 21, 0.05, BRICK)
    b.merlons(footprint_line(kx, ky, 23, 18, 0.05), z0 + 28, BRICK, closed=True, size=(1.4, 1.3), gap=1.1, width=0.8,
              offset=-0.5)
    b.hip_roof(kx, ky, z0 + 28, 20, 15, 10, 0.05, ROOF_D)
    for f in range(3):
        for k in range(-2, 3):
            c, s = math.cos(0.05), math.sin(0.05)
            b.box(kx + c * k * 4.2 + s * 9.07, ky + s * k * 4.2 - c * 9.07, z0 + 10 + f * 6, 0.9, 0.2, 1.8, 0.05, WIN)
    tx, ty = kx - 11, ky - 8.5
    b.cylinder(tx, ty, z0 + 7, z0 + 33, 3.0, 3.0, BRICK, segments=12)
    b.cone(tx, ty, z0 + 33, 7, 3.6, ROOF_D, segments=12)
    # A flagstaff on the keep's roof
    b.cylinder(kx, ky, z0 + 35, z0 + 47, 0.4, 0.3, WOOD, segments=8)
    LAMP["castle_flag"] = (kx, ky, z0 + 47)
    # Buildings round the yard
    for x, y, along, across, angle in ((cu - 26, cv + 2, 14, 8, math.pi / 2), (cu - 22, cv + 22, 18, 8, 0.0),
                                        (cu + 30, cv - 10, 12, 7, math.pi / 2)):
        b.box(x, y, z0, along, across, 6.5, angle, PLASTER)
        b.gable_roof(x, y, z0 + 6.5, along, across, across * 0.55, angle, ROOF, PLASTER)
    obj = b.object("PortCastle", order)
    link(scene, obj)
    FOOTPRINTS.append((cu, cv, max(CASTLE["half_u"], CASTLE["half_v"]) + 6))


def footprint_line(x, y, along, across, angle):
    c, s = math.cos(angle), math.sin(angle)
    return [(x + a * c - w * s, y + a * s + w * c) for a, w in
            ((-along / 2, -across / 2), (along / 2, -across / 2), (along / 2, across / 2), (-along / 2, across / 2))]


# ---------------------------------------------------------------------------
# Plants (as the islands': made here, scattered by zone)
# ---------------------------------------------------------------------------

LOOK = dict(id="port", leaves=((0.01, 0.045, 0.008), (0.045, 0.12, 0.02)), trunk=(0.07, 0.045, 0.025),
            rock=("mossy_rock", 6, (0.95, 1.0, 0.95)))


def tube(bm, points, radii, sides=7):
    rings = []
    for i, (p, r) in enumerate(zip(points, radii)):
        p = Vector(p)
        ahead = Vector(points[min(i + 1, len(points) - 1)]) - Vector(points[max(i - 1, 0)])
        axis = ahead.normalized()
        side = axis.orthogonal().normalized()
        up = axis.cross(side)
        rings.append([bm.verts.new(p + (side * math.cos(a) + up * math.sin(a)) * r)
                      for a in np.linspace(0, 2 * math.pi, sides, endpoint=False)])
    for a, b in zip(rings, rings[1:]):
        for k in range(sides):
            bm.faces.new((a[k], a[(k + 1) % sides], b[(k + 1) % sides], b[k]))
    bm.faces.new(list(reversed(rings[-1])))


def blob(bm, rng, center, radius, subdiv=2, squash=1.0, amount=0.18):
    import bmesh
    geom = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    for v in geom["verts"]:
        v.co.z *= squash
        v.co += Vector(center)
        v.co += (v.co - Vector(center)).normalized() * rng.uniform(-amount, amount) * radius


def plant_mesh(kind, variant):
    import bmesh
    name = f"port_plant_{kind}_{variant}"
    mesh = bpy.data.meshes.get(name)
    if mesh:
        return mesh
    rng = np.random.default_rng(sum(ord(c) for c in kind) * 7 + variant)
    bm = bmesh.new()
    n_bark = 0
    if kind == "palm":
        h = rng.uniform(9, 13)
        bend = Vector((rng.uniform(1.5, 3.5), 0, 0))
        pts = [bend * (t * t) + Vector((0, 0, h * t)) for t in np.linspace(0, 1, 7)]
        tube(bm, pts, np.linspace(0.5, 0.3, 7))
        n_bark = len(bm.faces)
        top = pts[-1]
        for k in range(11):
            a = k / 11 * 2 * math.pi + rng.uniform(-0.2, 0.2)
            length = rng.uniform(5, 7)
            droop = rng.uniform(0.35, 0.7)
            dirv = Vector((math.cos(a), math.sin(a), 0))
            side = Vector((-math.sin(a), math.cos(a), 0))
            prev = None
            for s in range(7):
                t = s / 6
                c = top + dirv * length * t + Vector((0, 0, 1.2 * t - droop * length * t * t))
                w = 1.1 * math.sin(math.pi * min(1, t * 1.15 + 0.05)) + 0.1
                pair = (bm.verts.new(c - side * w + Vector((0, 0, 0.25 * w))), bm.verts.new(c + side * w + Vector((0, 0, 0.25 * w))))
                mid = bm.verts.new(c)
                if prev:
                    bm.faces.new((prev[0], prev[2], mid, pair[0]))
                    bm.faces.new((prev[2], prev[1], pair[1], mid))
                prev = (pair[0], pair[1], mid)
    elif kind in ("broadleaf", "bush"):
        if kind == "broadleaf":
            h = rng.uniform(3.5, 5)
            tube(bm, [(0, 0, 0), (rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), h)], [0.55, 0.4])
            n_bark = len(bm.faces)
            for _ in range(int(rng.integers(9, 14))):
                c = (rng.uniform(-2.6, 2.6), rng.uniform(-2.6, 2.6), h + rng.uniform(0.3, 3.2))
                blob(bm, rng, c, rng.uniform(1.3, 2.3), squash=0.85, amount=0.3)
        else:
            for _ in range(int(rng.integers(2, 5))):
                r = rng.uniform(0.9, 1.7)
                blob(bm, rng, (rng.uniform(-1.4, 1.4), rng.uniform(-1.4, 1.4), r * 0.6), r, squash=0.75, amount=0.22)
    elif kind == "fir":
        h = rng.uniform(10, 14)
        tube(bm, [(0, 0, 0), (0, 0, h * 0.3)], [0.4, 0.3])
        n_bark = len(bm.faces)
        for k in range(5):
            t = k / 5
            r = (1 - t) * 3.4 + 0.6
            cone = bmesh.ops.create_cone(bm, cap_ends=True, segments=9, radius1=r, radius2=0.15, depth=h * 0.3)
            for v in cone["verts"]:
                v.co.z += h * (0.18 + 0.75 * t) + h * 0.15
                v.co.x += rng.uniform(-0.25, 0.25)
                v.co.y += rng.uniform(-0.25, 0.25)
    elif kind == "rock":
        blob(bm, rng, (0, 0, 0.4), rng.uniform(1.3, 2.8), subdiv=2, squash=0.6, amount=0.25)
    for f in list(bm.faces)[n_bark:]:
        f.material_index = 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = kind != "rock"
    if kind == "rock":
        mesh.materials.append(material_rock())
        mesh.materials.append(material_rock())
    else:
        mesh.materials.append(material_bark())
        mesh.materials.append(material_leaves(kind))
    return mesh


def material_leaves(kind):
    name = f"port_leaves_{kind}"
    if bpy.data.materials.get(name):
        return bpy.data.materials[name]
    mat, n = new_material(name)
    tc = n.add("ShaderNodeTexCoord")
    noise = n.add("ShaderNodeTexNoise", Vector=tc.outputs["Object"])
    noise.inputs["Scale"].default_value = 1.6
    noise.inputs["Detail"].default_value = 8
    dark, light = LOOK["leaves"]
    if kind == "fir":
        dark, light = [tuple(c * 0.75 for c in col) for col in (dark, light)]
    color = n.mix(noise.outputs["Fac"], dark, light)
    info = n.add("ShaderNodeObjectInfo")
    hsv = n.add("ShaderNodeHueSaturation", Color=color)
    n.link(n.math("ADD", n.math("MULTIPLY", info.outputs["Random"], 0.06), 0.47), hsv.inputs["Hue"])
    n.link(n.math("ADD", n.math("MULTIPLY", info.outputs["Random"], 0.5), 0.75), hsv.inputs["Value"])
    leafy = n.add("ShaderNodeTexVoronoi", Vector=tc.outputs["Object"])
    leafy.inputs["Scale"].default_value = 2.5
    bump = n.add("ShaderNodeBump", Height=leafy.outputs["Distance"])
    bump.inputs["Strength"].default_value = 0.8
    bsdf = n.add("ShaderNodeBsdfPrincipled", **{"Base Color": hsv.outputs["Color"], "Normal": bump.outputs["Normal"]})
    bsdf.inputs["Roughness"].default_value = 0.75
    out = n.add("ShaderNodeOutputMaterial")
    n.link(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def material_bark():
    if bpy.data.materials.get("port_bark"):
        return bpy.data.materials["port_bark"]
    mat, n = new_material("port_bark")
    noise = n.add("ShaderNodeTexNoise", Vector=n.add("ShaderNodeTexCoord").outputs["Object"])
    noise.inputs["Scale"].default_value = 3
    base = LOOK["trunk"]
    n.shade(n.mix(noise.outputs["Fac"], tuple(c * 0.7 for c in base), base), rough=0.9)
    return mat


def material_rock():
    if bpy.data.materials.get("port_rock"):
        return bpy.data.materials["port_rock"]
    mat, n = new_material("port_rock")
    color, height = n.texture(n.add("ShaderNodeTexCoord").outputs["Object"], *LOOK["rock"], box=True)
    n.shade(color, height, 0.6, 0.85)
    return mat


def build_plants(scene, rng):
    spacing = 7.0
    land = np.asarray(H["land"])
    us = np.arange(land[:, 0].min(), land[:, 0].max(), spacing)
    vs = np.arange(land[:, 1].min(), land[:, 1].max(), spacing)
    gu, gv = np.meshgrid(us, vs)
    gu = (gu + rng.uniform(-0.45, 0.45, gu.shape) * spacing).ravel()
    gv = (gv + rng.uniform(-0.45, 0.45, gv.shape) * spacing).ravel()
    z, d, masks = heights(gu, gv)
    e = 0.8
    zx = (heights(gu + e, gv)[0] - heights(gu - e, gv)[0]) / (2 * e)
    zy = (heights(gu, gv + e)[0] - heights(gu, gv - e)[0]) / (2 * e)
    slope = np.hypot(zx, zy)
    road_dist, _ = polyline_distance(gu, gv, ROAD)
    hill, r = hill_height(gu, gv)
    # Trees grow in groves, with meadows between; few on the mount's face over the town, so the rock shows
    groves = smoothstep(-0.1, 0.45, waves_noise(gu, gv, 31, 120, 3))
    face = smoothstep(10, -20, gv - HILL["v"]) * smoothstep(110, 60, np.abs(gu - HILL["u"]))
    plants = []
    for i in range(len(gu)):
        u, v = gu[i], gv[i]
        if d[i] < 2 or road_dist[i] < ROAD_WIDTH + 2.5 or masks["paved"][i] > 0.1 or masks["field"][i] > 0.1:
            continue
        if any(math.hypot(u - x, v - y) < rr for x, y, rr in FOOTPRINTS):
            continue
        town = masks["town"][i]
        roll = rng.uniform()
        if slope[i] > 0.9:
            kind = "rock" if roll < 0.12 else ("bush" if roll < 0.2 else None)
        elif d[i] < BEACH_WIDTH + 2:
            kind = "palm" if roll < 0.035 and town < 0.2 else None
        elif town > 0.4:
            kind = "broadleaf" if roll < 0.12 else None
        elif hill[i] > 8:
            roll /= 0.35 + 0.65 * groves[i] * (1 - 0.75 * face[i])
            kind = "broadleaf" if roll < 0.22 else "fir" if roll < 0.36 else "bush" if roll < 0.44 else None
        else:
            roll /= 0.15 + 0.85 * groves[i]
            kind = "broadleaf" if roll < 0.12 else "bush" if roll < 0.18 else "palm" if roll < 0.19 else None
        if kind is None:
            continue
        obj = bpy.data.objects.new(f"PortPlant_{i}", plant_mesh(kind, i % 3))
        loc = TURN @ Vector((u, v, z[i] - 0.3))
        obj.location = loc
        obj.rotation_euler = (0, 0, rng.uniform(0, 2 * math.pi))
        obj.scale = (rng.uniform(0.8, 1.2),) * 3
        link(scene, obj)
        plants.append(obj)
    return plants


# ---------------------------------------------------------------------------
# Scene, camera, light
# ---------------------------------------------------------------------------


def link(scene, obj):
    if obj.name not in scene.collection.objects:
        scene.collection.objects.link(obj)


def camera_axes():
    """Camera directions in Blender's world (as render_sprites.py)"""
    yaw, pitch = math.radians(CAM_YAW), math.radians(CAM_PITCH)
    fwd = Vector((math.sin(yaw), math.cos(yaw), 0))
    right = Vector((math.cos(yaw), -math.sin(yaw), 0))
    view = (fwd * math.cos(pitch) + Vector((0, 0, -math.sin(pitch)))).normalized()
    up = (fwd * math.sin(pitch) + Vector((0, 0, math.cos(pitch)))).normalized()
    return right, up, view


def has_gpu():
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            prefs.get_devices()
            if any(d.type != "CPU" for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type != "CPU"
                return True
        return False
    except Exception:
        return False


def scene_setup():
    scene = bpy.data.scenes.get("Port") or bpy.data.scenes.new("Port")
    if bpy.context.window:
        bpy.context.window.scene = scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    sun = bpy.data.objects.new("PortSun", bpy.data.lights.get("PortSun") or bpy.data.lights.new("PortSun", "SUN"))
    scene.collection.objects.link(sun)
    sun.data.energy = SUN_STRENGTH
    sun.data.angle = math.radians(SUN_ANGLE)
    x, y, z = LIGHT_GAME
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = Vector((x, -y, z)).normalized().to_track_quat("Z", "Y")
    world = bpy.data.worlds.get("PortWorld") or bpy.data.worlds.new("PortWorld")
    world.use_nodes = True
    scene.world = world
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.82, 0.9, 1.0, 1)
    bg.inputs["Strength"].default_value = AMBIENT
    cam = bpy.data.objects.new("PortCamera", bpy.data.cameras.get("PortCamera") or bpy.data.cameras.new("PortCamera"))
    scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.clip_start = 1
    cam.data.clip_end = 5000
    scene.camera = cam
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if has_gpu() else "CPU"
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 3
    scene.cycles.transparent_max_bounces = 4
    scene.render.film_transparent = True
    scene.render.resolution_percentage = 100
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    return scene


def frame_camera(scene, points):
    """Frames the camera on Blender points; returns the picture's size and where the island's centre is in it"""
    right, up, view = camera_axes()
    pts = np.asarray(points)
    sx, sy = pts @ np.array(right), pts @ np.array(up)
    lo = np.array([sx.min(), sy.min()])
    hi = np.array([sx.max(), sy.max()])
    width = int(math.ceil((hi[0] - lo[0]) * PX_PER_UNIT)) + 2 * MARGIN
    height = int(math.ceil((hi[1] - lo[1]) * PX_PER_UNIT)) + 2 * MARGIN
    anchor = (-lo[0] * PX_PER_UNIT + MARGIN, hi[1] * PX_PER_UNIT + MARGIN)
    cx = (width / 2 - anchor[0]) / PX_PER_UNIT
    cy = (anchor[1] - height / 2) / PX_PER_UNIT
    cam = scene.camera
    cam.data.ortho_scale = max(width, height) / PX_PER_UNIT
    m = Matrix((right, up, -view)).transposed().to_4x4()
    m.translation = right * cx + up * cy - view * 2000
    cam.matrix_world = m
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    return width, height, anchor


def bounds(objects):
    pts = []
    for obj in objects:
        for c in obj.bound_box:
            pts.append(tuple(obj.matrix_world @ Vector(c)))
    return pts


# ---------------------------------------------------------------------------
# Rendering and cutting the picture up
# ---------------------------------------------------------------------------

try:
    import OpenImageIO as oiio
except ImportError:
    oiio = None


def load_rgba(path):
    config = oiio.ImageSpec()
    config.attribute("oiio:UnassociatedAlpha", 1)
    buf = oiio.ImageBuf(path, 0, 0, config)
    px = buf.get_pixels(oiio.FLOAT)
    if px.shape[2] == 3:
        px = np.concatenate([px, np.ones(px.shape[:2] + (1,), np.float32)], axis=2)
    return px


def save_webp(path, rgba, quality=88):
    """rgba: straight alpha, float 0..1, row 0 at the top"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h, w, _ = rgba.shape
    img = bpy.data.images.new("port_out", w, h, alpha=True)
    img.alpha_mode = "STRAIGHT"
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    img.filepath_raw = path
    scene = bpy.context.scene
    settings = scene.render.image_settings
    old = (settings.file_format, settings.quality, settings.color_mode)
    settings.file_format = "WEBP" if path.endswith(".webp") else "PNG"
    settings.quality = quality
    settings.color_mode = "RGBA"
    img.save_render(path, scene=scene)
    settings.file_format, settings.quality, settings.color_mode = old
    bpy.data.images.remove(img)


def render(scene, path, samples, exr=False, filter_width=1.2):
    scene.cycles.samples = samples
    scene.cycles.filter_width = filter_width
    scene.cycles.use_denoising = samples > 4
    s = scene.render.image_settings
    s.file_format = "OPEN_EXR" if exr else "PNG"
    s.color_depth = "32" if exr else "8"
    s.color_mode = "RGBA"
    scene.render.filepath = path
    t0 = time.time()
    bpy.ops.render.render(write_still=True, scene=scene.name)
    print(f"rendered {os.path.basename(path)} in {time.time() - t0:.0f} s", flush=True)


def position_material():
    """Every surface shows where it is: u, v in the harbour's frame and z, as its colour"""
    mat, n = new_material("port_position")
    geo = n.add("ShaderNodeNewGeometry")
    sep = n.add("ShaderNodeSeparateXYZ", Vector=geo.outputs["Position"])
    u = n.math("MULTIPLY", n.math("SUBTRACT", sep.outputs["X"], sep.outputs["Y"]), S2)
    v = n.math("MULTIPLY", n.math("ADD", sep.outputs["X"], sep.outputs["Y"]), S2)
    comb = n.add("ShaderNodeCombineXYZ")
    n.link(u, comb.inputs["X"])
    n.link(v, comb.inputs["Y"])
    n.link(sep.outputs["Z"], comb.inputs["Z"])
    emit = n.add("ShaderNodeEmission", Color=comb.outputs[0])
    emit.inputs["Strength"].default_value = 1.0
    out = n.add("ShaderNodeOutputMaterial")
    n.link(emit.outputs[0], out.inputs["Surface"])
    return mat


def water_plane(scene, points):
    pts = np.asarray(points)
    lo, hi = pts.min(axis=0) - 50, pts.max(axis=0) + 50
    mesh = bpy.data.meshes.get("PortWater") or bpy.data.meshes.new("PortWater")
    mesh.clear_geometry()
    mesh.from_pydata([(lo[0], lo[1], 0), (hi[0], lo[1], 0), (hi[0], hi[1], 0), (lo[0], hi[1], 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new("PortWater", mesh)
    obj.is_shadow_catcher = True
    link(scene, obj)
    return obj


def render_all(scene, catcher, anchor):
    os.makedirs(FRAMES_DIR, exist_ok=True)
    color_png = os.path.join(FRAMES_DIR, "color.png")
    pos_exr = os.path.join(FRAMES_DIR, "position.exr")
    shadow_png = os.path.join(FRAMES_DIR, "shadow.png")
    others = [o for o in scene.objects if o.type == "MESH" and o is not catcher]
    # 1. The colour
    catcher.hide_render = True
    render(scene, color_png, SAMPLES)
    # 2. Where every pixel's surface is: one sample through its middle, no filter
    view_layer = scene.view_layers[0]
    view_layer.material_override = position_material()
    scene.view_settings.view_transform = "Standard"
    render(scene, pos_exr, 1, exr=True, filter_width=0.01)
    view_layer.material_override = None
    # 3. The shadows on the water: only the catcher is seen, everything else only casts shadows
    catcher.hide_render = False
    for o in others:
        o.visible_camera = False
    render(scene, shadow_png, max(8, SAMPLES // 3))
    for o in others:
        o.visible_camera = True
    catcher.hide_render = True
    return color_png, pos_exr, shadow_png


def dilate(mask, by):
    """A mask grown by `by` pixels"""
    out = mask.copy()
    h, w = mask.shape
    for dy in range(-by, by + 1):
        for dx in range(-by, by + 1):
            if dx * dx + dy * dy > by * by or (dx == 0 and dy == 0):
                continue
            out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] |= \
                mask[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def cut_up(color_png, pos_exr, shadow_png, anchor):
    """The ground and the slices. Each pixel belongs to one of them; but each also holds, UNDERLAP pixels round its
    edge, what the nearer ones show there (the ground holds the raised land round it): those are always drawn over
    by their own picture, and with them no seam opens between two pictures when the game shrinks them"""
    color = load_rgba(color_png)
    pos = load_rgba(pos_exr)
    shadow = np.clip((load_rgba(shadow_png)[..., 3] - 0.06) / 0.94, 0, 1)
    hit = pos[..., 3] > 0.5
    u, v, z = pos[..., 0], pos[..., 1], pos[..., 2]
    raised = hit & (z >= CUT)
    # The ground: what is at the water's level, and the shadows on the water over it
    ground = color.copy()
    solid = ~raised & (color[..., 3] > 0.5)
    ground[raised & ~dilate(solid, UNDERLAP)] = 0
    water = (~hit) | (z < -0.02)
    s = np.where(water & ~raised, shadow * WATER_SHADOW, 0.0)
    a = ground[..., 3]
    out_a = s + a * (1 - s)
    rgb = ground[..., :3] * (a * (1 - s) / np.maximum(out_a, 1e-6))[..., None]
    ground = np.concatenate([rgb, out_a[..., None]], axis=2)
    # The slices: raised pixels by where on the ground their surface stands, along the camera's view
    index = np.where(raised, np.floor(v / SLICE).astype(int), 10 ** 6)
    slices = []
    for k in np.unique(index[raised]):
        own = index == k
        rows, cols = np.nonzero(own)
        top, left = max(rows.min() - UNDERLAP, 0), max(cols.min() - UNDERLAP, 0)
        bottom, right = rows.max() + 1 + UNDERLAP, cols.max() + 1 + UNDERLAP
        sub = own[top:bottom, left:right]
        # Nearer slices (smaller v) round its edge: drawn over it anyway
        near = dilate(sub, UNDERLAP) & (index[top:bottom, left:right] < k)
        keep = sub | near
        part = np.zeros(sub.shape + (4,), np.float32)
        part[keep] = color[top:bottom, left:right][keep]
        slices.append(dict(v=float((k + 0.5) * SLICE), top=int(top), left=int(left), pixels=part))
    return ground, slices


def crop(rgba):
    solid = np.argwhere(rgba[..., 3] > 0.004)
    top, left = np.maximum(solid.min(axis=0) - MARGIN, 0)
    bottom, right = np.minimum(solid.max(axis=0) + MARGIN + 1, rgba.shape[:2])
    return rgba[top:bottom, left:right], int(top), int(left)


def pack(slices):
    """Shelf-packs the slices into pages of at most PAGE pixels a side, GUTTER pixels of air between them"""
    order = sorted(range(len(slices)), key=lambda i: -slices[i]["pixels"].shape[0])
    pages, placed = [], {}
    x = y = shelf = 0
    page = 0
    width = min(PAGE, max(s["pixels"].shape[1] for s in slices) + GUTTER)
    width = max(width, 1024)
    heights = [0]
    for i in order:
        h, w = slices[i]["pixels"].shape[:2]
        if x + w + GUTTER > width:
            x, y = 0, y + shelf + GUTTER
            shelf = 0
        if y + h + GUTTER > PAGE:
            page += 1
            heights.append(0)
            x = y = shelf = 0
        placed[i] = (page, x, y)
        x += w + GUTTER
        shelf = max(shelf, h)
        heights[page] = max(heights[page], y + h + GUTTER)
    for p in range(page + 1):
        pages.append(np.zeros((heights[p], width, 4), np.float32))
    for i, (p, x, y) in placed.items():
        h, w = slices[i]["pixels"].shape[:2]
        pages[p][y:y + h, x:x + w] = slices[i]["pixels"]
    return pages, placed


def write_out(ground, slices, anchor):
    os.makedirs(SPRITES_DIR, exist_ok=True)
    # Pages of an earlier build that this one doesn't make again
    for name in os.listdir(SPRITES_DIR):
        if name.startswith("raised_") and name.endswith(".webp"):
            os.remove(os.path.join(SPRITES_DIR, name))
    g, top, left = crop(ground)
    save_webp(os.path.join(SPRITES_DIR, "ground.webp"), g)
    pages, placed = pack(slices)
    for p, pixels in enumerate(pages):
        save_webp(os.path.join(SPRITES_DIR, f"raised_{p}.webp"), pixels)
    meta = dict(
        pxPerUnit=PX_PER_UNIT, pitch=CAM_PITCH, yaw=CAM_YAW,
        centre=[CX, CY],
        ground=dict(file="ground.webp", w=int(g.shape[1]), h=int(g.shape[0]), x=round(anchor[0] - left, 1),
                    y=round(anchor[1] - top, 1)),
        pages=[f"raised_{p}.webp" for p in range(len(pages))],
        slices=[],
    )
    # The lamp and the flags the game animates, each over the slice its tower stands in
    bands = [s["v"] for s in slices]
    for key, name in (("lamp", "lamp"), ("flag", "flag"), ("castleFlag", "castle_flag")):
        u, v, z = LAMP[name]
        band = (math.floor(v / SLICE) + 0.5) * SLICE
        meta[key] = dict(point=[round(c, 2) for c in (*game(u, v), z)], slice=bands.index(band))
    for i, s in enumerate(slices):
        p, x, y = placed[i]
        h, w = s["pixels"].shape[:2]
        at = game(0.0, s["v"])
        meta["slices"].append(dict(page=p, frame=[x, y, w, h], x=round(s["left"] - anchor[0], 1),
                                   y=round(s["top"] - anchor[1], 1), at=[round(at[0], 2), round(at[1], 2)]))
    with open(os.path.join(SPRITES_DIR, "port.json"), "w", newline="\n") as fh:
        json.dump(meta, fh, indent=1)
        fh.write("\n")
    print(f"port: ground {g.shape[1]}x{g.shape[0]}, {len(slices)} slices on {len(pages)} page(s) "
          f"{[p.shape[1::-1] for p in pages]}", flush=True)


def build():
    t0 = time.time()
    rng = np.random.default_rng(7)
    FOOTPRINTS.clear()
    LAMP.clear()
    MATERIALS.clear()
    scene = scene_setup()
    terrain, verts = build_terrain(scene)
    build_harbour(scene, rng)
    build_castle(scene, rng)
    build_town(scene, rng)
    build_shore(scene, rng)
    plants = build_plants(scene, rng)
    print(f"built in {time.time() - t0:.0f} s: {len(plants)} plants", flush=True)
    visible = verts[verts[:, 2] > -DEPTH * 0.95]
    world_pts = [tuple(TURN @ Vector(p)) for p in visible[:: max(1, len(visible) // 20000)]]
    structures = [o for o in scene.objects if o.type == "MESH" and o.name.startswith("Port") and o is not terrain]
    points = world_pts + bounds(structures)
    catcher = water_plane(scene, [p[:2] for p in world_pts])
    width, height, anchor = frame_camera(scene, points)
    print(f"picture {width}x{height}", flush=True)
    return scene, catcher, anchor


def main():
    try:
        scene, catcher, anchor = build()
        if not PREVIEW:
            bpy.ops.wm.save_as_mainfile(filepath=BLEND)
        if os.environ.get("PORT_NO_RENDER"):
            return
        if PREVIEW:
            catcher.hide_render = True
            render(scene, os.path.join(FRAMES_DIR, "preview.png"), SAMPLES)
            print("PREVIEW DONE", flush=True)
            return
        files = render_all(scene, catcher, anchor)
        ground, slices = cut_up(*files, anchor)
        write_out(ground, slices, anchor)
        print("PORT DONE", flush=True)
    except Exception:
        print("ERROR\n" + traceback.format_exc(), flush=True)
        if bpy.app.background:
            sys.exit(1)


# Imported by build_harbour.py for the port's geometry: then it builds and renders nothing
if __name__ == "__main__":
    main()

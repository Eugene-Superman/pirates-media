"""
Islands for the game: ten island shapes, each rendered in five looks, for the game's isometric camera.

Run in Blender (any file; the script works in its own scene "Islands"): Scripting -> Open -> build_islands.py ->
Run Script. Blender stays usable between renders; progress is printed to the system console. 100 renders, about
15-20 minutes on a GTX 1060. Set ISLAND_ONLY=look:shape,... in the environment to render a few (e.g. tropical:cay).

What it makes:
  canvas/src/game/world/islandShapes.json   the shapes for the game logic: coastline, size, heights
  canvas/public/sprites/islands/<look>/<shape>_ground.webp, <shape>_raised.webp
  canvas/public/sprites/islands/islands.json    where each picture's island centre is, and the scale

Every shape is a height field built from a coastline (radius by angle around the centre): a sloping sea floor that
fades out under the water, a beach, then land rising to a plateau, hills and cliffs. The looks are real textures
from Poly Haven (polyhaven.com, CC0; downloaded into textures/polyhaven/ on the first run) for the sand, the land and
the rock, and plants made here: palms, leafy trees, bushes, firs, dry scrub, rocks.

Two layers, so ships can sail round an island: "ground" is the whole terrain with the sea floor (drawn under ships)
and the shadows of the plants; "raised" is the terrain above the beach with the plants (drawn over a ship that is
behind the island). Laid over each other they are one picture.

Camera and light are the game's (as in render_sprites.py): pitch 30, yaw 45, sun from LIGHT = (-0.6, 0.1, 0.8).
Game coordinates have y pointing south; Blender's y is north, so y is negated.
"""

import json
import math
import os
import time
import traceback
import urllib.request

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

PX_PER_UNIT = 2.2  # sprite pixels per world unit: the game's zoom 1.4 x ~1.5
CAM_PITCH = 30.0
CAM_YAW = 45.0
LIGHT_GAME = (-0.6, 0.1, 0.8)
SUN_STRENGTH = 2.0
SUN_ANGLE = 1.2
AMBIENT = 0.72
SAMPLES = 40

SEGMENTS = 48  # coastline points in the game's data
GRID = 1.25  # world units between terrain vertices
SHALLOWS = 1.45  # the sea floor reaches this share of the coast's radius, out of sight under the water
DEPTH = 5.0  # world units the sea floor goes down to
BEACH_HEIGHT = 1.6  # top of the beach above the water, world units
CUT = 0.6  # world units: terrain above this is the "raised" layer
MAX_PLANT = 16  # world units: no plant is taller (for framing the camera)
FOAM = 0.55  # how white the surf along the waterline is
MARGIN = 4  # pixels round a cropped picture

# ---------------------------------------------------------------------------
# Shapes. radius: world units of the reference circle; the coast's radius by angle is a share of it.
# elong: length / width; angle: degrees the long axis is turned (game coordinates, 0 = east, clockwise on the map);
# lobes: (angle°, size, width°) bulges (+) and bays (-); rough: how jagged; plateau: height of the land, world units;
# cliff: how steep its edge is (0 gentle, 1 sheer); beach: share of the radius that is beach;
# hills: (x, y, height, width): position and width in shares of the radius (y south), height in world units;
# plants: how densely they grow (0..1)
# ---------------------------------------------------------------------------
SHAPES = [
    dict(id="round", radius=105, seed=3, elong=1.1, angle=20, lobes=[], rough=0.08, plateau=10, cliff=0.4,
         beach=0.16, hills=[(0.05, -0.05, 14, 0.35)], plants=0.8),
    dict(id="bean", radius=140, seed=8, elong=1.7, angle=-25, lobes=[(70, -0.28, 28)], rough=0.07, plateau=13,
         cliff=0.5, beach=0.13, hills=[(-0.35, 0.1, 16, 0.3), (0.38, -0.05, 22, 0.28)], plants=0.75),
    dict(id="long", radius=165, seed=12, elong=2.6, angle=35, lobes=[(215, 0.12, 25)], rough=0.06, plateau=12,
         cliff=0.55, beach=0.12, hills=[(-0.2, -0.12, 12, 0.5), (0.3, 0.15, 18, 0.32)], plants=0.7),
    dict(id="cay", radius=58, seed=17, elong=1.4, angle=-10, lobes=[], rough=0.1, plateau=2.2, cliff=0.1,
         beach=0.38, hills=[], plants=0.9),
    dict(id="spire", radius=72, seed=21, elong=1.15, angle=60, lobes=[(150, 0.15, 30)], rough=0.12, plateau=18,
         cliff=0.95, beach=0.12, hills=[(0.0, 0.05, 30, 0.38)], plants=0.35),
    dict(id="twins", radius=150, seed=26, elong=2.0, angle=-50, lobes=[(40, -0.3, 22), (220, -0.3, 22)],
         rough=0.07, plateau=11, cliff=0.45, beach=0.13, hills=[(-0.45, 0.0, 26, 0.3), (0.45, 0.0, 18, 0.3)],
         plants=0.75),
    dict(id="bay", radius=175, seed=31, elong=1.3, angle=10, lobes=[(250, -0.42, 30), (100, 0.12, 40)],
         rough=0.07, plateau=14, cliff=0.6, beach=0.12, hills=[(0.05, -0.3, 40, 0.3)], plants=0.65),
    dict(id="cape", radius=120, seed=37, elong=1.2, angle=0, lobes=[(0, 0.32, 18), (120, 0.3, 18), (240, 0.3, 18)],
         rough=0.06, plateau=12, cliff=0.7, beach=0.12, hills=[(0.0, 0.0, 10, 0.4)], plants=0.7),
    dict(id="jagged", radius=130, seed=44, elong=1.35, angle=75, lobes=[(30, -0.18, 14), (160, -0.2, 12),
         (290, -0.16, 14)], rough=0.2, plateau=12, cliff=0.75, beach=0.1, hills=[(-0.15, 0.2, 20, 0.3),
         (0.25, -0.2, 15, 0.25)], plants=0.6),
    dict(id="flat", radius=150, seed=52, elong=1.5, angle=-70, lobes=[(330, 0.15, 30)], rough=0.09, plateau=4,
         cliff=0.15, beach=0.2, hills=[(0.2, 0.1, 5, 0.5)], plants=0.95),
]

# ---------------------------------------------------------------------------
# Looks: Poly Haven textures (id, tile size in world units, tint) for the sand, the land, patches mixed into the land
# and the rock; the colour of shallow water and the tint of the sea floor; plant colours; plants by zone:
# (kind, chance) per scatter point. Colours are linear (Blender's), not sRGB: 0.2 linear is about 0.48 on screen
# ---------------------------------------------------------------------------
LOOKS = [
    dict(id="tropical", name="Tropical",
         sand=("aerial_beach_01", 30, (1.3, 1.18, 0.92)), land=("forrest_ground_01", 30, (0.95, 1.05, 0.85)),
         patch=("grass_ground", 34, (0.9, 1.0, 0.8)), rock=("aerial_rocks_04", 24, (1.0, 1.0, 1.0)),
         water=(0.03, 0.45, 0.48), seabed=(1.0, 0.98, 0.88),
         leaves=((0.012, 0.06, 0.008), (0.06, 0.16, 0.02)), trunk=(0.09, 0.055, 0.03),
         plants=dict(shore=[("palm", 0.35)], low=[("palm", 0.22), ("broadleaf", 0.25), ("bush", 0.15)],
                     high=[("broadleaf", 0.45), ("bush", 0.15)], cliff=[("rock", 0.12)])),
    dict(id="green", name="Green isle",
         sand=("sand_03", 26, (1.0, 0.98, 0.92)), land=("grass_ground", 30, (0.85, 1.0, 0.75)),
         patch=("aerial_grass_rock", 36, (0.9, 1.0, 0.85)), rock=("mossy_rock", 20, (0.95, 1.0, 0.95)),
         water=(0.03, 0.3, 0.33), seabed=(0.85, 0.85, 0.75),
         leaves=((0.01, 0.045, 0.008), (0.045, 0.12, 0.02)), trunk=(0.07, 0.045, 0.025),
         plants=dict(shore=[("bush", 0.12), ("rock", 0.05)], low=[("broadleaf", 0.3), ("bush", 0.2)],
                     high=[("broadleaf", 0.3), ("fir", 0.25)], cliff=[("rock", 0.2)])),
    dict(id="desert", name="Desert",
         sand=("dense_sand", 28, (1.1, 1.0, 0.85)), land=("red_laterite_soil_stones", 30, (1.05, 0.95, 0.85)),
         patch=("dry_ground_01", 34, (1.1, 0.98, 0.85)), rock=("rock_boulder_dry", 22, (1.0, 0.85, 0.7)),
         water=(0.04, 0.42, 0.42), seabed=(1.0, 0.92, 0.75),
         leaves=((0.04, 0.045, 0.015), (0.12, 0.11, 0.04)), trunk=(0.12, 0.08, 0.05),
         plants=dict(shore=[("rock", 0.06)], low=[("dry", 0.16), ("deadtree", 0.03), ("rock", 0.05)],
                     high=[("dry", 0.08), ("rock", 0.08)], cliff=[("rock", 0.25)])),
    dict(id="volcanic", name="Volcanic",
         sand=("coast_sand_05", 24, (0.85, 0.85, 0.85)), land=("dark_rock_02", 34, (0.9, 0.88, 0.85)),
         patch=("coast_sand_rocks_02", 30, (0.85, 1.0, 0.8)), rock=("dark_rock", 22, (0.9, 0.88, 0.86)),
         water=(0.02, 0.24, 0.28), seabed=(0.35, 0.35, 0.36),
         leaves=((0.008, 0.035, 0.008), (0.03, 0.08, 0.015)), trunk=(0.05, 0.04, 0.03),
         plants=dict(shore=[("rock", 0.15)], low=[("bush", 0.18), ("palm", 0.06)], high=[("rock", 0.1)],
                     cliff=[("rock", 0.22)])),
    dict(id="northern", name="Northern",
         sand=("ganges_river_pebbles", 16, (0.95, 0.95, 0.95)), land=("aerial_rocks_01", 30, (0.9, 0.95, 0.88)),
         patch=("rock_ground", 30, (0.9, 0.9, 0.9)), rock=("lichen_rock", 20, (0.95, 0.97, 1.0)),
         water=(0.02, 0.2, 0.26), seabed=(0.6, 0.6, 0.58),
         leaves=((0.005, 0.025, 0.01), (0.02, 0.06, 0.025)), trunk=(0.06, 0.045, 0.03),
         plants=dict(shore=[("rock", 0.15)], low=[("fir", 0.4), ("bush", 0.1)], high=[("fir", 0.35)],
                     cliff=[("rock", 0.25)])),
]
PLANT_SPACING = 8  # world units between scatter points (before thinning by chance and density)

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()
for _text in bpy.data.texts:
    if _text.filepath and os.path.basename(_text.filepath) == "build_islands.py":
        SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
TEX_DIR = os.path.join(ASSETS_DIR, "textures", "polyhaven")
GAME_DIR = os.path.normpath(os.path.join(ASSETS_DIR, "..", "canvas"))
SPRITES_DIR = os.path.join(GAME_DIR, "public", "sprites", "islands")
SHAPES_JSON = os.path.join(GAME_DIR, "src", "game", "world", "islandShapes.json")
FRAMES_DIR = os.path.join(ASSETS_DIR, "frames", "islands")


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------
# Shapes and terrain (game coordinates: x east, y south, z up; the island's centre at 0, 0)
# ---------------------------------------------------------------------------


def coast_multipliers(shape):
    """The coast's radius by angle, as shares of the shape's radius, SEGMENTS of them from angle 0 clockwise"""
    rng = np.random.default_rng(shape["seed"])
    th = np.arange(SEGMENTS) / SEGMENTS * 2 * np.pi
    fine = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    a = math.radians(shape["angle"])
    long_axis = math.sqrt(shape["elong"])
    r = 1 / np.sqrt((np.cos(fine - a) / long_axis) ** 2 + (np.sin(fine - a) * long_axis) ** 2)
    for angle, size, width in shape["lobes"]:
        diff = np.angle(np.exp(1j * (fine - math.radians(angle))))
        r *= 1 + size * np.exp(-((diff / math.radians(width)) ** 2))
    jag = np.zeros_like(fine)
    for k in range(2, 9):
        jag += rng.normal() * np.cos(k * fine + rng.uniform(0, 2 * np.pi)) / k
    r *= 1 + shape["rough"] * jag / max(np.abs(jag).max(), 1e-6)
    r /= np.sqrt((r**2).mean())  # the reference circle has the same area
    return np.interp(th, fine, r, period=2 * np.pi)


def coast_radius(mult, theta):
    """Radius of the coast (share) at angles theta, linearly between the SEGMENTS points, as the game draws it"""
    pos = (theta % (2 * np.pi)) / (2 * np.pi) * SEGMENTS
    i0 = np.floor(pos).astype(int) % SEGMENTS
    i1 = (i0 + 1) % SEGMENTS
    t = pos - np.floor(pos)
    # Straight between points, like the polygon: the radius along a chord, not a straight interpolation
    a0 = i0 / SEGMENTS * 2 * np.pi
    a1 = a0 + 2 * np.pi / SEGMENTS
    p0 = np.stack([np.cos(a0) * mult[i0], np.sin(a0) * mult[i0]], -1)
    p1 = np.stack([np.cos(a1) * mult[i1], np.sin(a1) * mult[i1]], -1)
    d = np.stack([np.cos(theta), np.sin(theta)], -1)
    e = p1 - p0
    # Intersection of the ray from the centre along d with the chord p0 -> p1
    denom = d[..., 0] * e[..., 1] - d[..., 1] * e[..., 0]
    num = p0[..., 0] * e[..., 1] - p0[..., 1] * e[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(np.abs(denom) > 1e-9, num / denom, mult[i0] * (1 - t) + mult[i1] * t)
    return r


def waves_noise(x, y, rng, scale, octaves=4):
    """Smooth noise from a few plane waves per octave: cheap, and the same for a given rng"""
    out = np.zeros_like(x)
    amp = 1.0
    freq = 1 / scale
    for _ in range(octaves):
        for _ in range(3):
            ang = rng.uniform(0, 2 * np.pi)
            out += amp * np.sin((x * math.cos(ang) + y * math.sin(ang)) * freq * 2 * np.pi + rng.uniform(0, 2 * np.pi))
        amp *= 0.5
        freq *= 2.03
    return out / 3


def heights(shape, mult, x, y):
    """Terrain height at game points (x, y) round the centre, world units"""
    rng = np.random.default_rng(shape["seed"] + 1000)
    R = shape["radius"]
    theta = np.arctan2(y, x)
    rc = R * coast_radius(mult, theta)
    d = np.hypot(x, y) / rc
    noise = waves_noise(x, y, rng, R * 0.35)
    fine = waves_noise(x, y, rng, 9, 3)

    beach = shape["beach"]
    z = np.empty_like(x)
    sea = d >= 1
    z[sea] = -DEPTH * smoothstep(1, SHALLOWS, d[sea]) ** 0.6 + 0.15 * fine[sea]
    land = ~sea
    dl = d[land]
    z_beach = BEACH_HEIGHT * np.clip((1 - dl) / beach, 0, 1) ** 1.3
    # The land rises from the top of the beach: over a short distance for cliffs, a long one for gentle slopes
    rise_width = 0.05 + 0.4 * (1 - shape["cliff"])
    u = np.clip((1 - beach - dl) / rise_width, 0, 1)
    rise = u * u * (3 - 2 * u)
    if shape["cliff"] > 0.6:
        rise = rise ** 0.5
    plateau = shape["plateau"] * (1 + 0.25 * noise[land])
    hills = np.zeros_like(dl)
    for hx, hy, hh, hw in shape["hills"]:
        q = ((x[land] / R - hx) ** 2 + (y[land] / R - hy) ** 2) / hw**2
        hills += hh * np.exp(-q) * (1 + 0.15 * noise[land])
    z_land = z_beach + rise * (plateau + hills) + 0.3 * fine[land] * rise
    z[land] = np.maximum(z_land, z_beach)
    return z, d


def build_terrain(shape, mult):
    R = shape["radius"]
    extent = R * mult.max() * SHALLOWS + 2 * GRID
    n = int(math.ceil(2 * extent / GRID)) + 1
    xs = np.linspace(-extent, extent, n)
    gx, gy = np.meshgrid(xs, xs)  # gy: game y (south)
    z, d = heights(shape, mult, gx, gy)
    # Blender: x, -y, z
    verts = np.stack([gx, -gy, z], -1).reshape(-1, 3)
    idx = np.arange(n * n).reshape(n, n)
    quads = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], -1).reshape(-1, 4)
    dq = d.reshape(-1)[quads].min(axis=1)
    zq = z.reshape(-1)[quads]
    keep = dq < SHALLOWS
    ground = quads[keep]
    raised = quads[keep & (zq.max(axis=1) > CUT)]
    return verts, ground, raised, (gx, gy, z, d)


def make_mesh(name, verts, quads):
    used = np.unique(quads)
    remap = np.full(len(verts), -1)
    remap[used] = np.arange(len(used))
    v = verts[used]
    f = remap[quads]
    mesh = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    mesh.clear_geometry()
    mesh.vertices.add(len(v))
    mesh.vertices.foreach_set("co", v.astype(np.float32).ravel())
    mesh.loops.add(len(f) * 4)
    mesh.loops.foreach_set("vertex_index", f.astype(np.int32).ravel())
    mesh.polygons.add(len(f))
    mesh.polygons.foreach_set("loop_start", (np.arange(len(f)) * 4).astype(np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(len(f), 4, np.int32))
    mesh.update(calc_edges=True)
    mesh.polygons.foreach_set("use_smooth", np.ones(len(f), bool))
    return mesh


# ---------------------------------------------------------------------------
# Plants: where they grow (the same for every look), and what grows there (by look)
# ---------------------------------------------------------------------------


def scatter(shape, mult):
    """Points on the land with their zone: shore (top of the beach), low land, high land, cliff"""
    rng = np.random.default_rng(shape["seed"] + 2000)
    R = shape["radius"]
    extent = R * mult.max()
    xs = np.arange(-extent, extent, PLANT_SPACING)
    gx, gy = np.meshgrid(xs, xs)
    gx = gx + rng.uniform(-0.45, 0.45, gx.shape) * PLANT_SPACING
    gy = gy + rng.uniform(-0.45, 0.45, gy.shape) * PLANT_SPACING
    gx, gy = gx.ravel(), gy.ravel()
    z, d = heights(shape, mult, gx, gy)
    e = 0.8
    zx = (heights(shape, mult, gx + e, gy)[0] - heights(shape, mult, gx - e, gy)[0]) / (2 * e)
    zy = (heights(shape, mult, gx, gy + e)[0] - heights(shape, mult, gx, gy - e)[0]) / (2 * e)
    slope = np.hypot(zx, zy)
    top = BEACH_HEIGHT + shape["plateau"] * 0.6
    points = []
    for i in range(len(gx)):
        if d[i] >= 0.97 or z[i] < 0.9:
            continue
        if slope[i] > 0.9:
            zone = "cliff"
        elif d[i] > 1 - shape["beach"] * 0.75:
            zone = "shore"
        elif z[i] < top + 4:
            zone = "low"
        else:
            zone = "high"
        if rng.uniform() > shape["plants"]:
            continue
        points.append(dict(x=float(gx[i]), y=float(gy[i]), z=float(z[i]), zone=zone, pick=float(rng.uniform()),
                           turn=float(rng.uniform(0, 2 * np.pi)), size=float(rng.uniform(0.75, 1.25)),
                           lean=float(rng.uniform(0, 2 * np.pi))))
    return points


def jitter(bm, rng, amount):
    for v in bm.verts:
        v.co += v.normal * rng.uniform(-amount, amount)


def blob(bm, rng, center, radius, subdiv=2, squash=1.0, amount=0.18):
    geom = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    verts = geom["verts"]
    for v in verts:
        v.co.z *= squash
        v.co += Vector(center)
        v.co += (v.co - Vector(center)).normalized() * rng.uniform(-amount, amount) * radius
    return verts


def tube(bm, points, radii, sides=7):
    """A tube along points with a radius at each"""
    rings = []
    for i, (p, r) in enumerate(zip(points, radii)):
        p = Vector(p)
        ahead = Vector(points[min(i + 1, len(points) - 1)]) - Vector(points[max(i - 1, 0)])
        axis = ahead.normalized()
        side = axis.orthogonal().normalized()
        up = axis.cross(side)
        ring = [bm.verts.new(p + (side * math.cos(a) + up * math.sin(a)) * r)
                for a in np.linspace(0, 2 * math.pi, sides, endpoint=False)]
        rings.append(ring)
    for a, b in zip(rings, rings[1:]):
        for k in range(sides):
            bm.faces.new((a[k], a[(k + 1) % sides], b[(k + 1) % sides], b[k]))
    bm.faces.new(list(reversed(rings[-1])))


def plant_mesh(kind, look, variant):
    """One plant model of a kind for a look: two materials, bark/stone (0) and leaves (1). Origin at its foot"""
    name = f"plant_{look['id']}_{kind}_{variant}"
    mesh = bpy.data.meshes.get(name)
    if mesh:
        return mesh
    # A stable seed: Python's hash() of a string changes between sessions
    rng = np.random.default_rng(sum(ord(c) for c in kind) * 7 + variant)
    bm = bmesh.new()
    if kind == "palm":
        h = rng.uniform(9, 13)
        bend = Vector((rng.uniform(1.5, 3.5), 0, 0))
        pts = [Vector((0, 0, 0)) + bend * (t * t) + Vector((0, 0, h * t)) for t in np.linspace(0, 1, 7)]
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
        faces = list(bm.faces)
        for f in faces[n_bark:]:
            f.material_index = 1
    elif kind in ("broadleaf", "bush", "dry"):
        if kind == "broadleaf":
            h = rng.uniform(3.5, 5)
            tube(bm, [(0, 0, 0), (rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), h)], [0.55, 0.4])
            n_bark = len(bm.faces)
            for _ in range(int(rng.integers(9, 14))):
                c = (rng.uniform(-2.6, 2.6), rng.uniform(-2.6, 2.6), h + rng.uniform(0.3, 3.2))
                blob(bm, rng, c, rng.uniform(1.3, 2.3), squash=0.85, amount=0.3)
        else:
            n_bark = 0
            count = int(rng.integers(2, 5))
            for _ in range(count):
                r = rng.uniform(0.9, 1.7) * (0.7 if kind == "dry" else 1)
                c = (rng.uniform(-1.4, 1.4), rng.uniform(-1.4, 1.4), r * 0.6)
                blob(bm, rng, c, r, subdiv=2, squash=0.75, amount=0.35 if kind == "dry" else 0.22)
        for f in list(bm.faces)[n_bark:]:
            f.material_index = 1
    elif kind == "fir":
        h = rng.uniform(10, 14)
        tube(bm, [(0, 0, 0), (0, 0, h * 0.3)], [0.4, 0.3])
        n_bark = len(bm.faces)
        tiers = 5
        for k in range(tiers):
            t = k / tiers
            r = (1 - t) * 3.4 + 0.6
            base = h * (0.18 + 0.75 * t)
            cone = bmesh.ops.create_cone(bm, cap_ends=True, segments=9, radius1=r, radius2=0.15, depth=h * 0.3)
            for v in cone["verts"]:
                v.co.z += base + h * 0.15
                v.co.x += rng.uniform(-0.25, 0.25)
                v.co.y += rng.uniform(-0.25, 0.25)
        for f in list(bm.faces)[n_bark:]:
            f.material_index = 1
    elif kind == "deadtree":
        h = rng.uniform(5, 8)
        tube(bm, [(0, 0, 0), (0.3, 0.2, h * 0.6), (0.6, 0.1, h)], [0.4, 0.28, 0.12])
        for _ in range(4):
            a = rng.uniform(0, 2 * math.pi)
            start = (0.3, 0.2, h * rng.uniform(0.45, 0.85))
            end = (start[0] + math.cos(a) * 2.5, start[1] + math.sin(a) * 2.5, start[2] + rng.uniform(1, 2.5))
            tube(bm, [start, end], [0.16, 0.06], sides=5)
    elif kind == "rock":
        blob(bm, rng, (0, 0, 0.4), rng.uniform(1.3, 2.8), subdiv=2, squash=0.6, amount=0.25)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = kind != "rock"
    mesh.materials.append(material_bark(look) if kind != "rock" else material_stone(look))
    mesh.materials.append(material_leaves(look, kind))
    return mesh


PLANT_VARIANTS = 3


# ---------------------------------------------------------------------------
# Textures and materials
# ---------------------------------------------------------------------------


def download(asset):
    """Poly Haven's 1k diffuse map of an asset, into textures/polyhaven/ (seen from this far, bumps come from it too)"""
    os.makedirs(TEX_DIR, exist_ok=True)
    wanted = {"Diffuse": "diff"}
    paths = {suffix: os.path.join(TEX_DIR, f"{asset}_{suffix}_1k.jpg") for suffix in wanted.values()}
    if all(os.path.exists(p) for p in paths.values()):
        return paths
    req = urllib.request.Request(f"https://api.polyhaven.com/files/{asset}", headers={"User-Agent": "blender-assets"})
    files = json.load(urllib.request.urlopen(req, timeout=60))
    for key, suffix in wanted.items():
        if os.path.exists(paths[suffix]) or key not in files:
            continue
        url = files[key]["1k"]["jpg"]["url"]
        req = urllib.request.Request(url, headers={"User-Agent": "blender-assets"})
        with urllib.request.urlopen(req, timeout=120) as r, open(paths[suffix], "wb") as fh:
            fh.write(r.read())
        print("downloaded", os.path.basename(paths[suffix]), flush=True)
    return paths


def image(path, data):
    img = bpy.data.images.load(path, check_existing=True)
    if data:
        img.colorspace_settings.name = "Non-Color"
    return img


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

    def mix(self, factor, a, b):
        n = self.add("ShaderNodeMix")
        n.data_type = "RGBA"
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


def texture_set(nodes, coords, spec):
    """Diffuse colour (tinted) of a Poly Haven texture tiled every spec[1] world units, and its brightness for bumps"""
    asset, tile, tint = spec
    paths = download(asset)
    mapping = nodes.add("ShaderNodeMapping", Vector=coords)
    mapping.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
    diff = nodes.add("ShaderNodeTexImage", Vector=mapping.outputs[0])
    diff.image = image(paths["diff"], False)
    # From three sides, blended: on a cliff a texture laid from above would be smeared into streaks
    diff.projection = "BOX"
    diff.projection_blend = 0.35
    mult = nodes.add("ShaderNodeMix")
    mult.data_type = "RGBA"
    mult.blend_type = "MULTIPLY"
    mult.inputs[0].default_value = 1
    nodes.link(diff.outputs["Color"], mult.inputs[6])
    mult.inputs[7].default_value = (*tint, 1)
    bw = nodes.add("ShaderNodeRGBToBW", Color=diff.outputs["Color"])
    return mult.outputs[2], bw.outputs[0]


def material_terrain(look):
    name = f"terrain_{look['id']}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nodes = Nodes(mat)
    tc = nodes.add("ShaderNodeTexCoord")
    coords = tc.outputs["Object"]
    geo = nodes.add("ShaderNodeNewGeometry")
    sep = nodes.add("ShaderNodeSeparateXYZ", Vector=geo.outputs["Position"])
    z = sep.outputs["Z"]
    sepn = nodes.add("ShaderNodeSeparateXYZ", Vector=geo.outputs["Normal"])
    nz = sepn.outputs["Z"]
    noise = nodes.add("ShaderNodeTexNoise", Vector=coords)
    noise.inputs["Scale"].default_value = 0.05
    noise.inputs["Detail"].default_value = 6
    wobble = nodes.math("SUBTRACT", noise.outputs["Fac"], 0.5)

    sand, sand_h = texture_set(nodes, coords, look["sand"])
    land, land_h = texture_set(nodes, coords, look["land"])
    patch, _ = texture_set(nodes, coords, look["patch"])
    rock, rock_h = texture_set(nodes, coords, look["rock"])
    # Big soft patches of a second ground texture, so the land isn't one texture repeated
    patches = nodes.add("ShaderNodeTexNoise", Vector=coords)
    patches.inputs["Scale"].default_value = 0.025
    patches.inputs["Detail"].default_value = 4
    land = nodes.mix(nodes.smooth(patches.outputs["Fac"], 0.4, 0.65), land, patch)

    # Sand up to the top of the beach (wobbly edge), land above, rock where steep
    zb = nodes.math("ADD", z, nodes.math("MULTIPLY", wobble, 2.4))
    land_share = nodes.smooth(zb, BEACH_HEIGHT - 0.2, BEACH_HEIGHT + 1.4)
    steep = nodes.smooth(nz, 0.82, 0.62)
    upper = nodes.mix(steep, land, rock)
    color = nodes.mix(land_share, sand, upper)
    # Wet sand at the waterline
    wet = nodes.smooth(z, 0.5, 0.0)
    darker = nodes.add("ShaderNodeMix")
    darker.data_type = "RGBA"
    darker.blend_type = "MULTIPLY"
    nodes.link(wet, darker.inputs[0])
    nodes.link(color, darker.inputs[6])
    darker.inputs[7].default_value = (0.8, 0.77, 0.72, 1)
    color = darker.outputs[2]
    # Under the water: the sea floor seen through shallow water, fading into the game's sea
    depth = nodes.math("MULTIPLY", z, -1)
    under = nodes.smooth(depth, 0.0, 0.5)
    murk = nodes.smooth(depth, 0.2, DEPTH * 0.8)
    tinted = nodes.add("ShaderNodeMix")
    tinted.data_type = "RGBA"
    tinted.blend_type = "MULTIPLY"
    tinted.inputs[0].default_value = 1
    nodes.link(sand, tinted.inputs[6])
    tinted.inputs[7].default_value = (*look["seabed"], 1)
    seafloor = nodes.mix(murk, tinted.outputs[2], (*look["water"], 1))
    color = nodes.mix(under, color, seafloor)
    # Surf: a broken white line along the waterline
    foam_noise = nodes.add("ShaderNodeTexNoise", Vector=coords)
    foam_noise.inputs["Scale"].default_value = 0.35
    foam_noise.inputs["Detail"].default_value = 5
    band = nodes.math("MULTIPLY", nodes.smooth(z, -0.4, -0.15), nodes.smooth(z, 0.02, -0.08))
    foam = nodes.math("MULTIPLY", band, nodes.smooth(foam_noise.outputs["Fac"], 0.5, 0.7), clamp=True)
    foam = nodes.math("MULTIPLY", foam, FOAM)
    color = nodes.mix(foam, color, (0.93, 0.96, 0.96, 1))

    # Bumps from the textures' brightness, none under the water
    upper_h = nodes.math("ADD", nodes.math("MULTIPLY", land_h, nodes.math("SUBTRACT", 1.0, steep)),
                         nodes.math("MULTIPLY", rock_h, steep))
    height = nodes.math("ADD", nodes.math("MULTIPLY", sand_h, nodes.math("SUBTRACT", 1.0, land_share)),
                        nodes.math("MULTIPLY", upper_h, land_share))
    bump = nodes.add("ShaderNodeBump", Height=nodes.math("MULTIPLY", height, nodes.math("SUBTRACT", 1.0, under)))
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.3
    bsdf = nodes.add("ShaderNodeBsdfPrincipled", **{"Base Color": color, "Normal": bump.outputs["Normal"]})
    bsdf.inputs["Roughness"].default_value = 0.9
    # Alpha: solid on land and in the shallows, fading out over the deeper sea floor
    alpha = nodes.math("SUBTRACT", 1.0, nodes.smooth(depth, 0.6, DEPTH * 0.92))
    alpha = nodes.math("MAXIMUM", alpha, foam)
    transparent = nodes.add("ShaderNodeBsdfTransparent")
    mixer = nodes.add("ShaderNodeMixShader", Fac=alpha)
    nodes.link(transparent.outputs[0], mixer.inputs[1])
    nodes.link(bsdf.outputs[0], mixer.inputs[2])
    out = nodes.add("ShaderNodeOutputMaterial")
    nodes.link(mixer.outputs[0], out.inputs["Surface"])
    return mat


def material_leaves(look, kind):
    name = f"leaves_{look['id']}_{kind}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    nodes = Nodes(mat)
    tc = nodes.add("ShaderNodeTexCoord")
    noise = nodes.add("ShaderNodeTexNoise", Vector=tc.outputs["Object"])
    noise.inputs["Scale"].default_value = 1.6
    noise.inputs["Detail"].default_value = 8
    dark, light = look["leaves"]
    if kind == "fir":
        dark, light = [tuple(c * 0.75 for c in col) for col in (dark, light)]
    if kind == "dry":
        dark, light = (0.05, 0.035, 0.015), (0.15, 0.11, 0.055)
    color = nodes.mix(noise.outputs["Fac"], (*dark, 1), (*light, 1))
    # Every plant a little lighter or darker, yellower or bluer than the next
    info = nodes.add("ShaderNodeObjectInfo")
    hsv = nodes.add("ShaderNodeHueSaturation", Color=color)
    nodes.link(nodes.math("ADD", nodes.math("MULTIPLY", info.outputs["Random"], 0.06), 0.47), hsv.inputs["Hue"])
    nodes.link(nodes.math("ADD", nodes.math("MULTIPLY", info.outputs["Random"], 0.5), 0.75), hsv.inputs["Value"])
    color = hsv.outputs["Color"]
    leafy = nodes.add("ShaderNodeTexVoronoi", Vector=tc.outputs["Object"])
    leafy.inputs["Scale"].default_value = 2.5
    bump = nodes.add("ShaderNodeBump", Height=leafy.outputs["Distance"])
    bump.inputs["Strength"].default_value = 0.8
    bsdf = nodes.add("ShaderNodeBsdfPrincipled", **{"Base Color": color, "Normal": bump.outputs["Normal"]})
    bsdf.inputs["Roughness"].default_value = 0.75
    out = nodes.add("ShaderNodeOutputMaterial")
    nodes.link(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def material_bark(look):
    name = f"bark_{look['id']}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    nodes = Nodes(mat)
    tc = nodes.add("ShaderNodeTexCoord")
    noise = nodes.add("ShaderNodeTexNoise", Vector=tc.outputs["Object"])
    noise.inputs["Scale"].default_value = 3
    base = look["trunk"]
    color = nodes.mix(noise.outputs["Fac"], (*[c * 0.7 for c in base], 1), (*base, 1))
    bsdf = nodes.add("ShaderNodeBsdfPrincipled", **{"Base Color": color})
    bsdf.inputs["Roughness"].default_value = 0.9
    out = nodes.add("ShaderNodeOutputMaterial")
    nodes.link(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def material_stone(look):
    name = f"stone_{look['id']}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    nodes = Nodes(mat)
    tc = nodes.add("ShaderNodeTexCoord")
    rock, rock_h = texture_set(nodes, tc.outputs["Object"], (look["rock"][0], 6, look["rock"][2]))
    bump = nodes.add("ShaderNodeBump", Height=rock_h)
    bump.inputs["Strength"].default_value = 0.6
    bsdf = nodes.add("ShaderNodeBsdfPrincipled", **{"Base Color": rock, "Normal": bump.outputs["Normal"]})
    bsdf.inputs["Roughness"].default_value = 0.85
    out = nodes.add("ShaderNodeOutputMaterial")
    nodes.link(bsdf.outputs[0], out.inputs["Surface"])
    return mat


# ---------------------------------------------------------------------------
# Scene, camera and light
# ---------------------------------------------------------------------------


def camera_axes():
    """Camera directions in Blender's world (as render_sprites.py)"""
    yaw, pitch = math.radians(CAM_YAW), math.radians(CAM_PITCH)
    fwd = Vector((math.sin(yaw), math.cos(yaw), 0))
    right = Vector((math.cos(yaw), -math.sin(yaw), 0))
    view = (fwd * math.cos(pitch) + Vector((0, 0, -math.sin(pitch)))).normalized()
    up = (fwd * math.sin(pitch) + Vector((0, 0, math.cos(pitch)))).normalized()
    return right, up, view


def light_dir():
    x, y, z = LIGHT_GAME
    return Vector((x, -y, z)).normalized()


def scene_setup():
    scene = bpy.data.scenes.get("Islands") or bpy.data.scenes.new("Islands")
    bpy.context.window.scene = scene
    sun = scene.objects.get("IslandSun")
    if sun is None:
        sun = bpy.data.objects.new("IslandSun", bpy.data.lights.new("IslandSun", "SUN"))
        scene.collection.objects.link(sun)
    sun.data.energy = SUN_STRENGTH
    sun.data.angle = math.radians(SUN_ANGLE)
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = light_dir().to_track_quat("Z", "Y")
    world = bpy.data.worlds.get("IslandWorld") or bpy.data.worlds.new("IslandWorld")
    world.use_nodes = True
    scene.world = world
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.82, 0.9, 1.0, 1)
    bg.inputs["Strength"].default_value = AMBIENT
    cam = scene.objects.get("IslandCamera")
    if cam is None:
        cam = bpy.data.objects.new("IslandCamera", bpy.data.cameras.new("IslandCamera"))
        scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.clip_start = 1
    cam.data.clip_end = 4000
    scene.camera = cam
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if has_gpu() else "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 3
    scene.cycles.transparent_max_bounces = 4
    scene.cycles.filter_width = 1.2
    scene.render.film_transparent = True
    scene.render.use_persistent_data = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    return scene


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


def frame_camera(scene, points):
    """Frames the camera on Blender points; returns the picture's size and where the island's centre (0,0,0) is"""
    right, up, view = camera_axes()
    pts = np.asarray(points)
    sx = pts @ np.array(right)
    sy = pts @ np.array(up)
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
    m.translation = right * cx + up * cy - view * 1500
    cam.matrix_world = m
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    return width, height, anchor


# ---------------------------------------------------------------------------
# Building and rendering
# ---------------------------------------------------------------------------


def shape_data():
    data = []
    for shape in SHAPES:
        mult = coast_multipliers(shape)
        top = BEACH_HEIGHT + shape["plateau"]
        hill = max([h[2] for h in shape["hills"]], default=0)
        data.append(dict(id=shape["id"], radius=shape["radius"], shape=[round(float(m), 4) for m in mult],
                         height=round(top, 1), hillHeight=round(float(hill), 1)))
    return data


def write_shapes():
    os.makedirs(os.path.dirname(SHAPES_JSON), exist_ok=True)
    with open(SHAPES_JSON, "w", newline="\n") as fh:
        json.dump(shape_data(), fh, indent=2)
        fh.write("\n")
    print("shapes ->", SHAPES_JSON, flush=True)


def link(scene, obj):
    if obj.name not in scene.collection.objects:
        scene.collection.objects.link(obj)


def clear_island(scene):
    for obj in list(scene.objects):
        if obj.name.startswith(("Ground", "Raised", "Plant_")):
            bpy.data.objects.remove(obj, do_unlink=True)


def build_island(scene, shape, look):
    """Puts one shape in one look into the scene; returns the Blender points to frame"""
    clear_island(scene)
    mult = coast_multipliers(shape)
    verts, ground_q, raised_q, _ = build_terrain(shape, mult)
    terrain = material_terrain(look)
    objects = {}
    for name, quads in (("Ground", ground_q), ("Raised", raised_q)):
        mesh = make_mesh(f"{name}_{shape['id']}", verts, quads)
        mesh.materials.clear()
        mesh.materials.append(terrain)
        obj = bpy.data.objects.new(name, mesh)
        link(scene, obj)
        objects[name] = obj
    plants = []
    for i, p in enumerate(scatter(shape, mult)):
        options = look["plants"].get(p["zone"], [])
        roll = p["pick"]
        kind = None
        for k, chance in options:
            if roll < chance:
                kind = k
                break
            roll -= chance
        if kind is None:
            continue
        variant = i % PLANT_VARIANTS
        obj = bpy.data.objects.new(f"Plant_{i}", plant_mesh(kind, look, variant))
        obj.location = (p["x"], -p["y"], p["z"] - 0.3)
        obj.rotation_euler = (0, 0, p["turn"])
        obj.scale = (p["size"],) * 3
        link(scene, obj)
        plants.append(obj)
    # Framing: the sea floor's visible part and every plant's top
    visible = verts[verts[:, 2] > -DEPTH * 0.95]
    tops = [(o.location.x, o.location.y, o.location.z + MAX_PLANT) for o in plants] or [(0, 0, 0)]
    return objects, plants, np.concatenate([visible, np.array(tops)])


def set_pass(objects, plants, layer):
    ground, raised = objects["Ground"], objects["Raised"]
    ground.hide_render = layer != "ground"
    raised.hide_render = layer != "raised"
    for p in plants:
        # In the ground layer the plants only cast their shadows
        p.visible_camera = layer == "raised"
        p.visible_shadow = True
        p.visible_diffuse = layer == "raised"
        p.visible_glossy = layer == "raised"


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


def save_webp(path, rgba, quality=86):
    """rgba: straight alpha, float 0..1, row 0 at the top"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h, w, _ = rgba.shape
    img = bpy.data.images.new("island_out", w, h, alpha=True)
    img.alpha_mode = "STRAIGHT"
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "WEBP"
    scene = bpy.context.scene
    settings = scene.render.image_settings
    old = (settings.file_format, settings.quality, settings.color_mode)
    settings.file_format = "WEBP"
    settings.quality = quality
    settings.color_mode = "RGBA"
    img.save_render(path, scene=scene)
    settings.file_format, settings.quality, settings.color_mode = old
    bpy.data.images.remove(img)


def crop_and_save(png, webp, anchor):
    rgba = load_rgba(png)
    solid = np.argwhere(rgba[..., 3] > 0.004)
    if len(solid) == 0:
        rgba = np.zeros((2, 2, 4), np.float32)
        top, left = 0, 0
    else:
        top, left = np.maximum(solid.min(axis=0) - MARGIN, 0)
        bottom, right = np.minimum(solid.max(axis=0) + MARGIN + 1, rgba.shape[:2])
        rgba = rgba[top:bottom, left:right]
    save_webp(webp, rgba)
    return dict(file=os.path.relpath(webp, SPRITES_DIR).replace("\\", "/"), w=int(rgba.shape[1]),
                h=int(rgba.shape[0]), x=round(anchor[0] - left, 1), y=round(anchor[1] - top, 1))


def only_list():
    raw = os.environ.get("ISLAND_ONLY", "").strip()
    if not raw:
        return None
    return {tuple(item.split(":")) for item in raw.split(",")}


def jobs():
    only = only_list()
    out = []
    for look in LOOKS:
        for shape in SHAPES:
            if only and (look["id"], shape["id"]) not in only:
                continue
            out.append((look, shape))
    return out


def meta_path():
    return os.path.join(SPRITES_DIR, "islands.json")


def load_meta():
    if os.path.exists(meta_path()):
        with open(meta_path()) as fh:
            meta = json.load(fh)
    else:
        meta = {}
    meta["pxPerUnit"] = PX_PER_UNIT
    meta["looks"] = [dict(id=look["id"], name=look["name"]) for look in LOOKS]
    meta.setdefault("sprites", {})
    return meta


def save_meta(meta):
    os.makedirs(SPRITES_DIR, exist_ok=True)
    with open(meta_path(), "w", newline="\n") as fh:
        json.dump(meta, fh, indent=1)
        fh.write("\n")


state = {"jobs": [], "pos": 0, "layer": 0, "done": False, "error": None, "started": time.time(), "log": []}
bpy.app.driver_namespace["islands_state"] = state
current = {}


def step():
    try:
        scene = bpy.data.scenes["Islands"]
        if state["pos"] >= len(state["jobs"]):
            clear_island(scene)
            state["done"] = True
            print(f"islands done in {time.time() - state['started']:.0f} s", flush=True)
            return None
        look, shape = state["jobs"][state["pos"]]
        if state["layer"] == 0:
            objects, plants, points = build_island(scene, shape, look)
            current.update(objects=objects, plants=plants, frame=frame_camera(scene, points))
        layer = ("ground", "raised")[state["layer"]]
        set_pass(current["objects"], current["plants"], layer)
        png = os.path.join(FRAMES_DIR, look["id"], f"{shape['id']}_{layer}.png")
        os.makedirs(os.path.dirname(png), exist_ok=True)
        scene.render.filepath = png
        t0 = time.time()
        with bpy.context.temp_override(window=bpy.context.window_manager.windows[0], scene=scene):
            bpy.ops.render.render(write_still=True, scene=scene.name)
        info = crop_and_save(png, os.path.join(SPRITES_DIR, look["id"], f"{shape['id']}_{layer}.webp"),
                             current["frame"][2])
        meta = load_meta()
        meta["sprites"].setdefault(look["id"], {}).setdefault(shape["id"], {})[layer] = info
        save_meta(meta)
        state["log"].append(f"{look['id']}/{shape['id']}/{layer} {time.time() - t0:.1f}s")
        print(f"[{state['pos'] + 1}/{len(state['jobs'])}] {look['id']} {shape['id']} {layer}: "
              f"{time.time() - t0:.1f} s", flush=True)
        state["layer"] += 1
        if state["layer"] > 1:
            state["layer"] = 0
            state["pos"] += 1
        return 0.1
    except Exception:
        state["error"] = traceback.format_exc()
        print(state["error"], flush=True)
        return None


def reset():
    """Forgets plants and materials of an earlier run, so changes to this script take effect"""
    scene = bpy.data.scenes.get("Islands")
    if scene:
        clear_island(scene)
    for mesh in list(bpy.data.meshes):
        if mesh.name.startswith(("plant_", "Ground_", "Raised_")) and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        if mat.name.startswith(("terrain_", "leaves_", "bark_", "stone_")):
            bpy.data.materials.remove(mat)


def main():
    reset()
    write_shapes()
    for look in LOOKS:
        for key in ("sand", "land", "patch", "rock"):
            download(look[key][0])
    scene_setup()
    state["jobs"] = jobs()
    if os.environ.get("ISLAND_NO_RENDER"):
        state["done"] = True
        return
    bpy.app.timers.register(step, first_interval=0.5)


main()

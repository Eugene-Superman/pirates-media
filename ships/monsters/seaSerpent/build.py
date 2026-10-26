"""
Sea serpent (line "monsters", game class "seaSerpent"), built from code: a sea monster that strikes at ships from the
water. Its body bends along the way it swam, so it isn't one picture: the game lays it out (client/scene/models/
SerpentSprite.ts) from the parts rendered here, each from every direction, in one atlas a damage stage:
  head     the head on the end of the neck: horned, finned, yellow-eyed, its jaw breathing a little (frames 1-4)
  bite     the head striking: the mouth opens wide on its fangs, the head rears and snaps shut (frames 101-106)
  segment  a piece of the scaly body, laid along it over and over and scaled to its thickness (frame 201)
  fin      the same with a spined fin on its back: every other piece of the back (frame 211)
  harpoon  the same with a harpoon in it: the pieces the game marks as hit (frame 221)
  tail     the tail's end, with its fin (frame 231)
Every part sits at the origin, the others hidden at its frame (keyed hide_render), so the timeline shows them one after
another; the head's and the jaw's joints are keyframed. The parts cast no shadow: the game draws them with their
water (the body under the surface, foam where it breaks it).

Run in Blender: open seaSerpent.blend next to this file, Scripting tab -> Open -> build.py -> Run Script. It rebuilds
the "Ship" collection for the scene's "damage" property (0-4, see DAMAGE_STAGES); render_stages.py renders every stage.

Damage: 1 a few cuts; 2 bleeding, its fins torn; 3 bleeding badly, the fins in rags; 4 dead: pale, the eyes shut, the
jaw hanging open.

Axes and scale match the game: 1 Blender unit = 1 game unit, the head points to +X, Z up. A body piece is as thick as
the body's thickest part (serpent3d.ts, BODY_RADIUS 3.1); the head is about as big as the vector model's (HEAD_SCALE):
wider than the neck, so it reads as a head at the end of it.

Textures: the scales are a shader pattern over the wrinkles of a scanned CC0 leather from Poly Haven (polyhaven.com),
in blender-assets/textures/polyhaven/, downloaded there on the first run.
"""

import json
import math
import os
import urllib.request

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

BODY_RADIUS = 3.1  # the body's thickest, world units: the game scales a piece down to its place along the body
PIECE_LENGTH = 3.0  # half-length of a piece of the body: pieces 2.35 apart overlap into one body
JAW_HINGE = (2.6, -0.7)  # x, z of the jaw's hinge in the head's frame
HEAD_SIZE = 1.3  # the head and its jaw, against the sizes they are built at below

# The parts and the timeline's frames they are shown at: the game's animations
# prettier-ignore
ANIMATIONS = {
    "head": dict(start=1, frames=4, fps=8, loop=True),
    "bite": dict(start=101, frames=6, fps=13, loop=False),
    "segment": dict(start=201, frames=1, fps=1, loop=True),
    "fin": dict(start=211, frames=1, fps=1, loop=True),
    "harpoon": dict(start=221, frames=1, fps=1, loop=True),
    "tail": dict(start=231, frames=1, fps=1, loop=True),
}
DEAD_FRAME = 301
DEAD = dict(ANIMATIONS, head=dict(start=DEAD_FRAME, frames=1, fps=1, loop=True))
del DEAD["bite"]
# No shadow on the water: the parts are laid out by the game, their shadows would land in the wrong places
SHADOW = False

SKIN_TILE = 3.0
SCALE_SIZE = 1.6  # scales a unit

COLORS = {
    "body": 0x2F7A62,
    "edge": 0x163F33,
    "belly": 0xA8C99A,
    "fin": 0xD9603B,
    "bone": 0xD8CFB0,
    "eye": 0xFFD84A,
    "pupil": 0x101010,
    "lid": 0x24594A,
    "teeth": 0xF2EEDD,
    "mouth": 0x7A2A2A,
    "wound": 0x5A1010,
    "shaft": 0x7A5A35,
    "iron": 0x3A3A40,
}

# prettier-ignore
DAMAGE_STAGES = {
    0: dict(blood=0.0, fin=1.0, pale=0.0, dead=False),
    1: dict(blood=0.12, fin=1.0, pale=0.0, dead=False),
    2: dict(blood=0.25, fin=0.85, pale=0.0, dead=False),
    3: dict(blood=0.42, fin=0.65, pale=0.1, dead=False),
    4: dict(blood=0.45, fin=0.6, pale=0.45, dead=True),
}


def base_dir():
    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()


def assets_root(ship_dir):
    """blender-assets itself: the parent of the "ships" folder this ship lives in"""
    path = os.path.abspath(ship_dir)
    while os.path.basename(path) != "ships":
        parent = os.path.dirname(path)
        if parent == path:
            return os.path.abspath(ship_dir)
        path = parent
    return os.path.dirname(path)


SHIP_DIR = os.environ.get("SHIP_OUT") or base_dir()  # ships/monsters/seaSerpent
TEX_DIR = os.path.join(SHIP_DIR, "textures")
PH_DIR = os.path.join(assets_root(SHIP_DIR), "textures", "polyhaven")


def animations(stage):
    """The parts rendered for a damage stage: the dead serpent doesn't bite, and its head has one pose"""
    return DEAD if DAMAGE_STAGES[stage]["dead"] else ANIMATIONS


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def srgb(hex_color):
    return [((hex_color >> s) & 0xFF) / 255 for s in (16, 8, 0)]


def linear(hex_color):
    out = []
    for c in srgb(hex_color):
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out + [1.0]


def save_image(name, rgba):
    """rgba: h x w x 4 array in sRGB 0..1, row 0 at the top. Saved next to the .blend and linked, not packed"""
    os.makedirs(TEX_DIR, exist_ok=True)
    h, w, _ = rgba.shape
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    path = os.path.join(TEX_DIR, name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    img.source = "FILE"
    img.filepath = relpath(path)
    img.reload()
    return img


def relpath(path):
    try:
        return bpy.path.relpath(path)
    except ValueError:
        return path


def value_noise(size, cells, rng):
    """Smooth noise 0..1: a random grid of `cells` x `cells` interpolated up to `size`"""
    grid = rng.random((cells + 1, cells + 1))
    coords = np.linspace(0, cells, size)
    i = np.clip(coords.astype(int), 0, cells - 1)
    f = coords - i
    f = f * f * (3 - 2 * f)
    rows = grid[i] * (1 - f)[:, None] + grid[i + 1] * f[:, None]
    return rows[:, i] * (1 - f)[None, :] + rows[:, i + 1] * f[None, :]


POLYHAVEN_KINDS = {"diff": "Diffuse", "nor_gl": "nor_gl", "rough": "Rough"}


def download(asset):
    """Poly Haven's 1k maps of an asset into textures/polyhaven/, the first time a ship needs them"""
    paths = {kind: os.path.join(PH_DIR, f"{asset}_{kind}_1k.jpg") for kind in POLYHAVEN_KINDS}
    if all(os.path.exists(p) for p in paths.values()):
        return
    os.makedirs(PH_DIR, exist_ok=True)
    req = urllib.request.Request(f"https://api.polyhaven.com/files/{asset}", headers={"User-Agent": "blender-assets"})
    files = json.load(urllib.request.urlopen(req, timeout=60))
    for kind, key in POLYHAVEN_KINDS.items():
        if os.path.exists(paths[kind]) or key not in files:
            continue
        url = files[key]["1k"]["jpg"]["url"]
        req = urllib.request.Request(url, headers={"User-Agent": "blender-assets"})
        with urllib.request.urlopen(req, timeout=120) as r, open(paths[kind], "wb") as fh:
            fh.write(r.read())
        print("downloaded", os.path.basename(paths[kind]), flush=True)


def polyhaven(asset, kind):
    """kind: diff / nor_gl / rough. None when Poly Haven has no such map for the asset"""
    download(asset)
    path = os.path.join(PH_DIR, f"{asset}_{kind}_1k.jpg")
    if not os.path.exists(path):
        return None
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "sRGB" if kind == "diff" else "Non-Color"
    img.filepath = relpath(path)
    return img


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


def new_material(name):
    old = bpy.data.materials.get(name)
    if old:
        bpy.data.materials.remove(old)
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    return m


def plain(name, color, rough=0.8, metal=0.0, alpha=1.0):
    m = new_material(name)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = linear(color)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if alpha < 1:
        bsdf.inputs["Alpha"].default_value = alpha
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = "BLENDED"
    m.diffuse_color = linear(color)
    return m


def grain(nodes, links, asset, coords, tile, low=0.65, high=1.2):
    """The brightness of a scanned set's grain, box-mapped from object coordinates: low..high"""
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1 / tile)
    links.new(coords, mapping.inputs["Vector"])
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = polyhaven(asset, "diff")
    tex.projection = "BOX"
    tex.projection_blend = 0.3
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    bw = nodes.new("ShaderNodeRGBToBW")
    links.new(tex.outputs["Color"], bw.inputs["Color"])
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.clamp = True
    ramp.inputs["From Min"].default_value = 0.05
    ramp.inputs["From Max"].default_value = 0.6
    ramp.inputs["To Min"].default_value = low
    ramp.inputs["To Max"].default_value = high
    links.new(bw.outputs["Val"], ramp.inputs["Value"])
    nor = polyhaven(asset, "nor_gl")
    normal = None
    if nor is not None:
        ntex = nodes.new("ShaderNodeTexImage")
        ntex.image = nor
        ntex.projection = "BOX"
        ntex.projection_blend = 0.3
        links.new(mapping.outputs["Vector"], ntex.inputs["Vector"])
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = 0.8
        links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        normal = nmap.outputs["Normal"]
    return ramp.outputs["Result"], tex.outputs["Color"], normal


def multiply(nodes, links, a, b):
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    links.new(a, mix.inputs[6])
    links.new(b, mix.inputs[7])
    return mix.outputs[2]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def basis(axis):
    """Rotation that turns Z into `axis`"""
    return axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()


def angles(segs):
    return [2 * math.pi * i / segs for i in range(segs)]


def lathe(bm, profile, segs, matrix, mat=0, cap_bottom=True, cap_top=True, smooth=False):
    """Solid of revolution around local Z. profile: [(radius, z), ...] bottom to top"""
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new(matrix @ Vector((r * math.cos(a), r * math.sin(a), z))) for a in angles(segs)])
    for k in range(len(rings) - 1):
        lo, hi = rings[k], rings[k + 1]
        for i in range(segs):
            j = (i + 1) % segs
            f = bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
            f.material_index = mat
            f.smooth = smooth
    if cap_bottom:
        bm.faces.new(list(reversed(rings[0]))).material_index = mat
    if cap_top:
        bm.faces.new(rings[-1]).material_index = mat


def rod(bm, a, b, r1, r2=None, segs=8, mat=0, caps=True):
    a, b = Vector(a), Vector(b)
    d = b - a
    lathe(bm, [(r1, 0.0), (r2 if r2 is not None else r1, d.length)], segs, Matrix.Translation(a) @ basis(d), mat, caps, caps)


def ellipsoid(bm, center, radii, mat=0, segs=16, rings=10, shape=None):
    """An ellipsoid; shape(x, y, z) -> (x, y, z) bends the unit sphere's points before they are scaled"""
    c = Vector(center)

    def point(u, v):
        phi = math.pi * v - math.pi / 2
        a = 2 * math.pi * u
        p = (math.cos(phi) * math.cos(a), math.cos(phi) * math.sin(a), math.sin(phi))
        if shape:
            p = shape(*p)
        return c + Vector((p[0] * radii[0], p[1] * radii[1], p[2] * radii[2]))

    faces = surface(bm, point, segs, rings, mat=mat, closed_u=True)
    orient(faces, lambda _f: c)


def surface(bm, point_at, cols, rows, uv_of=None, mat=0, closed_u=False, smooth=True):
    """A grid of faces through point_at(u, v), u and v in 0..1; uv_of(point) gives each corner's UV. Corners that
    meet (a pole, a tip) are welded. Returns the faces"""
    uv = bm.loops.layers.uv.verify()
    ncols = cols if closed_u else cols + 1
    verts = [[bm.verts.new(point_at(i / cols, j / rows)) for i in range(ncols)] for j in range(rows + 1)]
    made = []
    for j in range(rows):
        for i in range(cols):
            k = (i + 1) % ncols
            quad = [verts[j][i], verts[j][k], verts[j + 1][k], verts[j + 1][i]]
            uniq = []
            for v in quad:
                if not uniq or (uniq[-1].co - v.co).length > 1e-5:
                    uniq.append(v)
            if (uniq[0].co - uniq[-1].co).length <= 1e-5:
                uniq.pop()
            if len(uniq) < 3:
                continue
            f = bm.faces.new(uniq)
            f.material_index = mat
            f.smooth = smooth
            if uv_of:
                for loop in f.loops:
                    loop[uv].uv = uv_of(loop.vert.co)
            made.append(f)
    bmesh.ops.remove_doubles(bm, verts=[v for row in verts for v in row], dist=1e-5)
    return [f for f in made if f.is_valid]


def orient(faces, inside):
    """Turns each face to look away from inside(face), a point within the body it bounds, so smooth shading is right"""
    for f in faces:
        f.normal_update()
        if f.normal.dot(f.calc_center_median() - inside(f)) < 0:
            f.normal_flip()


def polygon(bm, points, mat=0):
    f = bm.faces.new([bm.verts.new(Vector(p)) for p in points])
    f.material_index = mat
    return f




# ---------------------------------------------------------------------------
# Serpent materials
# ---------------------------------------------------------------------------


def scales_material(name, stage):
    """Teal scales with dark edges (a Voronoi pattern), a pale belly, over leathery wrinkles; blood in patches as it
    is hurt, and the colour drained out of it when it is dead"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.38
    coord = nodes.new("ShaderNodeTexCoord")
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = SCALE_SIZE
    links.new(coord.outputs["Object"], vor.inputs["Vector"])
    edge = nodes.new("ShaderNodeMapRange")
    edge.clamp = True
    edge.inputs["From Min"].default_value = 0.02
    edge.inputs["From Max"].default_value = 0.1
    links.new(vor.outputs["Distance"], edge.inputs["Value"])
    scale_mix = nodes.new("ShaderNodeMix")
    scale_mix.data_type = "RGBA"
    links.new(edge.outputs["Result"], scale_mix.inputs[0])
    scale_mix.inputs[6].default_value = linear(COLORS["edge"])
    scale_mix.inputs[7].default_value = linear(COLORS["body"])
    # The belly: lighter below the body's middle
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Object"], sep.inputs["Vector"])
    belly = nodes.new("ShaderNodeMapRange")
    belly.clamp = True
    belly.inputs["From Min"].default_value = 0.2
    belly.inputs["From Max"].default_value = -1.6
    links.new(sep.outputs["Z"], belly.inputs["Value"])
    belly_mix = nodes.new("ShaderNodeMix")
    belly_mix.data_type = "RGBA"
    links.new(belly.outputs["Result"], belly_mix.inputs[0])
    links.new(scale_mix.outputs[2], belly_mix.inputs[6])
    belly_mix.inputs[7].default_value = linear(COLORS["belly"])
    shade, _, normal = grain(nodes, links, "leather_white", coord.outputs["Object"], SKIN_TILE, 0.7, 1.15)
    color = multiply(nodes, links, belly_mix.outputs[2], shade)
    if stage["blood"] > 0:
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 0.6
        noise.inputs["Detail"].default_value = 6.0
        links.new(coord.outputs["Object"], noise.inputs["Vector"])
        ramp = nodes.new("ShaderNodeMapRange")
        ramp.clamp = True
        low = 0.72 - 0.4 * stage["blood"]
        ramp.inputs["From Min"].default_value = low
        ramp.inputs["From Max"].default_value = low + 0.05
        ramp.inputs["To Max"].default_value = 0.85
        links.new(noise.outputs["Fac"], ramp.inputs["Value"])
        blood = nodes.new("ShaderNodeMix")
        blood.data_type = "RGBA"
        links.new(ramp.outputs["Result"], blood.inputs[0])
        links.new(color, blood.inputs[6])
        blood.inputs[7].default_value = linear(COLORS["wound"])
        color = blood.outputs[2]
    if stage["pale"] > 0:
        hsv = nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = 1 - stage["pale"]
        hsv.inputs["Value"].default_value = 1 + stage["pale"] * 0.4
        links.new(color, hsv.inputs["Color"])
        color = hsv.outputs["Color"]
    links.new(color, bsdf.inputs["Base Color"])
    if normal is not None:
        links.new(normal, bsdf.inputs["Normal"])
    m.diffuse_color = linear(COLORS["body"])
    return m


MATERIAL_ORDER = ("scales", "fin", "bone", "eye", "pupil", "lid", "teeth", "mouth", "wound", "shaft", "iron")


def make_materials(stage):
    fin = plain("SerpentFin", COLORS["fin"], rough=0.5)
    fin.node_tree.nodes.get("Principled BSDF").inputs["Subsurface Weight"].default_value = 0.2
    if stage["pale"] > 0:
        fin.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = linear(0xB88A70)
    return {
        "scales": scales_material("SerpentScales", stage),
        "fin": fin,
        "bone": plain("SerpentBone", COLORS["bone"], rough=0.6),
        "eye": plain("SerpentEye", COLORS["eye"], rough=0.15),
        "pupil": plain("SerpentPupil", COLORS["pupil"], rough=0.2),
        "lid": plain("SerpentLid", COLORS["lid"], rough=0.6),
        "teeth": plain("SerpentTeeth", COLORS["teeth"], rough=0.35),
        "mouth": plain("SerpentMouth", COLORS["mouth"], rough=0.5),
        "wound": plain("SerpentWound", COLORS["wound"], rough=0.35),
        "shaft": plain("HarpoonShaft", COLORS["shaft"], rough=0.8),
        "iron": plain("HarpoonIron", COLORS["iron"], rough=0.45, metal=0.7),
    }


def mat(name):
    return MATERIAL_ORDER.index(name)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------


def cone(bm, base, tip, r, m, segs=6):
    rod(bm, base, tip, r, 0.01, segs=segs, mat=m)


def membrane(bm, points, m):
    """A fin's skin between its spines: one face each side, so it shows from both"""
    f = polygon(bm, points, mat=m)
    f.smooth = False
    g = polygon(bm, list(reversed(points)), mat=m)
    g.smooth = False


def dorsal_fin(bm, x0, x1, base_z, height, spines, torn):
    """Spines leaning back over the ridge with orange skin between them; torn: share of the skin left"""
    tips = []
    for k in range(spines):
        t = k / (spines - 1)
        x = x0 + (x1 - x0) * t
        h = height * (1 - 0.35 * t)
        base = Vector((x, 0, base_z))
        tip = Vector((x - 0.9 * h * 0.45, 0, base_z + h))
        rod(bm, base, tip, 0.13, 0.03, segs=5, mat=mat("bone"))
        tips.append((base, tip))
    for (b0, t0), (b1, t1) in zip(tips, tips[1:]):
        # The skin reaches a share of the way up; torn fins in ragged steps
        k0 = torn * (0.92 if torn > 0.9 else 0.75 + 0.2 * math.sin(b0.x * 7))
        k1 = torn * (0.92 if torn > 0.9 else 0.7 + 0.2 * math.sin(b1.x * 5))
        membrane(bm, [b0, b1, b1.lerp(t1, k1), b0.lerp(t0, k0)], mat("fin"))


def piece(bm, length=PIECE_LENGTH, radius=BODY_RADIUS, taper=0.0):
    """A piece of the body: an ellipsoid along x with a low ridge of knobs down its back. taper: how much thinner its
    back end is (the tail)"""

    def shape(x, y, z):
        k = 1 - taper * max(0.0, -x) ** 1.5
        return x, y * k, z * k

    ellipsoid(bm, (0, 0, 0), (length, radius, radius * 0.97), mat=mat("scales"), segs=20, rings=12, shape=shape)
    for x in (-1.6, 0.0, 1.6):
        if abs(x) < length * 0.8:
            k = 1 - taper * max(0.0, -x / length) ** 1.5
            cone(bm, Vector((x, 0, radius * 0.9 * k)), Vector((x - 0.25, 0, radius * 0.9 * k + 0.55)), 0.28, mat("scales"))


def build_segment(bm, stage):
    piece(bm)


def build_fin(bm, stage):
    piece(bm)
    dorsal_fin(bm, 1.9, -1.9, BODY_RADIUS * 0.85, 2.6, 4, stage["fin"])


def build_harpooned(bm, stage):
    piece(bm)
    at = Vector((0.4, 1.0, BODY_RADIUS * 0.82))
    d = Vector((-0.5, 0.45, 0.75)).normalized()
    rod(bm, at - d * 0.6, at + d * 4.2, 0.12, 0.1, segs=6, mat=mat("shaft"))
    rod(bm, at - d * 0.1, at + d * 0.5, 0.17, 0.14, segs=6, mat=mat("iron"))
    pts = [at + Vector((math.cos(a) * 0.9, math.sin(a) * 0.7, 0.12)) for a in angles(9)]
    polygon(bm, pts, mat=mat("wound"))


def build_tail(bm, stage):
    piece(bm, length=3.4, radius=BODY_RADIUS * 0.8, taper=0.55)
    torn = stage["fin"]
    # The tail's fin, upright: spines fanning back from the tip of the tail
    root = Vector((-2.6, 0, 0.2))
    tips = [root + Vector((-3.6 * math.cos(a), 0, 3.0 * math.sin(a))) for a in (1.0, 0.45, -0.05, -0.55, -1.0)]
    for tip in tips:
        rod(bm, root, tip, 0.14, 0.03, segs=5, mat=mat("bone"))
    for t0, t1 in zip(tips, tips[1:]):
        membrane(bm, [root, root.lerp(t0, 0.95 * torn), root.lerp(t1, 0.95 * torn)], mat("fin"))


def build_head(bm, bm_jaw, stage):
    """The head in its joint's frame, from where the neck ends forward: a broad skull, a long snout with fangs along
    it, yellow eyes under heavy brows (shut when dead), two horns sweeping back and a crest of spines down the neck"""

    def snout_shape(x, y, z):
        f = max(0.0, x)
        squeeze = 1 - 0.35 * f**2
        return x, y * squeeze, (z * 0.6 if z < 0 else z) * squeeze

    ellipsoid(bm, (1.9, 0, 0.6), (2.9, 2.45, 2.15), mat=mat("scales"), segs=20, rings=12)
    ellipsoid(bm, (4.6, 0, 0.05), (2.3, 1.55, 1.15), mat=mat("scales"), segs=16, rings=10, shape=snout_shape)
    # Fangs down the sides of the snout, longest at the front
    for k in range(5):
        x = 3.3 + k * 0.6
        for s in (1, -1):
            y = s * (1.45 - 0.12 * k)
            cone(bm, Vector((x, y, -0.55)), Vector((x + 0.08, y * 0.98, -1.0 - 0.12 * k)), 0.14 + 0.02 * k, mat("teeth"), 5)
    # Nostrils
    for s in (1, -1):
        ellipsoid(bm, (6.3, s * 0.45, 0.75), (0.25, 0.16, 0.12), mat=mat("pupil"), segs=6, rings=4)
    # Eyes under the brows
    for s in (1, -1):
        if stage["dead"]:
            ellipsoid(bm, (3.25, s * 1.55, 1.3), (0.62, 0.42, 0.42), mat=mat("lid"), segs=10, rings=6)
        else:
            ellipsoid(bm, (3.25, s * 1.55, 1.3), (0.6, 0.42, 0.48), mat=mat("eye"), segs=10, rings=6)
            ellipsoid(bm, (3.4, s * 1.85, 1.3), (0.1, 0.12, 0.4), mat=mat("pupil"), segs=6, rings=4)
        ellipsoid(bm, (3.0, s * 1.45, 1.85), (0.9, 0.45, 0.32), mat=mat("lid"), segs=10, rings=6)
    # Horns: two curved spikes back from the top of the skull
    for s in (1, -1):
        a = Vector((1.0, s * 1.2, 2.2))
        b = Vector((-0.9, s * 1.55, 3.4))
        c = Vector((-2.6, s * 1.7, 3.9))
        rod(bm, a, b, 0.42, 0.28, segs=7, mat=mat("bone"))
        rod(bm, b, c, 0.28, 0.03, segs=7, mat=mat("bone"))
    dorsal_fin(bm, 0.4, -3.4, 2.3, 2.3, 5, stage["fin"])

    # The jaw, in its own joint's frame: hinged under the skull, its top the mouth's red inside, fangs along it
    jl, jw, jd = 1.95, 1.3, 0.7

    def jaw_shape(x, y, z):
        f = max(0.0, x)
        squeeze = 1 - 0.35 * f**2
        return x, y * squeeze, min(z, 0.0)

    ellipsoid(bm_jaw, (jl, 0, 0), (jl, jw, jd), mat=mat("scales"), segs=14, rings=8, shape=jaw_shape)
    mouth = [Vector((jl + jl * 0.9 * math.cos(a), jw * 0.82 * math.sin(a) * (1 - 0.3 * max(0.0, math.cos(a)) ** 2), 0.03)) for a in angles(14)]
    polygon(bm_jaw, mouth, mat=mat("mouth"))
    for k in range(4):
        x = 1.2 + k * 0.6
        for s in (1, -1):
            y = s * (1.05 - 0.1 * k)
            cone(bm_jaw, Vector((x, y, 0.0)), Vector((x + 0.05, y, 0.45 + 0.08 * k)), 0.12, mat("teeth"), 5)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def new_bm():
    bm = bmesh.new()
    bm.loops.layers.uv.verify()
    return bm


def mesh_object(coll, name, bm, mats, parent):
    bm.normal_update()
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for key in MATERIAL_ORDER:
        mesh.materials.append(mats[key])
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    obj.parent = parent
    return obj


def joint(coll, name, parent, location=(0.0, 0.0, 0.0)):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "SPHERE"
    obj.empty_display_size = 0.4
    coll.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.rotation_mode = "XYZ"
    return obj


def key(obj, frame, rotation):
    obj.rotation_euler = rotation
    obj.keyframe_insert("rotation_euler", frame=frame)


def show_only_at(objects, frames, every):
    """Keys hide_render so the objects render only at their part's frames"""
    for obj in objects:
        for frame in every:
            obj.hide_render = frame not in frames
            obj.keyframe_insert("hide_render", frame=frame)


def clear_previous():
    coll = bpy.data.collections.get("Ship")
    if coll:
        for obj in list(coll.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(coll)
    for block in (bpy.data.materials, bpy.data.meshes, bpy.data.images, bpy.data.actions):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def build(damage=None):
    """damage: the stage (see DAMAGE_STAGES); by default the scene's "damage" property, or 0"""
    scene = bpy.context.scene
    if damage is None:
        damage = int(scene.get("damage", 0))
    damage = damage if damage in DAMAGE_STAGES else 0
    stage = DAMAGE_STAGES[damage]
    scene["damage"] = damage
    clear_previous()
    coll = bpy.data.collections.new("Ship")
    scene.collection.children.link(coll)
    mats = make_materials(stage)

    # render_sprites.py turns the object named "Ship": every part turns with it
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 6
    coll.objects.link(root)

    anims = animations(damage)
    frames = {name: [spec["start"] + k for k in range(spec["frames"])] for name, spec in anims.items()}
    every = sorted({f for fs in frames.values() for f in fs})

    head = joint(coll, "Joint.Head", root)
    head.scale = (HEAD_SIZE, HEAD_SIZE, HEAD_SIZE)
    jaw = joint(coll, "Joint.Jaw", head, (JAW_HINGE[0], 0, JAW_HINGE[1]))
    bm, bm_jaw = new_bm(), new_bm()
    build_head(bm, bm_jaw, stage)
    head_objects = [mesh_object(coll, "Head", bm, mats, head), mesh_object(coll, "Jaw", bm_jaw, mats, jaw)]
    show_only_at(head_objects, frames["head"] + frames.get("bite", []), every)

    for name, builder in (("segment", build_segment), ("fin", build_fin), ("harpoon", build_harpooned), ("tail", build_tail)):
        bm = new_bm()
        builder(bm, stage)
        show_only_at([mesh_object(coll, name.capitalize(), bm, mats, root)], frames[name], every)

    # The head breathes, its jaw working a little; then the bite: it rears, the mouth wide, and snaps shut striking
    for k, open_deg in enumerate((0, 4, 8, 4)):
        f = frames["head"][k] if not stage["dead"] else None
        if f is not None:
            key(head, f, (0, 0, 0))
            key(jaw, f, (0, math.radians(open_deg), 0))
    if stage["dead"]:
        key(head, DEAD_FRAME, (0, math.radians(8), 0))
        key(jaw, DEAD_FRAME, (0, math.radians(30), 0))
    else:
        # prettier-ignore
        bite = [(18, -6), (48, -12), (60, -14), (0, 6), (0, 3), (10, 0)]  # jaw open, head pitch (+ down), degrees
        for f, (open_deg, pitch) in zip(frames["bite"], bite):
            key(head, f, (0, math.radians(pitch), 0))
            key(jaw, f, (0, math.radians(open_deg), 0))
    for name in ("segment", "fin", "harpoon", "tail"):
        key(head, frames[name][0], (0, 0, 0))
        key(jaw, frames[name][0], (0, 0, 0))

    scene.frame_start = 1
    scene.frame_end = 4
    scene.timeline_markers.clear()
    for name, fs in frames.items():
        scene.timeline_markers.new(name, frame=fs[0])
    scene.frame_set(every[0])
    return root


if __name__ == "__main__":
    build()

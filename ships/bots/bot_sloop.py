"""
The bots' sloops, built from code: one gaff-rigged mast with a jib (or two) on a bowsprit, a flush deck with a low
bulwark. Each ship's folder has a short build.py that describes its hull, rig, guns and looks (a SPEC) and calls
build() here: ships/bots/merchantSloop/ (a trader: a square topsail, a deckhouse, deck cargo, swivel guns) and
ships/bots/smugglerSloop/ (black, raked, dark sails, a gaff topsail and two jibs, a cannon a side, no lights).

Run in Blender: open the ship's .blend, Scripting tab -> Open -> its build.py -> Run Script. It rebuilds the "Ship"
collection: the look picked by the scene's "variant" property (when the ship has several), the damage stage by its
"damage" property (0-4, see DAMAGE_STAGES). render_stages.py renders them all.

Damage: each stage keeps the damage of the one before and adds to it: 1 soot, shot holes in the hull and the sails,
some deck cargo gone; 2 more holes, torn sails, the bulwark broken in places, a shredded flag; 3 charred wood and sails
burnt from the foot (the game adds the fire); 4 the mast snapped and over the port side with its sails on the water,
listing to port, low in the water, wreckage alongside (the game animates the sinking).

Axes and scale match the game: 1 Blender unit = 1 game unit, the bow points to +X, port side to +Y, Z up,
waterline at Z = 0.

Textures: scanned CC0 wood and metal from Poly Haven (polyhaven.com), shared by all ships in
blender-assets/textures/polyhaven/ and downloaded there on the first run; the sails and flags are generated into
the ship's textures/ folder. They are linked by relative paths, not packed.
"""

import json
import math
import os
import urllib.request

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

WALL = 0.26  # hull planking thickness
BRACE = 0.42  # radians: the fore-and-aft sails are sheeted out to port, so they read from the bow and the stern too
SQUARE_BRACE = 0.3  # radians the square topsail's yard is turned
HULL_TILE = 8.0  # real-world size of one texture tile, in game units: sets the plank width on the model
PLANK_STRETCH = 2.2  # hull planks are long boards, so the tile is stretched along the hull
DECK_TILE = 4.5
SPAR_TILE = 4.5

# Colors (sRGB)
COLORS = {
    "iron": 0x34343A,
    "brass": 0xC9973F,
    "rope": 0x8E6B44,
    "hole": 0x1C130D,
    "soot": 0x1E1712,
    "char": 0x1A130E,
    "burnt": 0x2B1E15,
    "glass": 0xFFCF73,
    "grate": 0x3A2717,
    "burlap": 0xB89B68,
    "tarp": 0x5D5848,
    "white": 0xF2EEE4,
}

# What each damage stage does to the model. Holes, bulwark breaks and debris are taken from the lists below in order,
# so every stage keeps the damage of the previous one and adds to it. cargo: the share of the deck cargo still aboard;
# flag: what is left of the flags
# prettier-ignore
DAMAGE_STAGES = {
    0: dict(soot=0.0, char=0.0, hull_holes=0, sail_holes=0, sail_tear=False, sail_burn=0.0, rail_breaks=0, cargo=1.0,
            flag=1.0, lantern=True, mast_broken=False, list_deg=0.0, sink=0.0, debris=0),
    1: dict(soot=0.3, char=0.0, hull_holes=3, sail_holes=4, sail_tear=False, sail_burn=0.0, rail_breaks=0, cargo=0.85,
            flag=0.8, lantern=True, mast_broken=False, list_deg=0.0, sink=0.0, debris=0),
    2: dict(soot=0.5, char=0.0, hull_holes=6, sail_holes=8, sail_tear=True, sail_burn=0.0, rail_breaks=2, cargo=0.65,
            flag=0.55, lantern=False, mast_broken=False, list_deg=1.5, sink=0.2, debris=1),
    3: dict(soot=0.65, char=0.3, hull_holes=9, sail_holes=11, sail_tear=True, sail_burn=0.36, rail_breaks=3, cargo=0.45,
            flag=0.3, lantern=False, mast_broken=False, list_deg=3.5, sink=0.45, debris=3),
    4: dict(soot=0.75, char=0.45, hull_holes=12, sail_holes=14, sail_tear=True, sail_burn=0.5, rail_breaks=5, cargo=0.3,
            flag=0.0, lantern=False, mast_broken=True, list_deg=9.0, sink=1.0, debris=9),
}
# Shot holes in the hull: x, height, side (+1 port, -1 starboard), radius. A sprite shows about 3 pixels per unit, so
# a hole much smaller than a unit is lost
HULL_HOLES = [
    (-4.0, 1.9, -1, 0.9), (6.0, 1.6, 1, 1.0), (-9.5, 2.2, 1, 0.85), (9.5, 2.0, -1, 0.9), (1.0, 1.3, 1, 1.05),
    (-7.0, 1.2, -1, 1.0), (11.0, 1.5, 1, 0.85), (3.5, 2.4, -1, 0.8), (-11.5, 1.6, -1, 0.9), (-2.0, 2.5, 1, 0.8),
    (7.5, 1.1, -1, 1.0), (-5.0, 2.3, 1, 0.95),
]
# Holes in a sail, in its texture: u across, v up, radius. Each sail picks its own share of them (a seed per sail)
SAIL_HOLES = [
    (0.3, 0.58, 0.05), (0.72, 0.33, 0.045), (0.55, 0.82, 0.035), (0.16, 0.25, 0.055), (0.86, 0.63, 0.04),
    (0.44, 0.42, 0.065), (0.65, 0.6, 0.05), (0.25, 0.86, 0.04), (0.8, 0.16, 0.06), (0.1, 0.5, 0.05),
    (0.38, 0.2, 0.045), (0.92, 0.4, 0.035), (0.58, 0.3, 0.05), (0.2, 0.68, 0.045),
]
SAIL_HOLE_PICKS = (
    (0, 5, 3, 8, 11, 1, 9, 6, 13, 2, 10, 4, 12, 7),
    (6, 1, 12, 4, 9, 0, 13, 3, 7, 10, 2, 11, 5, 8),
    (1, 9, 4, 12, 0, 7, 11, 3, 13, 6, 2, 10, 8, 5),
    (10, 3, 7, 0, 13, 5, 8, 2, 12, 9, 4, 1, 11, 6),
)
# Chunks broken out of the bulwark: x, side, half-length, depth below the rail
RAIL_BREAKS = [(-4.0, 1, 1.4, 0.85), (6.0, -1, 1.2, 0.75), (-9.0, -1, 1.1, 0.7), (2.5, 1, 1.0, 0.6), (9.5, 1, 0.9, 0.65)]
MAST_BREAK = 3.2  # height above the deck where the mast snaps in stage 4
WEAR_SEED = 4.4  # soot and char blotches stay in the same places from stage to stage, they only grow

# The ship being built: its SPEC (see merchantSloop/build.py), set by build()
P = {}
TEX_DIR = ""
PH_DIR = ""


def base_dir():
    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    return os.environ.get("SHIP_OUT") or os.getcwd()


def assets_root(ship_dir):
    """blender-assets itself: the parent of the "ships" folder this ship lives in"""
    path = os.path.abspath(ship_dir)
    while os.path.basename(path) != "ships":
        parent = os.path.dirname(path)
        if parent == path:
            return os.path.abspath(ship_dir)  # not inside ships/, e.g. a test run: keep everything together
        path = parent
    return os.path.dirname(path)


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


def hull_point(x, z, side):
    """A point on the side and its outward normal. side = +1 port, -1 starboard"""
    e = 0.02
    w = half_width(x, z)
    dwdx = (half_width(x + e, z) - half_width(x - e, z)) / (2 * e)
    dwdz = (half_width(x, z + e) - half_width(x, z - e)) / (2 * e)
    n = Vector((-dwdx, side, -dwdz)).normalized()
    return Vector((x, side * w, z)), n


def inner_width(x, z):
    return max(0.0, half_width(x, z) - WALL * 1.1)


def side_frame(n):
    """Tangent along the hull, outward normal and 'up' on the hull surface"""
    t = Vector((1, 0, 0))
    t = (t - n * t.dot(n)).normalized()
    up = Vector((0, 0, 1))
    b = (up - n * up.dot(n) - t * up.dot(t)).normalized()
    return t, n, b


def keep(items, share):
    """The first share of a list: what is left of the catch at a damage stage"""
    return items[: int(round(len(items) * share))]


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------


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


def add_wear(nt, color_out, soot, char):
    """Soot blotches and charred patches over a material. Object coordinates are shared by all parts,
    so a blotch continues across neighbouring pieces"""
    if soot <= 0 and char <= 0:
        return color_out
    nodes, links = nt.nodes, nt.links
    coord = nodes.new("ShaderNodeTexCoord")

    def blotches(scale, amount, softness):
        noise = nodes.new("ShaderNodeTexNoise")
        noise.noise_dimensions = "4D"
        noise.inputs["W"].default_value = WEAR_SEED + scale
        noise.inputs["Scale"].default_value = scale
        noise.inputs["Detail"].default_value = 6.0
        noise.inputs["Roughness"].default_value = 0.62
        links.new(coord.outputs["Object"], noise.inputs["Vector"])
        # The more damage, the lower the threshold and the larger the blotches
        ramp = nodes.new("ShaderNodeMapRange")
        ramp.clamp = True
        low = 0.66 - 0.32 * amount
        ramp.inputs["From Min"].default_value = low
        ramp.inputs["From Max"].default_value = low + softness
        links.new(noise.outputs["Fac"], ramp.inputs["Value"])
        return ramp.outputs["Result"]

    for amount, color, scale, softness, strength in ((soot, "soot", 0.4, 0.16, 0.9), (char, "char", 0.7, 0.1, 0.8)):
        if amount <= 0:
            continue
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MIX"
        fac = nodes.new("ShaderNodeMath")
        fac.operation = "MULTIPLY"
        fac.inputs[1].default_value = strength * min(1.0, amount * 2.5)
        links.new(blotches(scale, amount, softness), fac.inputs[0])
        links.new(fac.outputs["Value"], mix.inputs[0])
        links.new(color_out, mix.inputs[6])
        mix.inputs[7].default_value = linear(COLORS[color])
        color_out = mix.outputs[2]
    return color_out


def scanned(name, asset, tint=None, paint=True, hue=0.5, saturation=1.0, value=1.0, normal=0.6, metal=0.0, rough_add=0.0, wear=(0.0, 0.0)):
    """A material from a Poly Haven texture set.
    tint + paint: the color of paint over the wood, its brightness follows the grain of the texture.
    tint without paint: the texture is multiplied by the color (rust stains on dark iron)"""
    m = new_material(name)
    nt = m.node_tree
    nodes, links = nt.nodes, nt.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Specular IOR Level"].default_value = 0.3

    diff = nodes.new("ShaderNodeTexImage")
    diff.image = polyhaven(asset, "diff")
    hsv = nodes.new("ShaderNodeHueSaturation")
    hsv.inputs["Hue"].default_value = hue  # 0.5 keeps the hue, above it shifts towards yellow
    hsv.inputs["Saturation"].default_value = saturation
    hsv.inputs["Value"].default_value = value
    links.new(diff.outputs["Color"], hsv.inputs["Color"])
    color_out = hsv.outputs["Color"]

    if tint is not None:
        mul = nodes.new("ShaderNodeMix")
        mul.data_type = "RGBA"
        mul.blend_type = "MULTIPLY"
        mul.inputs[0].default_value = 1.0
        mul.inputs[6].default_value = linear(tint)
        if paint:
            bw = nodes.new("ShaderNodeRGBToBW")
            links.new(color_out, bw.inputs["Color"])
            grain = nodes.new("ShaderNodeMapRange")
            grain.clamp = True
            grain.inputs["From Min"].default_value = 0.02
            grain.inputs["From Max"].default_value = 0.35
            grain.inputs["To Min"].default_value = 0.6
            grain.inputs["To Max"].default_value = 1.2
            links.new(bw.outputs["Val"], grain.inputs["Value"])
            links.new(grain.outputs["Result"], mul.inputs[7])
        else:
            links.new(color_out, mul.inputs[7])
        color_out = mul.outputs[2]
    color_out = add_wear(nt, color_out, *wear)
    links.new(color_out, bsdf.inputs["Base Color"])

    rough_img = polyhaven(asset, "rough")
    if rough_img is None:
        bsdf.inputs["Roughness"].default_value = min(1.0, 0.75 + rough_add)
    else:
        rough = nodes.new("ShaderNodeTexImage")
        rough.image = rough_img
        if rough_add:
            add = nodes.new("ShaderNodeMath")
            add.operation = "ADD"
            add.use_clamp = True
            add.inputs[1].default_value = rough_add
            links.new(rough.outputs["Color"], add.inputs[0])
            links.new(add.outputs["Value"], bsdf.inputs["Roughness"])
        else:
            links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    nor_img = polyhaven(asset, "nor_gl")
    if nor_img is not None:
        nor = nodes.new("ShaderNodeTexImage")
        nor.image = nor_img
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = normal
        links.new(nor.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])

    m.diffuse_color = linear(tint) if tint is not None else (0.35, 0.2, 0.1, 1)
    return m


def plain(name, color, rough=0.8, metal=0.0, emission=0.0, two_sided=False, image=None, sheen=0.0):
    m = new_material(name)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = linear(color)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Sheen Weight"].default_value = sheen
    if image is not None:
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        m.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if emission > 0:
        bsdf.inputs["Emission Color"].default_value = linear(color)
        bsdf.inputs["Emission Strength"].default_value = emission
    m.diffuse_color = linear(color)
    m.use_backface_culling = not two_sided
    return m


def see_through(m, nodes, links, surface, alpha):
    """Cuts a material out where an image's alpha is 0: holes in a sail, the gaps between a net's twine"""
    out = nodes.get("Material Output")
    holes = nodes.new("ShaderNodeMixShader")
    clear = nodes.new("ShaderNodeBsdfTransparent")
    links.new(alpha, holes.inputs["Fac"])
    links.new(clear.outputs["BSDF"], holes.inputs[1])
    links.new(surface, holes.inputs[2])
    links.new(holes.outputs["Shader"], out.inputs["Surface"])
    m.use_backface_culling = False


def cloth(name, image, color):
    """Sail canvas: some sunlight shines through it, and a fine bump keeps it from looking like plastic"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.95
    bsdf.inputs["Specular IOR Level"].default_value = 0.15
    bsdf.inputs["Sheen Weight"].default_value = 0.3
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 4.0
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    translucent = nodes.new("ShaderNodeBsdfTranslucent")
    links.new(tex.outputs["Color"], translucent.inputs["Color"])
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.22
    links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(translucent.outputs["BSDF"], mix.inputs[2])
    # Holes and burnt parts of the sail are cut out by the texture's alpha
    see_through(m, nodes, links, mix.outputs["Shader"], tex.outputs["Alpha"])
    m.diffuse_color = linear(color)
    return m


# ---------------------------------------------------------------------------
# Geometry helpers (bmesh)
# ---------------------------------------------------------------------------


class Parts:
    """One bmesh per material; each becomes its own object at the end"""

    def __init__(self):
        self.meshes = {}

    def __getitem__(self, key):
        if key not in self.meshes:
            bm = bmesh.new()
            bm.loops.layers.uv.verify()
            self.meshes[key] = bm
        return self.meshes[key]


def basis(axis):
    """Rotation that turns Z into `axis`"""
    return axis.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()


def lathe(bm, profile, segs, matrix, cap_bottom=True, cap_top=True, uv_along=None):
    """Solid of revolution around local Z. profile: [(radius, z), ...] bottom to top.
    uv_along: tile size; the texture's long axis then runs along the solid, wood grain along a mast"""
    uv = bm.loops.layers.uv.active
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new(matrix @ Vector((r * math.cos(a), r * math.sin(a), z))) for a in angles(segs)])
    for k in range(len(rings) - 1):
        lo, hi = rings[k], rings[k + 1]
        for i in range(segs):
            j = (i + 1) % segs
            f = bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
            if uv_along:
                z0, z1 = profile[k][1], profile[k + 1][1]
                corners = ((z0, i), (z0, i + 1), (z1, i + 1), (z1, i))
                for loop, (z, s) in zip(f.loops, corners):
                    # One plank of the tile wraps around the solid, so no seams show on a round spar
                    loop[uv].uv = (z / uv_along, 0.05 + 0.06 * s / segs)
    if cap_bottom:
        bm.faces.new(list(reversed(rings[0])))
    if cap_top:
        bm.faces.new(rings[-1])


def angles(segs):
    return [2 * math.pi * i / segs for i in range(segs)]


def rod(bm, a, b, r1, r2=None, segs=8, caps=True, uv_along=None):
    a, b = Vector(a), Vector(b)
    d = b - a
    m = Matrix.Translation(a) @ basis(d)
    lathe(bm, [(r1, 0.0), (r2 if r2 is not None else r1, d.length)], segs, m, caps, caps, uv_along)


def ball(bm, center, r, segs=8, squash=1.0):
    profile = [(r * math.sin(math.pi * k / 6) + 1e-4, -r * squash * math.cos(math.pi * k / 6)) for k in range(7)]
    lathe(bm, profile, segs, Matrix.Translation(Vector(center)), False, False)


def box(bm, center, size, axes=None):
    """A box centred at `center` with `size` along `axes` (three vectors)"""
    if axes is None:
        axes = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    rot = Matrix((axes[0], axes[1], axes[2])).transposed().to_4x4()
    m = Matrix.Translation(Vector(center)) @ rot @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)


def turned(rot):
    """Axes of a box turned by `rot` radians round Z"""
    return (Vector((math.cos(rot), math.sin(rot), 0)), Vector((-math.sin(rot), math.cos(rot), 0)), Vector((0, 0, 1)))


def polygon(bm, points, flip=False):
    verts = [bm.verts.new(Vector(p)) for p in points]
    if flip:
        verts.reverse()
    return bm.faces.new(verts)


def box_project_uvs(bm, tile, along_x=True):
    """Box mapping for faces without hand-made UVs. Planks run along X on sides and decks"""
    uv = bm.loops.layers.uv.active
    for f in bm.faces:
        if any(loop[uv].uv.length_squared > 0 for loop in f.loops):
            continue
        n = f.normal
        ax = max(range(3), key=lambda k: abs(n[k]))
        for loop in f.loops:
            c = loop.vert.co
            if ax == 2:  # top/bottom: planks along X
                loop[uv].uv = (c.x / tile, c.y / tile) if along_x else (c.y / tile, c.x / tile)
            elif ax == 1:  # facing ±Y: planks along X, stacked up
                loop[uv].uv = (c.x / tile, c.z / tile)
            else:  # facing ±X: planks along Y
                loop[uv].uv = (c.y / tile, c.z / tile)


def grid_surface(bm, point_at, cols, rows, uv_scale=(1.0, 1.0)):
    """A cols x rows grid; point_at(u, v) -> Vector, u, v in 0..1. UV = (u, v) times uv_scale. Collapsed corners are
    welded"""
    uv = bm.loops.layers.uv.active
    su, sv = uv_scale
    verts = [[bm.verts.new(point_at(i / cols, j / rows)) for i in range(cols + 1)] for j in range(rows + 1)]
    for j in range(rows):
        for i in range(cols):
            quad = [verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]]
            coords = [(i / cols, j / rows), ((i + 1) / cols, j / rows), ((i + 1) / cols, (j + 1) / rows), (i / cols, (j + 1) / rows)]
            uniq = []
            for v, c in zip(quad, coords):
                if not uniq or (uniq[-1][0].co - v.co).length > 1e-5:
                    uniq.append((v, c))
            if (uniq[0][0].co - uniq[-1][0].co).length <= 1e-5:
                uniq.pop()
            if len(uniq) < 3:
                continue
            f = bm.faces.new([v for v, _ in uniq])
            for loop, (_, c) in zip(f.loops, uniq):
                loop[uv].uv = (c[0] * su, c[1] * sv)
    bmesh.ops.remove_doubles(bm, verts=[v for row in verts for v in row], dist=1e-5)


# ---------------------------------------------------------------------------
# Sails
# ---------------------------------------------------------------------------


def sail_texture(name, color, size=512, seed=5, patches=(), band=None, stage=None, holes=()):
    """Canvas: vertical cloths of slightly different tone, stitched seams, doubled edges and a reef band, weave and
    weathering towards the foot. patches: (u0, v0, u1, v1, tone) squares sewn over old tears; band: (v0, v1, color) a
    stripe painted across. stage: a DAMAGE_STAGES entry, holes: which of SAIL_HOLES this sail gets (in the order they
    come); holes, a tear and a burnt foot are cut out through alpha"""
    rng = np.random.default_rng(seed)
    n = (np.arange(size) + 0.5) / size
    xs = n[None, :]
    ys = 1 - n[:, None]  # 0 = foot, 1 = head
    base = np.array(srgb(color))

    shade = np.ones((size, size))
    panels = 7
    cloth_ = np.clip((xs * panels).astype(int), 0, panels - 1)
    shade *= (1 + 0.05 * (rng.random(panels) - 0.5))[cloth_]
    shade *= 1 - 0.02 * (np.sin(np.arange(size)[None, :] * 2.2) ** 2)
    shade *= 1 - 0.015 * (np.sin(np.arange(size)[:, None] * 2.0) ** 2)
    shade *= 1 + 0.03 * (rng.random((size, size)) - 0.5)
    shade *= 1 - 0.08 * value_noise(size, 5, rng)
    shade *= 1 - 0.1 * np.clip(1 - ys / 0.3, 0, 1) ** 1.6 * (0.5 + value_noise(size, 12, rng))

    pos = (xs * panels) % 1
    overlap = (pos < 0.03) | (pos > 0.995)
    shade = np.where(overlap, shade * 0.94, shade)
    stitch = (np.abs(pos - 0.006) < 0.0025) | (np.abs(pos - 0.026) < 0.0025)
    dash = (np.arange(size)[:, None] % 5) < 3
    shade = np.where(stitch & dash, shade * 0.86, shade)
    band_ = np.abs(ys - 0.2) < 0.014
    shade = np.where(band_, shade * 0.94, shade)
    points = (np.abs(ys - 0.2) < 0.026) & (np.abs(((xs * 12) % 1) - 0.5) < 0.05)
    shade = np.where(points, shade * 0.8, shade)
    edge = np.minimum(np.minimum(xs, 1 - xs), np.minimum(ys, 1 - ys))
    shade = np.where(edge < 0.035, shade * 0.94, shade)
    shade = np.where(edge < 0.01, shade * 0.74, shade)
    rgb = base[None, None, :] * shade[..., None]

    if band is not None:
        v0, v1, band_color = band
        inside = (ys > v0) & (ys < v1)
        rgb = np.where(inside[..., None], np.array(srgb(band_color))[None, None, :] * shade[..., None], rgb)
    for u0, v0, u1, v1, tone in patches:
        # A square of newer or older canvas sewn over a repair, its seams a little darker
        inside = (xs > u0) & (xs < u1) & (ys > v0) & (ys < v1)
        rim = inside & ((xs < u0 + 0.012) | (xs > u1 - 0.012) | (ys < v0 + 0.012) | (ys > v1 - 0.012))
        rgb = np.where(inside[..., None], rgb * tone, rgb)
        rgb = np.where(rim[..., None], rgb * 0.82, rgb)

    alpha = np.ones((size, size))
    if stage is not None:
        rgb, alpha = damage_sail(rgb, alpha, xs, ys, stage, holes, np.random.default_rng(seed + 1))
    rgba = np.concatenate([np.clip(rgb, 0, 1), alpha[..., None]], axis=2)
    return save_image(name, rgba)


def damage_sail(rgb, alpha, xs, ys, stage, holes, rng):
    """Cuts holes with scorched rims, a torn corner and a burnt-away foot into a sail's texture"""
    size = rgb.shape[0]
    soot = np.array(srgb(COLORS["soot"]))
    char = np.array(srgb(COLORS["char"]))
    scorch = np.zeros((size, size))  # 0 clean .. 1 charred black
    cut = np.zeros((size, size), dtype=bool)
    ragged = value_noise(size, 30, rng)

    for i in holes[: stage["sail_holes"]]:
        u, v, r = SAIL_HOLES[i]
        dx, dy = xs - u, ys - v
        dist = np.sqrt(dx * dx + dy * dy)
        theta = np.arctan2(dy, dx)
        phase = rng.random() * 6.28
        edge = r * (1 + 0.28 * np.sin(5 * theta + phase) + 0.18 * np.sin(11 * theta + 2 * phase) + 0.25 * (ragged - 0.5))
        cut |= dist < edge
        scorch = np.maximum(scorch, np.clip(1 - (dist - edge) / (r * 0.9), 0, 1) ** 1.5)

    if stage["sail_tear"]:
        # The clew is ripped away: the bottom corner at the leech
        d = (1 - xs) + ys * 0.9
        edge = 0.2 + 0.05 * (ragged - 0.5) + 0.02 * np.sin(ys * 60)
        cut |= d < edge
        scorch = np.maximum(scorch, 0.35 * np.clip(1 - (d - edge) / 0.05, 0, 1))

    if stage["sail_burn"] > 0:
        # Fire ate the sail from the foot up: a ragged edge with a black band above it
        edge = stage["sail_burn"] + 0.08 * (ragged - 0.5) + 0.03 * np.sin(xs * 37 + rng.random() * 6)
        cut |= ys < edge
        scorch = np.maximum(scorch, np.clip(1 - (ys - edge) / 0.12, 0, 1) ** 1.2)

    # General grime from smoke, stronger on badly damaged sails
    grime = stage["soot"] * 0.35 * value_noise(size, 6, rng)
    rgb = rgb * (1 - grime[..., None]) + soot[None, None, :] * grime[..., None]
    rgb = rgb * (1 - scorch[..., None]) + (char * 0.6 + soot * 0.4)[None, None, :] * scorch[..., None]
    alpha = np.where(cut, 0.0, alpha)
    return rgb, alpha




# ---------------------------------------------------------------------------
# Hull shape
# ---------------------------------------------------------------------------


def x_bow(z):
    """The stem rakes forward as it rises"""
    return P["bow"] + P["stem_rake"] * (z - P["deck"])


def x_stern(z):
    """The transom rakes aft as it rises"""
    return P["stern"] - P["transom_rake"] * (z - P["deck"])


def section(z):
    """Width of the cross-section at height z (0..1): a round bilge, the sides falling in a little above it"""
    widest = P["deck"] - 0.8
    if z <= widest:
        t = (widest - z) / (widest - P["keel"])
        return max(0.0, 1 - t**2.2) ** 0.5
    return 1 - 0.006 * (z - widest) ** 2


def plan(x, z):
    """Half-width at height z depending on x: a fine bow, a long run and a narrower transom"""
    xs, xb = x_stern(z), x_bow(z)
    if x >= xb:
        return 0.0
    if x > 2:
        t = (x - 2) / (xb - 2)
        return P["beam"] * max(0.0, 1 - t * t) ** 0.6
    if x < -6:
        t = min(1.0, (-6 - x) / (-6 - xs))
        return P["beam"] * (1 - 0.42 * t**1.6)
    return P["beam"]


def half_width(x, z):
    return plan(x, z) * section(z)


def rail_z(x):
    """Top of the bulwark: the sheer rises to the bow, and less to the stern"""
    bow = smoothstep(2.0, P["bow"], x) ** 1.5
    stern = smoothstep(-4.0, P["stern"], x) ** 1.5
    return P["deck"] + P["bulwark"] + P["sheer_bow"] * bow + P["sheer_stern"] * stern


def rail_top(x, side, stage):
    """The bulwark with the chunks damage broke out of it: a ragged notch each"""
    z = rail_z(x)
    for bx, bside, half, depth in RAIL_BREAKS[: stage["rail_breaks"]]:
        if bside != side or abs(x - bx) >= half:
            continue
        k = 1 - abs(x - bx) / half
        z -= depth * min(1.0, k * 1.6) * (0.8 + 0.2 * math.sin(x * 17.0))
    return z


def gunwale(x, side, stage, out=0.0):
    """A point on top of the bulwark, `out` units outboard of it"""
    z = rail_top(x, side, stage)
    return Vector((x, side * (half_width(x, z) + out), z))


def mast_at(z):
    """x of the mast's middle at height z: a raked mast leans aft"""
    return P["mast_x"] - (z - P["deck"]) * P["rake"]


def braced(along, across, z, brace=None):
    """A point in a sail's frame (along = forward of the mast, across = to port), the sail sheeted out by BRACE"""
    b = BRACE if brace is None else brace
    c, s = math.cos(-b), math.sin(-b)
    return Vector((mast_at(z) + along * c - across * s, along * s + across * c, z))


# ---------------------------------------------------------------------------
# Textures and materials
# ---------------------------------------------------------------------------


def flag_texture(name, flag, size=128):
    """A flag: a field with a cross, a band, or a pirate's white skull over crossed bones"""
    n = (np.arange(size) + 0.5) / size
    xs = n[None, :] * np.ones((size, 1))
    ys = 1 - n[:, None] * np.ones((1, size))
    rgb = np.ones((size, size, 3)) * np.array(srgb(flag["field"]))
    mark = np.array(srgb(flag.get("mark", 0xFFFFFF)))
    kind = flag["kind"]
    if kind == "cross":
        cross = (np.abs(xs - 0.36) < 0.08) | (np.abs(ys - 0.5) < 0.11)
        rgb = np.where(cross[..., None], mark, rgb)
    elif kind == "band":
        rgb = np.where((np.abs(ys - 0.5) < 0.17)[..., None], mark, rgb)
    elif kind == "skull":
        u, v = (xs - 0.45) / 0.5, (ys - 0.56) / 0.5
        skull = (u * u + (v - 0.1) ** 2 * 1.3 < 0.16) | ((np.abs(u) < 0.22) & (v > -0.32) & (v < 0.0))
        eyes = ((u - 0.15) ** 2 + (v - 0.08) ** 2 < 0.012) | ((u + 0.15) ** 2 + (v - 0.08) ** 2 < 0.012)
        bones = ((np.abs((u - (v + 0.5)) / 1.41) < 0.05) | (np.abs((u + (v + 0.5)) / 1.41) < 0.05)) & (v < -0.25) & (v > -0.75)
        rgb = np.where(((skull & ~eyes) | bones)[..., None], mark, rgb)
    rgb = np.where((xs < 0.05)[..., None], rgb * 0.8, rgb)  # the hem along the hoist
    return save_image(name, np.concatenate([rgb, np.ones((size, size, 1))], axis=2))


def make_materials(look, stage, index, variant):
    wear = (stage["soot"], stage["char"])
    light_wear = (stage["soot"] * 0.6, stage["char"] * 0.5)
    damaged = stage["sail_holes"] > 0 or stage["sail_burn"] > 0 or stage["sail_tear"]
    hurt = stage if damaged else None
    name = P["name"] + (f"_{variant}" if variant else "")
    suffix = f"_d{index}" if damaged else ""

    def sail(kind, seed, picks, size=512):
        image = sail_texture(
            f"{name}_{kind}{suffix}", look["sail"], size=size, seed=seed, patches=look.get("sail_patches", ()),
            band=look.get("sail_band"), stage=hurt, holes=picks,
        )
        return cloth(f"{name}_{kind}", image, look["sail"])

    hull_set, hull_tint, hull_hsv = look["hull"]
    mats = {
        "main": sail("main", 5, SAIL_HOLE_PICKS[0]),
        "jib": sail("jib", 9, SAIL_HOLE_PICKS[1], 256),
        "topsail": sail("topsail", 7, SAIL_HOLE_PICKS[2], 256),
        "hull": scanned(f"{name}Hull", hull_set, tint=hull_tint, hue=hull_hsv[0], saturation=hull_hsv[1], value=hull_hsv[2], wear=wear),
        "stripe": scanned(f"{name}Stripe", "wood_planks", tint=look["stripe"], normal=0.4, wear=wear),
        "bottom": scanned(f"{name}Bottom", "black_painted_planks", value=0.85),
        "inner": scanned(f"{name}Inner", "weathered_planks", value=1.2, wear=wear),
        "deck": scanned(f"{name}Deck", "wood_planks", saturation=0.9, value=look.get("deck_value", 1.15), wear=wear),
        "spar": scanned(f"{name}Spar", "wood_planks", saturation=0.9, value=0.75, wear=light_wear),
        "barrel": scanned(f"{name}Barrel", "wooden_barrel", value=1.3, wear=light_wear),
        "crate": scanned(f"{name}Crate", "wood_planks", value=1.25, wear=light_wear),
        "iron": scanned(f"{name}Iron", "rusty_metal_02", tint=COLORS["iron"], paint=False, value=1.7, metal=0.5),
        "brass": plain(f"{name}Brass", COLORS["brass"], rough=0.35, metal=1.0),
        "rope": plain(f"{name}Rope", COLORS["rope"], rough=1.0),
        "grate": plain(f"{name}Grate", COLORS["grate"], rough=1.0),
        "burlap": plain(f"{name}Burlap", COLORS["burlap"], rough=1.0, sheen=0.3),
        "tarp": plain(f"{name}Tarp", COLORS["tarp"], rough=0.95, sheen=0.2),
        "glass": plain(f"{name}Glass", COLORS["glass"], rough=0.3, emission=1.5 if stage["lantern"] else 0.0),
        "lantern": plain(f"{name}Lantern", COLORS["glass"] if stage["lantern"] else COLORS["hole"], rough=0.3, emission=4.0 if stage["lantern"] else 0.0),
        "flag": plain(f"{name}Flag", 0xFFFFFF, rough=0.9, two_sided=True, image=flag_texture(f"{name}_flag", look["flag"])),
        "pennant": plain(f"{name}Pennant", look.get("pennant", 0xFFFFFF), rough=0.9, two_sided=True),
        "hole": plain(f"{name}ShotHole", COLORS["hole"], rough=1.0),
        "burnt": plain(f"{name}Burnt", COLORS["burnt"], rough=1.0),
    }
    return mats


# ---------------------------------------------------------------------------
# Hull and deck
# ---------------------------------------------------------------------------

HULL_COLS = 60


def hull_rows():
    d, k = P["deck"], P["keel"]
    return [k, k + 0.15, k * 0.6, k * 0.25, 0.0, 0.5, 1.2, d - 1.5, d - 0.95, d - 0.3, d]


def build_hull(mats, coll, stage):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.verify()
    us = [0.5 - 0.5 * math.cos(math.pi * i / HULL_COLS) for i in range(HULL_COLS + 1)]
    rows_z = hull_rows()
    deck = P["deck"]
    stripe = (deck - 0.95, deck - 0.3)

    def x_at(u, z):
        return x_stern(z) + u * (x_bow(z) - x_stern(z))

    # Each side has its own columns: the bulwark may be broken on one side only
    columns = {}
    for side in (1, -1):
        cols = []
        for u in us:
            top = rail_top(x_at(u, deck + 0.5), side, stage)
            zs = rows_z + [(deck + top) / 2, top]
            cols.append([(x_at(u, z), z) for z in zs])
        columns[side] = cols

    shared = {}

    def vert(c, r, side):
        x, z = columns[side][c][r]
        w = half_width(x, z)
        if w < 1e-4:
            key = (c, r)
            if key not in shared:
                shared[key] = bm.verts.new((x, 0.0, z))
            return shared[key]
        return bm.verts.new((x, side * w, z))

    rows = len(columns[1][0])
    grid = {side: [[vert(c, r, side) for c in range(len(us))] for r in range(rows)] for side in (1, -1)}

    def add_face(vs):
        clean = []
        for v in vs:
            if not clean or clean[-1] is not v:
                clean.append(v)
        if clean[0] is clean[-1]:
            clean.pop()
        if len(clean) < 3:
            return
        f = bm.faces.new(clean)
        zc = sum(v.co.z for v in clean) / len(clean)
        # Slots: 0 hull, 1 the painted stripe under the deck, 2 the bottom
        f.material_index = 2 if zc < 0.5 else 1 if stripe[0] < zc < stripe[1] else 0
        for loop in f.loops:
            loop[uv].uv = (loop.vert.co.x / (HULL_TILE * PLANK_STRETCH), loop.vert.co.z / HULL_TILE)

    for side in (1, -1):
        g = grid[side]
        for r in range(rows - 1):
            for c in range(len(us) - 1):
                if side == 1:
                    add_face([g[r][c], g[r + 1][c], g[r + 1][c + 1], g[r][c + 1]])
                else:
                    add_face([g[r][c], g[r][c + 1], g[r + 1][c + 1], g[r + 1][c]])
    for r in range(rows - 1):
        add_face([grid[-1][r][0], grid[-1][r + 1][0], grid[1][r + 1][0], grid[1][r][0]])
    bm.normal_update()
    for f in bm.faces:
        if abs(f.normal.x) > 0.9:
            for loop in f.loops:
                loop[uv].uv = (loop.vert.co.y / (HULL_TILE * PLANK_STRETCH), loop.vert.co.z / HULL_TILE)

    bm.normal_update()
    mesh = bpy.data.meshes.new("Hull")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Hull", mesh)
    coll.objects.link(obj)
    # The inside of the planking +10, the rail's top +20
    for i in range(23):
        if i < 3:
            obj.data.materials.append([mats["hull"], mats["stripe"], mats["bottom"]][i])
        elif 10 <= i <= 12:
            obj.data.materials.append(mats["inner"])
        elif 20 <= i <= 22:
            obj.data.materials.append(mats["stripe"])
        else:
            obj.data.materials.append(mats["hull"])
    mod = obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = WALL
    mod.offset = -1
    mod.use_even_offset = True
    mod.use_rim = True
    mod.material_offset = 10
    mod.material_offset_rim = 20

    dg = bpy.context.evaluated_depsgraph_get()
    baked = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    remap = {0: 0, 1: 1, 2: 2, 10: 3, 11: 3, 12: 3, 20: 1, 21: 1, 22: 1}
    indices = [remap.get(p.material_index, 0) for p in baked.polygons]
    baked.materials.clear()
    for m in (mats["hull"], mats["stripe"], mats["bottom"], mats["inner"]):
        baked.materials.append(m)
    for p, i in zip(baked.polygons, indices):
        p.material_index = i
    obj.modifiers.clear()
    old = obj.data
    obj.data = baked
    bpy.data.meshes.remove(old)
    baked.name = "Hull"
    return obj


def deck_outline(z, x0, x1, steps=30):
    xs = [x0 + (x1 - x0) * i / steps for i in range(steps + 1)]
    left = [(x, inner_width(x, z), z) for x in xs if inner_width(x, z) > 0.03]
    right = [(x, -y, z) for x, y, z in reversed(left)]
    return left + right


def splinters(parts, center, along, up, half, rng, key="spar"):
    """Broken wood sticking up along a break: center and the direction along it, up out of the wood"""
    for k in range(5):
        root = center + along * (half * (k / 2 - 1))
        tip = root + up * (0.35 + 0.4 * rng.random()) + along * 0.12 * (rng.random() - 0.5)
        rod(parts[key], root, tip, 0.08, 0.015, segs=4)


def build_deck(parts, stage):
    """The deck, a hatch amidships, the windlass at the bow, the rudder and its tiller, a deckhouse or a companionway
    aft, anchors at the bow and a lantern on the taffrail"""
    deck = P["deck"]
    polygon(parts["deck"], deck_outline(deck, x_stern(deck) + WALL, x_bow(deck) - 0.2), flip=True)

    hx = P["hatch_x"]
    box(parts["grate"], (hx, 0, deck + 0.22), (2.6, 2.4, 0.44))
    for dx in (-1, 1):
        box(parts["spar"], (hx + dx * 1.3, 0, deck + 0.26), (0.2, 2.6, 0.52))
    for dy in (-1, 1):
        box(parts["spar"], (hx, dy * 1.2, deck + 0.26), (2.8, 0.2, 0.52))

    # Windlass across the foredeck between two bitts
    wx = P["bow"] - 3.4
    w = inner_width(wx, deck) - 0.5
    for y in (-w, w):
        box(parts["spar"], (wx, y, deck + 0.6), (0.4, 0.4, 1.2))
    lathe(parts["spar"], [(0.38, -w), (0.32, 0), (0.38, w)], 10, Matrix.Translation((wx, 0, deck + 0.75)) @ basis(Vector((0, 1, 0))))

    # The rudder hung on the transom, and the tiller over the stern
    zr = rail_z(P["stern"])
    xr = x_stern(1.0)
    pts = [(xr - 0.2, -1.3), (xr - 1.5, -1.0), (xr - 1.4, 1.6), (x_stern(deck) - 0.35, deck), (x_stern(zr) - 0.2, zr + 0.4), (x_stern(-1.2) - 0.05, -1.2)]
    for dy in (0.12, -0.12):
        polygon(parts["hull_part"], [(x, dy, z) for x, z in pts], flip=dy < 0)
    head = Vector((x_stern(zr) - 0.3, 0, zr + 0.35))
    rod(parts["spar"], head, (P["stern"] + 4.2, 0.15, deck + 1.1), 0.12, 0.09, segs=6)

    house = P.get("house")
    if house:
        # A cabin aft: plank walls, a roof a little wider, a door forward and a window each side
        x0, x1, half, h = house["x0"], house["x1"], house["half"], house["h"]
        cx = (x0 + x1) / 2
        box(parts["hull_part"], (cx, 0, deck + h / 2), (x1 - x0, 2 * half, h))
        box(parts["deck"], (cx, 0, deck + h + 0.08), (x1 - x0 + 0.4, 2 * half + 0.4, 0.16))
        box(parts["hole"], (x1 + 0.02, 0, deck + 0.75), (0.08, 0.9, 1.4))
        for side in (1, -1):
            for x in (x0 + 0.9, x1 - 0.9):
                box(parts["glass"], (x, side * (half + 0.02), deck + h * 0.6), (0.6, 0.06, 0.45))
    else:
        # A low companionway with a sliding hatch, and a skylight
        x = P["stern"] + 4.6
        box(parts["hull_part"], (x, 0, deck + 0.45), (1.6, 1.5, 0.9))
        box(parts["deck"], (x - 0.1, 0, deck + 0.95), (1.9, 1.7, 0.12))
        box(parts["grate"], (x + 2.6, 0, deck + 0.3), (1.4, 1.2, 0.6))

    # Anchors at the bows, hanging from the catheads
    for s in (1, -1):
        x = P["bow"] - 2.6
        p, n = hull_point(x, deck + 0.2, s)
        top = p + n * 0.4 + Vector((0, 0, 0.5))
        bottom = top + Vector((-0.25, 0, -2.4))
        rod(parts["iron"], top, bottom, 0.1, segs=6)
        rod(parts["spar"], top + Vector((-0.7, 0, 0)), top + Vector((0.7, 0, 0)), 0.1, segs=6)
        for dx in (-0.9, 0.9):
            tip = bottom + Vector((dx, 0, 0.8))
            rod(parts["iron"], bottom, tip, 0.09, segs=6)
            box(parts["iron"], tip, (0.4, 0.12, 0.32))

    if P.get("lantern"):
        post = Vector((P["stern"] + 0.8, 0, rail_z(P["stern"] + 0.8)))
        rod(parts["iron"], post, post + Vector((0, 0, 1.3)), 0.06, segs=5)
        lathe(parts["lantern"], [(0.25, 1.2), (0.3, 1.5), (0.22, 1.8)], 6, Matrix.Translation(post))
        lathe(parts["iron"], [(0.3, 1.8), (0.08, 2.1)], 6, Matrix.Translation(post))


# ---------------------------------------------------------------------------
# Guns
# ---------------------------------------------------------------------------


def build_guns(parts, stage):
    """A gun at each of the game's slots along the starboard rail (gun_x, one or a few), and its pair to port, as a
    ship would carry them. mortar: (x, y) of a boss's mortar on deck, pointing forward"""
    xs = P["gun_x"] if isinstance(P["gun_x"], (tuple, list)) else (P["gun_x"],)
    for gx in xs:
        for side in (1, -1):
            top = gunwale(gx, side, stage)
            out = Vector((0, side, 0))
            if P["gun"] == "swivel":
                # A swivel gun on a post at the rail: a bronze barrel in an iron fork
                pivot = top + Vector((0, -side * 0.15, 0.55))
                rod(parts["spar"], top - Vector((0, side * 0.15, 0.3)), pivot, 0.1, segs=6)
                aim = (out + Vector((0.35, 0, 0.12))).normalized()
                rod(parts["brass"], pivot - aim * 0.5, pivot + aim * 1.3, 0.15, 0.1, segs=8)
                rod(parts["iron"], pivot - aim * 0.5, pivot - aim * 0.95 + Vector((0, 0, -0.1)), 0.04, segs=4)
            else:
                # A cannon on its carriage, firing over the low bulwark
                y = side * (inner_width(gx, P["deck"]) - 1.2)
                box(parts["spar"], (gx, y, P["deck"] + 0.45), (1.3, 1.2, 0.6))
                for dx in (-0.45, 0.45):
                    for dy in (-0.55, 0.55):
                        m = Matrix.Translation((gx + dx, y + dy, P["deck"] + 0.3)) @ basis(Vector((0, 1, 0)))
                        lathe(parts["spar"], [(0.3, -0.08), (0.3, 0.08)], 8, m)
                breech = Vector((gx, y - side * 0.4, P["gun_z"] - 0.1))
                muzzle = Vector((gx, side * (half_width(gx, top.z) + 0.9), P["gun_z"]))
                rod(parts["iron"], breech, muzzle, 0.3, 0.22, segs=10)
    if P.get("mortar"):
        x, y = P["mortar"]
        deck = P["deck"]
        box(parts["spar"], (x, y, deck + 0.3), (2.0, 2.0, 0.6))
        for dy in (-0.75, 0.75):
            box(parts["iron"], (x, y + dy, deck + 0.85), (0.5, 0.18, 0.5))
        m = Matrix.Translation((x, y, deck + 0.75)) @ Matrix.Rotation(math.radians(40), 4, "Y")
        lathe(parts["brass"], [(0.7, -0.2), (0.85, 0.15), (0.72, 1.0), (0.82, 1.15), (0.66, 1.25)], 12, m, cap_top=False)
        lathe(parts["hole"], [(0.6, 1.2), (0.01, 1.2)], 12, m, False, False)
        # Its shells in a rack beside it
        for k in range(3):
            ball(parts["iron"], (x - 1.6, y - 0.5 + 0.5 * k, deck + 0.3), 0.24)


# ---------------------------------------------------------------------------
# Mast, sails, rigging
# ---------------------------------------------------------------------------


def stay_point(jib, t):
    """A point along a jib's stay, from its top on the mast (0) to the bowsprit (1)"""
    root, tip = bowsprit()
    top = Vector((mast_at(jib["top"]), 0, jib["top"]))
    return top.lerp(root.lerp(tip, jib["end"]), t)


def bowsprit():
    deck = P["deck"]
    root = Vector((x_bow(deck) - 2.4, 0, deck + 0.9))
    tip = Vector((P["bow"] + P["bowsprit"], 0, rail_z(P["bow"]) + 1.3))
    return root, tip


def build_mast(parts, stage):
    """The mast, the boom and the gaff with the mainsail between them, the topsail above, the jibs on their stays to
    the bowsprit, the flags. In stage 4 only the stump is left: fallen_rig() puts the rest over the side"""
    deck, top = P["deck"], P["mast_top"]
    root, tip = bowsprit()
    rod(parts["spar"], root, tip, 0.4, 0.22, segs=10, uv_along=SPAR_TILE)
    rod(parts["rope"], tip.lerp(root, 0.2), (x_bow(1.0) - 0.2, 0, 1.0), 0.07, segs=4, caps=False)  # bobstay
    foot = Vector((mast_at(deck - 0.5), 0, deck - 0.5))
    if stage["mast_broken"]:
        b = deck + MAST_BREAK
        rod(parts["spar"], foot, (mast_at(b), 0, b), 0.5, 0.42, segs=12, uv_along=SPAR_TILE)
        splinters(parts, Vector((mast_at(b), 0, b - 0.1)), Vector((0, 1, 0)), Vector((0, 0, 1)), 0.25, np.random.default_rng(5))
        # The boom slipped off and lies across the deck, its end on the port rail
        a = Vector((mast_at(deck + 1.2) - 0.5, 0.4, deck + 0.3))
        x = P["mast_x"] - 7.5
        rod(parts["spar"], a, gunwale(x, 1, stage, -0.1) + Vector((0, 0, 0.25)), 0.25, 0.18, segs=8, uv_along=SPAR_TILE)
        return
    rod(parts["spar"], foot, (mast_at(top), 0, top), 0.5, 0.26, segs=12, uv_along=SPAR_TILE)
    lathe(parts["spar"], [(0.32, 0), (0.3, 0.25), (0.05, 0.4)], 8, Matrix.Translation((mast_at(top), 0, top)))

    main = {k: Vector(v) for k, v in P["main"].items()}
    gaff_sail(parts, "main", main["tack"], main["throat"], main["peak"], main["clew"], laced_foot=True)
    # Boom along the foot and gaff along the head, each a little longer than the sail
    d = (main["clew"] - main["tack"]).normalized()
    a, b = main["tack"] - d * 0.3 - Vector((0, 0.25)), main["clew"] + d * 0.6 - Vector((0, 0.25))
    rod(parts["spar"], braced(a.x, 0, a.y), braced(b.x, 0, b.y), 0.28, 0.2, segs=8, uv_along=SPAR_TILE)
    d = (main["peak"] - main["throat"]).normalized()
    a, b = main["throat"] - d * 0.3 + Vector((0, 0.2)), main["peak"] + d * 0.5 + Vector((0, 0.2))
    rod(parts["spar"], braced(a.x, 0, a.y), braced(b.x, 0, b.y), 0.2, 0.13, segs=8, uv_along=SPAR_TILE)

    topsail = P["topsail"]
    if topsail["kind"] == "square":
        square_sail(parts, "topsail", topsail)
    else:
        gaff_sail(parts, "topsail", Vector((-0.3, main["throat"].y + 0.8)), Vector((-0.2, top - 0.6)), Vector((-0.2, top - 0.6)), main["peak"] + Vector((0.3, 0.45)), laced_foot=False)

    for jib in P["jibs"]:
        head, tack = stay_point(jib, jib["a"]), stay_point(jib, jib["b"])
        clew = Vector(jib["clew"])
        rod(parts["rope"], stay_point(jib, 0), stay_point(jib, 1), 0.06, segs=4, caps=False)

        def point(u, v, head=head, tack=tack, clew=clew):
            edge = head.lerp(tack, u)
            bulge = Vector((0, 0.9, 0)) * math.sin(math.pi * u) * math.sin(math.pi * v) ** 0.8
            return edge.lerp(clew, v) + bulge

        grid_surface(parts["jib"], point, 10, 6)

    build_flags(parts, stage, main)


def gaff_sail(parts, key, tack, throat, peak, clew, laced_foot):
    """A four-cornered fore-and-aft sail (a triangle when throat == peak) bellying out to port, the leeward side.
    Corners are (forward of the mast, height)"""

    def point(u, v):
        foot = tack.lerp(clew, u)
        head = throat.lerp(peak, u)
        along, z = foot.lerp(head, v)
        fv = math.sin(math.pi * v) ** 0.7 if laced_foot else math.sin(math.pi * (0.15 + 0.85 * v)) ** 0.7
        belly = 2.0 * math.sin(math.pi * u) ** 0.8 * fv
        return braced(along, belly, z)

    grid_surface(parts[key], point, 20, 16)


def square_sail(parts, key, spec):
    """A square sail across the mast between two yards, bellying forward"""
    lo, hi, half_lo, half_hi = spec["lo"], spec["hi"], spec["half_lo"], spec["half_hi"]

    def point(u, v):
        s = u * 2 - 1
        hw = half_lo + (half_hi - half_lo) * v
        fv = math.sin(math.pi * v) ** 0.8 * 0.85 + 0.15 * (1 - v)
        along = 1.6 * (1 - s * s) ** 0.8 * fv + 0.5
        return braced(along, -s * hw, lo + (hi - lo) * v, SQUARE_BRACE)

    grid_surface(parts[key], point, 16, 12)
    for z, hw, r in ((hi + 0.2, half_hi + 0.6, 0.16), (lo - 0.15, half_lo + 0.5, 0.14)):
        mid = braced(0.5, 0, z, SQUARE_BRACE)
        for end in (braced(0.5, hw, z, SQUARE_BRACE), braced(0.5, -hw, z, SQUARE_BRACE)):
            rod(parts["spar"], mid, end, r, r * 0.5, segs=6, uv_along=SPAR_TILE)


def build_flags(parts, stage, main):
    """The ensign at the gaff's peak or the masthead, and a pennant over a trader's masthead; damage shreds them"""
    left = stage["flag"]
    if left <= 0:
        return
    if P["flag_at"] == "gaff":
        anchor = braced(main["peak"].x - 0.4, 0, main["peak"].y + 0.3)
        width, height = 3.0 * left, 2.0
    else:
        anchor = Vector((mast_at(P["mast_top"]) - 0.2, 0, P["mast_top"] + 0.2))
        width, height = 3.6 * left, 2.4

    def flag(u, v):
        return anchor + Vector((-width * u, 0.35 * math.sin(u * 5.0) * u, -height * (1 - v)))

    grid_surface(parts["flag"], flag, 10, 4)
    if P.get("pennant"):
        top = Vector((mast_at(P["mast_top"]), 0, P["mast_top"] + 0.4))
        length = 6.0 * left

        def pennant(u, v):
            half = 0.4 * (1 - u) + 0.06
            return top + Vector((-0.1 - length * u, 0.5 * math.sin(u * 4.0) * u, -0.4 + (v * 2 - 1) * half))

        grid_surface(parts["pennant"], pennant, 12, 2)


def build_rigging(parts, stage):
    """Shrouds from the hounds to the chains on each side, backstays, the mainsheet and the topping lift"""
    if stage["mast_broken"]:
        return
    rope = parts["rope"]
    hounds = P["main"]["throat"][1] + 1.0
    head = Vector((mast_at(hounds), 0, hounds))
    for side in (1, -1):
        for dx in (-0.6, -1.8, -3.0):
            x = P["mast_x"] + dx
            p, n = hull_point(x, rail_z(x) - 0.3, side)
            rod(rope, head + Vector((0, side * 0.35, 0)), p + n * 0.45, 0.055, segs=4, caps=False)
            box(parts["iron"], p + n * 0.4, (0.18, 0.12, 0.5))
        x = P["mast_x"] - 1.8
        p, n = hull_point(x, rail_z(x) - 0.35, side)
        t, n2, b = side_frame(n)
        box(parts["spar"], p + n2 * 0.35, (3.4, 0.6, 0.15), (t, n2, b))
        if side == -1:  # the backstay to windward; the lee one is slack and lost against the sail
            x = P["stern"] + 3.5
            rod(rope, Vector((mast_at(P["mast_top"] - 1), side * 0.2, P["mast_top"] - 1)), gunwale(x, side, stage, 0.1), 0.05, segs=4, caps=False)
    main = {k: Vector(v) for k, v in P["main"].items()}
    clew = braced(main["clew"].x, 0, main["clew"].y - 0.25)
    rod(rope, clew, (P["stern"] + 1.2, 0, rail_z(P["stern"])), 0.05, segs=4, caps=False)
    rod(rope, clew, (mast_at(P["mast_top"] - 0.5), 0, P["mast_top"] - 0.5), 0.04, segs=4, caps=False)
    peak = braced(main["peak"].x, 0, main["peak"].y + 0.2)
    rod(rope, peak, (mast_at(P["mast_top"] - 1.5), 0, P["mast_top"] - 1.5), 0.04, segs=4, caps=False)
    for jib in P["jibs"]:
        rod(rope, Vector(jib["clew"]), gunwale(P["mast_x"] - 1.0, 1, stage), 0.04, segs=4, caps=False)


# ---------------------------------------------------------------------------
# Deck cargo
# ---------------------------------------------------------------------------


def barrel(parts, x, y, z, r, h, axis=None):
    """A barrel standing at (x, y, z), or lying along `axis` with its middle there"""
    if axis is None:
        m = Matrix.Translation((x, y, z))
    else:
        d = Vector(axis).normalized()
        m = Matrix.Translation(Vector((x, y, z)) - d * (h / 2)) @ basis(d)
    prof = [(r * 0.86, 0), (r, h * 0.3), (r * 1.05, h * 0.5), (r, h * 0.7), (r * 0.86, h)]
    lathe(parts["barrel"], prof, 12, m, uv_along=h)
    for zz in (0.14, h - 0.14):
        rr = r * 0.92 + 0.03
        lathe(parts["iron"], [(rr, zz - 0.05), (rr, zz + 0.05)], 12, m, False, False)


def crate(parts, x, y, z, s, rot):
    axes = turned(rot)
    box(parts["crate"], (x, y, z + s / 2), (s, s, s), axes)
    for k in (-1, 1):
        c = Vector((x, y, z + s / 2)) + axes[0] * (k * s * 0.42)
        box(parts["spar"], c, (0.14, s + 0.04, s + 0.04), axes)


def bale(parts, x, y, z, size, rot):
    """A bale of cloth or wool in burlap, corded twice round"""
    sx, sy, sz = size
    axes = turned(rot)
    c = Vector((x, y, z + sz / 2))
    box(parts["burlap"], c, (sx, sy, sz), axes)
    for k in (-0.28, 0.28):
        box(parts["rope"], c + axes[0] * (k * sx), (0.1, sy + 0.04, sz + 0.04), axes)


def sack(parts, x, y, z, r):
    profile = [(r * 0.85 * math.sin(math.pi * k / 6) + 1e-3, z + r * 0.7 * (1 - math.cos(math.pi * k / 6))) for k in range(7)]
    lathe(parts["burlap"], profile, 10, Matrix.Translation((x, y, 0)), False, False)


def tarp_heap(parts, x, y, rx, ry, h, rng):
    """Cargo nobody should see, under a lashed tarpaulin"""
    deck = P["deck"]
    bumps = [(rng.random() * 6.28, 0.6 + rng.random()) for _ in range(4)]

    def point(u, v):
        a = 2 * math.pi * u
        r = 1 - v
        lump = 1 + 0.08 * sum(math.sin(k * a + p) * s for k, (p, s) in enumerate(bumps, 2)) / len(bumps)
        z = deck + h * max(0.0, 1 - r**4) ** 0.5
        return Vector((x + rx * r * math.cos(a) * lump, y + ry * r * math.sin(a) * lump, z))

    grid_surface(parts["tarp"], point, 20, 6)
    for k in (-0.4, 0.0, 0.4):
        rod(parts["rope"], (x + k * rx, -ry * 1.02 + y, deck + 0.1), (x + k * rx, y, deck + h + 0.05), 0.04, segs=4)
        rod(parts["rope"], (x + k * rx, y, deck + h + 0.05), (x + k * rx, ry * 1.02 + y, deck + 0.1), 0.04, segs=4)


def build_cargo(parts, stage, look, rng):
    """What the ship carries on deck, by its look. Each list is ordered so the last items go first: a stage keeps the
    first `cargo` share of it"""
    deck = P["deck"]
    kind = look["cargo"]
    if kind == "crates":
        items = [
            lambda: crate(parts, 5.4, 2.0, deck, 1.4, 0.05),
            lambda: crate(parts, 5.4, -2.0, deck, 1.4, -0.05),
            lambda: crate(parts, 7.0, 2.0, deck, 1.3, 0.1),
            lambda: barrel(parts, 8.6, -1.7, deck, 0.6, 1.4),
            lambda: crate(parts, -6.0, 2.6, deck, 1.2, 0.0),
            lambda: crate(parts, 7.0, -2.0, deck, 1.3, -0.1),
            lambda: barrel(parts, 8.7, 0.0, deck, 0.6, 1.4),
            lambda: crate(parts, -6.1, -2.6, deck, 1.2, 0.08),
            lambda: crate(parts, 5.5, 2.0, deck + 1.4, 1.15, 0.3),
            lambda: barrel(parts, -1.2, -3.2, deck + 0.55, 0.55, 1.4, axis=(1, 0, 0)),
            lambda: crate(parts, 6.2, -2.0, deck + 1.3, 1.1, -0.25),
            lambda: barrel(parts, 8.7, 1.7, deck, 0.6, 1.4),
        ]
    elif kind == "bales":
        items = [
            lambda: bale(parts, 5.6, 1.9, deck, (2.2, 1.5, 1.2), 0.05),
            lambda: bale(parts, 5.6, -1.9, deck, (2.2, 1.5, 1.2), -0.05),
            lambda: sack(parts, 8.4, 1.4, deck, 0.65),
            lambda: barrel(parts, -6.0, 2.6, deck, 0.6, 1.4),
            lambda: bale(parts, 5.7, 0.0, deck + 1.2, (2.0, 1.4, 1.1), 0.12),
            lambda: sack(parts, 8.5, -1.3, deck, 0.65),
            lambda: barrel(parts, -6.1, -2.6, deck, 0.6, 1.4),
            lambda: sack(parts, 8.9, 0.1, deck, 0.6),
            lambda: bale(parts, -1.5, -3.1, deck, (1.8, 1.2, 1.0), 0.0),
            lambda: sack(parts, 8.6, 0.0, deck + 0.85, 0.55),
            lambda: barrel(parts, -6.0, 0.0, deck, 0.55, 1.3),
        ]
    elif kind == "hold":
        # The Baron's: the mortar has the foredeck, so the kegs are lashed along the bulwarks
        items = [
            lambda: tarp_heap(parts, -4.4, 0.0, 2.8, 2.6, 1.5, rng),
            lambda: barrel(parts, 5.6, 2.7, deck, 0.45, 1.0),
            lambda: barrel(parts, 5.6, -2.7, deck, 0.45, 1.0),
            lambda: barrel(parts, 6.6, 2.8, deck, 0.45, 1.0),
            lambda: barrel(parts, 6.6, -2.8, deck, 0.45, 1.0),
            lambda: barrel(parts, 6.1, 2.75, deck + 1.0, 0.42, 0.95),
        ]
    else:
        items = [
            lambda: tarp_heap(parts, -4.4, 0.0, 2.8, 2.6, 1.5, rng),
            lambda: barrel(parts, 6.0, 1.5, deck, 0.45, 1.0),
            lambda: barrel(parts, 6.0, -1.5, deck, 0.45, 1.0),
            lambda: barrel(parts, 7.1, 0.6, deck, 0.45, 1.0),
            lambda: barrel(parts, 7.1, -0.7, deck, 0.45, 1.0),
            lambda: barrel(parts, 6.5, 0.0, deck + 1.0, 0.42, 0.95),
            lambda: barrel(parts, 8.2, 0.1, deck + 0.45, 0.42, 1.2, axis=(0, 1, 0)),
        ]
    for add in keep(items, stage["cargo"]):
        add()
    if look.get("boat"):
        boat(parts, -1.9, 0.0, deck + 0.75)


def boat(parts, x, y, z):
    """The ship's boat, keel up on chocks: a lathed half-shell squashed into a boat's lines"""
    length, beam, depth = 4.6, 1.05, 0.75
    bm = parts["deck"]
    segs, rings = 10, 12
    verts = []
    for i in range(rings + 1):
        u = i / rings
        along = (u - 0.5) * length
        w = beam * math.sin(math.pi * u) ** 0.55
        ring = [bm.verts.new((x + along, y + w * math.cos(math.pi * j / segs), z + depth * math.sin(math.pi * j / segs) * math.sin(math.pi * u) ** 0.3)) for j in range(segs + 1)]
        verts.append(ring)
    for i in range(rings):
        for j in range(segs):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    for dx in (-1.2, 1.2):
        box(parts["spar"], (x + dx, y, z - 0.35), (0.3, 1.8, 0.7))


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


def build_damage(parts, stage, rng):
    """Shot holes in the hull with scorched rims and splinters, and broken plank ends where the bulwark broke"""
    for x, z, side, r in HULL_HOLES[: stage["hull_holes"]]:
        p, n = hull_point(x, z, side)
        t, n, b = side_frame(n)
        center = p + n * 0.04
        k = 11
        phase = rng.random() * 6.28
        rim = []
        for i in range(k):
            a = 2 * math.pi * i / k
            rr = r * (0.75 + 0.35 * abs(math.sin(3 * a + phase)) + 0.15 * rng.random())
            rim.append(center + (t * math.cos(a) + b * math.sin(a)) * rr)
        face = polygon(parts["hole"], rim)
        face.normal_update()
        if face.normal.dot(n) < 0:
            face.normal_flip()
        scorch = [center - n * 0.02 + (q - center) * (1.5 + 0.2 * rng.random()) for q in rim]
        face = polygon(parts["burnt"], scorch)
        face.normal_update()
        if face.normal.dot(n) < 0:
            face.normal_flip()
        for _ in range(5):
            a = rng.random() * 2 * math.pi
            d = t * math.cos(a) + b * math.sin(a)
            root = center + d * r * 0.85
            tip = root + d * r * (0.5 + 0.5 * rng.random()) + n * (0.15 + 0.25 * rng.random())
            rod(parts["hull_part"], root, tip, 0.08, 0.02, segs=4)
    for bx, side, half, _ in RAIL_BREAKS[: stage["rail_breaks"]]:
        for end in (-1, 1):
            x = bx + end * half * 0.85
            splinters(parts, gunwale(x, side, stage), Vector((1, 0, 0)), Vector((0, side * 0.2, 1)).normalized(), 0.18, rng, "hull_part")


def build_debris(parts, stage, look, rng):
    """Wreckage floating round the ship: planks, a hatch grating, barrels and its cargo. Built on the water, not listed
    with the ship"""
    for i in range(stage["debris"]):
        a = rng.random() * 2 * math.pi
        dist = 14 + 7 * rng.random()
        c = Vector((math.cos(a) * dist * 1.4, math.sin(a) * dist, 0.06))
        rot = rng.random() * math.pi
        kind = i % 4
        if kind == 1:
            barrel(parts, c.x, c.y, -0.2, 0.55, 1.3, axis=(math.cos(rot), math.sin(rot), 0))
        elif kind == 2 and look["cargo"] == "bales":
            bale(parts, c.x, c.y, -0.6, (1.8, 1.2, 1.0), rot)
        elif kind == 2:
            crate(parts, c.x, c.y, -0.55, 1.2, rot)
        elif kind == 3:
            box(parts["grate"], c, (2.2, 2.0, 0.25), turned(rot))
        else:
            # Light deck planks: the dark hull's would read as black specks on the water
            box(parts["deck"], c, (3.0 + rng.random() * 1.4, 0.5, 0.16), turned(rot))


def fallen_rig(parts, stage, tilt):
    """Stage 4: the mast snapped and went over the port side. It rests on the bulwark with its head in the water; the
    gaff floats alongside and the mainsail spreads on the water from the boom on deck out to it; the topsail lies by
    the masthead and the jibs hang from the bowsprit. Built over the listed ship (tilt is its list and sinking), so
    what floats lies on the water"""
    deck, top = P["deck"], P["mast_top"]
    length = top - deck - MAST_BREAK
    rest = tilt @ gunwale(P["mast_x"] + 0.4, 1, stage, 0.05) + Vector((0, 0, 0.3))
    head = Vector((P["mast_x"] + 3.0, rest.y + length * 0.78, 0.18))
    d = (rest - head).normalized()
    foot = head + d * length
    rod(parts["spar"], foot, head, 0.42, 0.26, segs=10, uv_along=SPAR_TILE)
    splinters(parts, foot, Vector((1, 0, 0)), d, 0.2, np.random.default_rng(8))

    main = {k: Vector(v) for k, v in P["main"].items()}
    gaff_len = (main["peak"] - main["throat"]).length + 0.8
    g_a = Vector((P["mast_x"] + 1.0, rest.y + 6.5, 0.16))
    g_b = g_a + Vector((-1.0, 0.18, 0)).normalized() * gaff_len
    rod(parts["spar"], g_a, g_b, 0.2, 0.13, segs=8, uv_along=SPAR_TILE)

    boom_a = tilt @ Vector((mast_at(deck + 1.2) - 0.5, 0.4, deck + 0.3))
    boom_b = tilt @ (gunwale(P["mast_x"] - 7.5, 1, stage, -0.1) + Vector((0, 0, 0.25)))
    rng = np.random.default_rng(9)
    phases = [rng.random() * 6.28 for _ in range(3)]

    def spread(foot_at, head_at, over_at):
        def point(u, v):
            f, h, o = foot_at(u), head_at(u), over_at(u)
            if v < 0.12:
                return f.lerp(o, v / 0.12)
            k = (v - 0.12) / 0.88
            p = o.lerp(h, k)
            wave = 0.1 * sum(math.sin(u * (8 + 4 * i) + v * (5 + 3 * i) + ph) for i, ph in enumerate(phases))
            p.z = max(0.08 + wave * min(1.0, k * 4), o.z * (1 - k * 3)) if k < 0.33 else 0.08 + wave
            return p

        return point

    def over_rail(u):
        x = boom_a.lerp(boom_b, u).x
        return tilt @ gunwale(min(x, P["mast_x"] - 0.5), 1, stage, 0.35) + Vector((0, 0, 0.15))

    grid_surface(parts["main"], spread(lambda u: boom_a.lerp(boom_b, u) + Vector((0, 0, 0.25)), lambda u: g_a.lerp(g_b, u), over_rail), 18, 16)

    # The topsail on the water past the gaff, round the masthead
    corner = head + Vector((-2.5, 1.5, 0))

    def topsail(u, v):
        p = corner + Vector((-7.0 * u, 4.5 * v, 0)) + Vector((0, 0.8 * math.sin(u * 3.0), 0))
        p.z = 0.1 + 0.08 * math.sin(u * 13 + v * 7) + 0.06 * math.sin(u * 5 - v * 11)
        return p

    grid_surface(parts["topsail"], topsail, 10, 8)

    # The jibs, torn off their stays, hang from the bowsprit into the water on the port bow
    _, tip = bowsprit()
    tip = tilt @ tip
    for k, jib in enumerate(P["jibs"]):
        a = tip + Vector((-3.0 - 3 * k, 4.0 + 2.5 * k, 0))
        b = tip + Vector((-9.0 - 2 * k, 3.0 + 3 * k, 0))
        a.z = b.z = 0.12

        def hanging(u, v, a=a, b=b, k=k):
            p = (tip - Vector((1.5 * k, 0, 0))).lerp(a.lerp(b, u), v)
            p.z = max(p.z, 0.1 + 0.08 * math.sin(u * 9 + v * 5))
            return p

        grid_surface(parts["jib"], hanging, 8, 6)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

OBJECT_NAMES = {
    "deck": "Deck",
    "hull_part": "Woodwork",
    "inner": "Bulwarks",
    "spar": "Spars",
    "rope": "Rigging",
    "main": "Mainsail",
    "jib": "Jibs",
    "topsail": "Topsail",
    "flag": "Flag",
    "pennant": "Pennant",
    "barrel": "Barrels",
    "crate": "Crates",
    "burlap": "Bales",
    "tarp": "Tarpaulin",
    "iron": "Iron",
    "brass": "Brass",
    "grate": "Hatches",
    "glass": "Windows",
    "lantern": "Lantern",
    "hole": "Openings",
    "burnt": "Scorch",
}
PART_MATERIAL = {"hull_part": "hull"}
# Parts whose UVs come from box projection, with the tile size that sets the plank width
BOX_UV_TILE = {
    "deck": DECK_TILE,
    "hull_part": HULL_TILE,
    "inner": HULL_TILE,
    "spar": SPAR_TILE,
    "crate": 2.5,
    "iron": 3.0,
}


def clear_previous():
    coll = bpy.data.collections.get("Ship")
    if coll:
        for obj in list(coll.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(coll)
    for block in (bpy.data.materials, bpy.data.meshes, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def build(spec, looks, damage=None, variant=None):
    """spec: the ship (see merchantSloop/build.py); looks: its looks by name, one of them picked by `variant` (or the
    scene's "variant" property, or the first); damage: the stage (see DAMAGE_STAGES), by default the scene's "damage"
    property, or 0. A ship with a single look keeps its atlases straight in its folder: it passes variant None"""
    global TEX_DIR, PH_DIR
    P.clear()
    P.update(spec)
    ship_dir = base_dir()
    TEX_DIR = os.path.join(ship_dir, "textures")
    PH_DIR = os.path.join(assets_root(ship_dir), "textures", "polyhaven")
    scene = bpy.context.scene
    if damage is None:
        damage = int(scene.get("damage", 0))
    damage = damage if damage in DAMAGE_STAGES else 0
    names = list(looks)
    if len(names) > 1:
        if variant is None:
            variant = str(scene.get("variant", names[0]))
        variant = variant if variant in looks else names[0]
        scene["variant"] = variant
        look = looks[variant]
    else:
        variant = None
        look = looks[names[0]]
    stage = DAMAGE_STAGES[damage]
    scene["damage"] = damage
    clear_previous()
    coll = bpy.data.collections.new("Ship")
    scene.collection.children.link(coll)

    mats = make_materials(look, stage, damage, variant)
    # render_sprites.py turns the object named "Ship"; everything else is parented to it
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 10
    coll.objects.link(root)
    hull = build_hull(mats, coll, stage)
    hull.parent = root

    parts = Parts()
    rng = np.random.default_rng(11)
    build_deck(parts, stage)
    build_guns(parts, stage)
    build_mast(parts, stage)
    build_rigging(parts, stage)
    build_cargo(parts, stage, look, np.random.default_rng(3))
    build_damage(parts, stage, rng)

    # A badly damaged ship sits lower in the water and lists to port. What floats round it is built after, on the water
    tilt = Matrix.Translation((0, 0, -stage["sink"])) @ Matrix.Rotation(-math.radians(stage["list_deg"]), 4, "X")
    add_objects(parts, mats, coll, root)
    for obj in coll.objects:
        if obj.type == "MESH":
            obj.data.transform(tilt)
    afloat = Parts()
    build_debris(afloat, stage, look, rng)
    if stage["mast_broken"]:
        fallen_rig(afloat, stage, tilt)
    add_objects(afloat, mats, coll, root, "Afloat")
    # A ship made from another one at another size: the whole of it stretched, the waterline staying where it is
    if P.get("scale"):
        stretch = Matrix.Diagonal((*P["scale"], 1.0))
        for obj in coll.objects:
            if obj.type == "MESH":
                obj.data.transform(stretch)
    return root


def add_objects(parts, mats, coll, root, prefix=""):
    """An object of each part's mesh, with its material, parented to the root"""
    for key, bm in parts.meshes.items():
        bm.normal_update()
        if key in BOX_UV_TILE:
            box_project_uvs(bm, BOX_UV_TILE[key])
        name = prefix + OBJECT_NAMES[key]
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mats[PART_MATERIAL.get(key, key)])
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        obj.parent = root

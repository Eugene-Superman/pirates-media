"""
Fishing boat (line "bots", game class "fishingBoat"), built from code: the small open boats that fish the starting
waters, neutral bots with no guns. A beamy open boat with a transom stern, three thwarts, a little foredeck and
afterdeck, and one lug sail on a stubby mast. Three looks, so a sea of them isn't one boat over and over (VARIANTS):
  nets     weathered blue, a white rail, a tanned red sail; nets heaped amidships with cork floats, fish baskets
  barrels  green, an ochre rail, a patched canvas sail; barrels and crates, a lantern at the stern
  pots     cream with a red rail, an ochre sail with a dark band and a little mizzen; lobster pots and marker buoys

Run in Blender: open fishingBoat.blend next to this file, Scripting tab -> Open -> build.py -> Run Script.
It rebuilds the "Ship" collection of the open file: the look picked by the scene's "variant" property (a name from
VARIANTS), the damage stage by its "damage" property (0-4, see DAMAGE_STAGES). render_stages.py renders every look at
every stage.

Damage: each stage keeps the damage of the one before and adds to it: 1 soot, shot holes in the hull and the sail,
some of the catch gone; 2 more holes, a torn sail, the gunwale broken in places, an oar lost; 3 charred wood, the sail
burnt from the foot (the game adds the fire), a thwart split; 4 the mast snapped and over the side with the sail in
the water, listing to port, low in the water, the catch and planks floating round (the game animates the sinking).

Axes and scale match the game: 1 Blender unit = 1 game unit, the bow points to +X, port side to +Y, Z up,
waterline at Z = 0. Hull about 19 units long and 8 wide (src/game/ships/shipClasses.ts, fishingBoat: bow 10,
stern -8.8, half-beam 4.1).

Textures: scanned CC0 wood and metal from Poly Haven (polyhaven.com), shared by all ships in
blender-assets/textures/polyhaven/ and downloaded there on the first run; the sails and the nets are generated into
textures/ next to this file. They are linked by relative paths, not packed.
"""

import json
import math
import os
import urllib.request

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# Dimensions (game units)
# ---------------------------------------------------------------------------

KEEL_Z = -0.9
FLOOR_Z = 0.25  # the floorboards
THWART_Z = 1.55  # the seats across the boat
BEAM = 3.95  # largest half-width of the hull
WALL = 0.16  # planking thickness
THWARTS_X = (5.2, 2.6, -3.6)  # the middle one holds the mast
FOREDECK_X = 7.4  # where the little foredeck starts
AFTDECK_X = -6.7  # where the afterdeck ends

MAST_X = 2.6
MAST_TOP = 13.6
# The lug sail, as (forward of the mast, height) at its four corners: tack and clew at the foot, throat and peak on
# the yard, which crosses the mast slanting up aft
LUG = dict(tack=(1.4, 2.9), throat=(0.9, 10.2), peak=(-6.8, 13.6), clew=(-7.2, 3.3))
# The pots boat's mizzen: a little lug on a mast at the transom, sheeted to a spar out over the stern
MIZZEN_X = -8.0
MIZZEN_TOP = 7.8
MIZZEN = dict(tack=(0.5, 3.3), throat=(0.4, 6.5), peak=(-2.4, 7.5), clew=(-2.8, 3.6))
SAIL_BELLY = 1.1  # how far the sail bulges to leeward
BRACE = 0.34  # radians: the sail is sheeted out a little, so it reads from the bow and the stern too

# Real-world size of one texture tile, in game units: sets the plank width on the model
HULL_TILE = 5.0
PLANK_STRETCH = 2.0  # hull planks are long boards, so the tile is stretched along the hull
DECK_TILE = 3.5
SPAR_TILE = 3.0
NET_TILE = 1.4

# Colors (sRGB)
COLORS = {
    "iron": 0x34343A,
    "rope": 0x8E6B44,
    "hole": 0x1C130D,
    "soot": 0x1E1712,
    "char": 0x1A130E,
    "burnt": 0x2B1E15,
    "glass": 0xFFCF73,
    "wicker": 0xB48A52,
    "fish": 0xC9D3D8,
    "float_orange": 0xE8742C,
    "float_white": 0xEDE7D8,
    "buoy": 0xC8372D,
    "flag": 0x222226,
    "net": 0x5E5A3C,
    "net_gap": 0x2C2A1E,
    "lath": 0xC9A774,
    "water": 0x2A5F78,  # the sea in the game, a little darker in the boat's shade
}

# The three looks. paint: the Poly Haven set on the hull above the waterline, with a hue/saturation/value tweak, and
# paint_tint: a color its grain is painted over with (None keeps the set's own paint);
# trim: the stripe under the rail and the rail itself; sail: the canvas, with patches or a band painted across;
# pennant: the masthead streamer; cargo: what fills the boat
# prettier-ignore
VARIANTS = {
    "nets": dict(paint="blue_painted_planks", paint_hsv=(0.5, 1.0, 1.0), paint_tint=0x3A78B0, trim=0xE6DFCB, sail=0xA9512E,
                 sail_patches=((0.22, 0.4, 0.36, 0.55, 0.88), (0.6, 0.16, 0.72, 0.28, 1.1)), sail_band=None,
                 pennant=0xD23B2B, cargo="nets", mizzen=False),
    "barrels": dict(paint="green_rough_planks", paint_hsv=(0.5, 1.0, 1.0), paint_tint=0x4E8A4A, trim=0xD8A537, sail=0xEDE3CB,
                    sail_patches=((0.18, 0.52, 0.34, 0.7, 0.86), (0.58, 0.22, 0.76, 0.36, 0.9),
                                  (0.42, 0.74, 0.54, 0.86, 0.84)), sail_band=None,
                    pennant=0xE3B23C, cargo="barrels", mizzen=False),
    "pots": dict(paint="distressed_painted_planks", paint_hsv=(0.5, 1.1, 1.0), paint_tint=None, trim=0xB3392B, sail=0xD7A146,
                 sail_patches=(), sail_band=(0.56, 0.68, 0x7A3A22),
                 pennant=0x2F5EA8, cargo="pots", mizzen=True),
}
VARIANT_NAMES = tuple(VARIANTS)

# What each damage stage does to the model. Holes, gunwale breaks and debris are taken from the lists below in order,
# so every stage keeps the damage of the previous one and adds to it. cargo: the share of the catch still aboard;
# pennant: what is left of it
# prettier-ignore
DAMAGE_STAGES = {
    0: dict(soot=0.0, char=0.0, hull_holes=0, sail_holes=0, sail_tear=False, sail_burn=0.0, rail_breaks=0, cargo=1.0,
            pennant=1.0, oars=2, thwart_split=False, mast_broken=False, list_deg=0.0, sink=0.0, debris=0),
    1: dict(soot=0.3, char=0.0, hull_holes=2, sail_holes=3, sail_tear=False, sail_burn=0.0, rail_breaks=0, cargo=0.85,
            pennant=0.75, oars=2, thwart_split=False, mast_broken=False, list_deg=0.0, sink=0.0, debris=0),
    2: dict(soot=0.5, char=0.0, hull_holes=4, sail_holes=6, sail_tear=True, sail_burn=0.0, rail_breaks=2, cargo=0.65,
            pennant=0.45, oars=1, thwart_split=False, mast_broken=False, list_deg=2.0, sink=0.15, debris=1),
    3: dict(soot=0.65, char=0.3, hull_holes=6, sail_holes=8, sail_tear=True, sail_burn=0.38, rail_breaks=3, cargo=0.45,
            pennant=0.0, oars=1, thwart_split=True, mast_broken=False, list_deg=4.0, sink=0.3, debris=3),
    4: dict(soot=0.75, char=0.45, hull_holes=8, sail_holes=10, sail_tear=True, sail_burn=0.5, rail_breaks=4, cargo=0.3,
            pennant=0.0, oars=0, thwart_split=True, mast_broken=True, list_deg=10.0, sink=0.7, debris=8),
}
# Shot holes in the hull: x, height, side (+1 port, -1 starboard), radius. A sprite shows about 3 pixels per unit, so
# a hole much smaller than half a unit is lost
HULL_HOLES = [
    (-2.6, 1.2, -1, 0.6), (3.6, 1.0, 1, 0.55), (-6.0, 1.4, 1, 0.5), (6.4, 1.5, -1, 0.5),
    (0.6, 0.8, 1, 0.62), (-4.6, 0.7, -1, 0.58), (5.0, 0.9, 1, 0.5), (-0.4, 1.5, -1, 0.5),
]
# Holes in the sail, in its texture: u from the luff to the leech, v up, radius
SAIL_HOLES = [
    (0.3, 0.58, 0.06), (0.72, 0.33, 0.055), (0.55, 0.8, 0.045), (0.16, 0.25, 0.065), (0.86, 0.63, 0.05),
    (0.44, 0.42, 0.07), (0.65, 0.6, 0.055), (0.25, 0.84, 0.05), (0.8, 0.16, 0.065), (0.1, 0.5, 0.055),
]
# Chunks broken out of the gunwale: x, side, half-length, depth
RAIL_BREAKS = [(-2.0, 1, 0.9, 0.7), (4.4, -1, 0.75, 0.55), (-5.4, -1, 0.7, 0.5), (0.9, 1, 0.6, 0.45)]
MAST_BREAK_Z = 5.2  # where the mast snaps in stage 4
WEAR_SEED = 7.1  # soot and char blotches stay in the same places from stage to stage, they only grow


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
            return os.path.abspath(ship_dir)  # not inside ships/, e.g. a test run: keep everything together
        path = parent
    return os.path.dirname(path)


SHIP_DIR = os.environ.get("SHIP_OUT") or base_dir()  # this ship's folder: ships/bots/fishingBoat
TEX_DIR = os.path.join(SHIP_DIR, "textures")
PH_DIR = os.path.join(assets_root(SHIP_DIR), "textures", "polyhaven")


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

    # The boat is half the Corsair's size, so its blotches are smaller too
    for amount, color, scale, softness, strength in ((soot, "soot", 0.55, 0.16, 0.9), (char, "char", 1.0, 0.1, 0.8)):
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


def netting(name, image, tile, cut=True):
    """Twine knotted into a net. cut: the gaps between the twine are see-through (a net hanging free); otherwise they
    are the dark inside of a heap of net"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Specular IOR Level"].default_value = 0.1
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1 / tile, 1 / tile, 1.0)
    links.new(coord.outputs["UV"], mapping.inputs["Vector"])
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.interpolation = "Closest"
    links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if cut:
        see_through(m, nodes, links, bsdf.outputs["BSDF"], tex.outputs["Alpha"])
    m.diffuse_color = linear(COLORS["net"])
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
# Hull shape
# ---------------------------------------------------------------------------


def x_bow(z):
    """The stem rakes forward as it rises"""
    return 9.0 + 0.42 * z


def x_stern(z):
    """The transom rakes aft as it rises"""
    return -8.0 - 0.28 * z


def section(z):
    """Width of the cross-section at height z (0..1): a firm round bilge, the sides flaring a little above it"""
    widest = 2.0
    if z <= widest:
        t = (widest - z) / (widest - KEEL_Z)
        return max(0.0, 1 - t**2.4) ** 0.5
    return 1 + 0.03 * (z - widest)


def plan(x, z):
    """Half-width at height z depending on x: a full bow and a wide transom, as a work boat has"""
    xs, xb = x_stern(z), x_bow(z)
    if x >= xb:
        return 0.0
    if x > 1.5:
        t = (x - 1.5) / (xb - 1.5)
        return BEAM * max(0.0, 1 - t * t) ** 0.62
    if x < -3.5:
        t = min(1.0, (-3.5 - x) / (-3.5 - xs))
        return BEAM * (1 - 0.36 * t**1.7)
    return BEAM


def half_width(x, z):
    return plan(x, z) * section(z)


def rail_z(x):
    """Top of the side: the sheer rises to the bow, and less to the stern"""
    d = x - 0.8
    return 2.35 + (0.0115 if d > 0 else 0.0065) * d * d


def aftdeck_z():
    return rail_z(AFTDECK_X) - 0.2


def rail_top(x, side, stage):
    """The gunwale with the chunks damage broke out of it: a ragged notch each"""
    z = rail_z(x)
    for bx, bside, half, depth in RAIL_BREAKS[: stage["rail_breaks"]]:
        if bside != side or abs(x - bx) >= half:
            continue
        k = 1 - abs(x - bx) / half
        z -= depth * min(1.0, k * 1.6) * (0.8 + 0.2 * math.sin(x * 23.0))
    return z


# ---------------------------------------------------------------------------
# Sails and nets
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


def net_texture(name, size=256, cells=12):
    """One tile of net: diamond meshes of tarred twine with knots where they cross; the gaps are transparent"""
    n = (np.arange(size) + 0.5) / size
    xs = n[None, :] * np.ones((size, 1))
    ys = n[:, None] * np.ones((1, size))
    a = ((xs + ys) * cells) % 1
    b = ((xs - ys) * cells) % 1
    da = np.minimum(a, 1 - a)
    db = np.minimum(b, 1 - b)
    twine = (da < 0.11) | (db < 0.11)
    knot = (da < 0.17) & (db < 0.17)
    color = np.array(srgb(COLORS["net"]))
    rng = np.random.default_rng(3)
    tone = 0.85 + 0.3 * value_noise(size, 8, rng)
    rgb = color[None, None, :] * tone[..., None]
    rgb = np.where(knot[..., None], rgb * 0.75, rgb)
    rgb = np.where(twine[..., None], rgb, np.array(srgb(COLORS["net_gap"]))[None, None, :])
    alpha = np.where(twine | knot, 1.0, 0.0)
    return save_image(name, np.concatenate([np.clip(rgb, 0, 1), alpha[..., None]], axis=2))


def flag_texture(name, color, size=64):
    """The pennant's cloth: plain, with a darker hem along the hoist"""
    n = (np.arange(size) + 0.5) / size
    xs = n[None, :] * np.ones((size, 1))
    rgb = np.ones((size, size, 3)) * np.array(srgb(color))
    rgb = np.where((xs < 0.06)[..., None], rgb * 0.8, rgb)
    return save_image(name, np.concatenate([rgb, np.ones((size, size, 1))], axis=2))


def make_materials(look, stage, index, variant):
    wear = (stage["soot"], stage["char"])
    light_wear = (stage["soot"] * 0.6, stage["char"] * 0.5)
    damaged = stage["sail_holes"] > 0 or stage["sail_burn"] > 0 or stage["sail_tear"]
    suffix = f"_d{index}" if damaged else ""
    hurt = stage if damaged else None
    hue, sat, val = look["paint_hsv"]
    sail = sail_texture(
        f"fishingBoat_{variant}_sail{suffix}", look["sail"], seed=5, patches=look["sail_patches"],
        band=look["sail_band"], stage=hurt, holes=(0, 5, 3, 8, 1, 9, 6, 2, 4, 7),
    )
    net = net_texture("fishingBoat_net")
    mats = {
        "paint": scanned(
            f"Boat{variant}Paint", look["paint"], tint=look["paint_tint"], hue=hue, saturation=sat, value=val, wear=wear
        ),
        "trim": scanned(f"Boat{variant}Trim", "wood_planks", tint=look["trim"], normal=0.4, wear=wear),
        # Tar below the waterline
        "tar": scanned("BoatTar", "black_painted_planks", value=0.9, wear=(0.0, 0.0)),
        # Bare planks inside the boat, the floorboards and the thwarts: lighter, so the boat reads as open
        "inner": scanned("BoatInner", "old_planks_02", value=1.5, wear=wear),
        "deck": scanned("BoatDeck", "weathered_planks", value=1.55, wear=wear),
        "spar": scanned("BoatSpar", "wood_planks", saturation=0.9, value=0.8, wear=light_wear),
        "barrel": scanned("BoatBarrel", "wooden_barrel", value=1.35, wear=light_wear),
        "crate": scanned("BoatCrate", "wood_planks", value=1.3, wear=light_wear),
        "iron": scanned("BoatIron", "rusty_metal_02", tint=COLORS["iron"], paint=False, value=1.7, metal=0.5),
        "rope": plain("BoatRope", COLORS["rope"], rough=1.0),
        "sail": cloth(f"Boat{variant}Sail", sail, look["sail"]),
        "pennant": plain(
            f"Boat{variant}Pennant", 0xFFFFFF, rough=0.9, two_sided=True,
            image=flag_texture(f"fishingBoat_{variant}_pennant", look["pennant"]),
        ),
        "heap": netting("BoatNetHeap", net, NET_TILE * 0.6, cut=False),
        "net": netting("BoatNet", net, NET_TILE),
        "wicker": plain("BoatWicker", COLORS["wicker"], rough=0.95),
        "fish": plain("BoatFish", COLORS["fish"], rough=0.3, metal=0.6),
        "float_orange": plain("BoatFloatOrange", COLORS["float_orange"], rough=0.6),
        "float_white": plain("BoatFloatWhite", COLORS["float_white"], rough=0.6),
        "buoy": plain("BoatBuoy", COLORS["buoy"], rough=0.6),
        "flag": plain("BoatFlag", COLORS["flag"], rough=0.9, two_sided=True),
        "lath": plain("BoatLath", COLORS["lath"], rough=0.9),
        "lantern": plain("BoatLantern", COLORS["glass"], rough=0.3, emission=4.0),
        "hole": plain("BoatShotHole", COLORS["hole"], rough=1.0),
        "water": plain("BoatBilgeWater", COLORS["water"], rough=0.15),
        "burnt": plain("BoatBurnt", COLORS["burnt"], rough=1.0),
    }
    if look["mizzen"]:
        mizzen = sail_texture(
            f"fishingBoat_{variant}_mizzen{suffix}", look["sail"], size=256, seed=9, band=look["sail_band"],
            stage=hurt, holes=(6, 1, 4, 9, 0, 3, 7, 2, 5, 8),
        )
        mats["mizzen"] = cloth(f"Boat{variant}Mizzen", mizzen, look["sail"])
    return mats


# ---------------------------------------------------------------------------
# Hull
# ---------------------------------------------------------------------------

HULL_ROWS = [-0.9, -0.8, -0.55, -0.2, 0.15, 0.35, 0.75, 1.3]
TAR_TOP = 0.35  # tar below this height, paint above
STRIPE = 0.5  # height of the painted stripe under the rail
HULL_COLS = 48


def build_hull(mats, coll, stage):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.verify()
    us = [0.5 - 0.5 * math.cos(math.pi * i / HULL_COLS) for i in range(HULL_COLS + 1)]
    base_z = HULL_ROWS[-1]
    tar_rows = sum(1 for z in HULL_ROWS if z <= TAR_TOP) - 1

    def x_at(u, z):
        return x_stern(z) + u * (x_bow(z) - x_stern(z))

    # Each side has its own columns: the gunwale may be broken on one side only
    columns = {}
    for side in (1, -1):
        cols = []
        for u in us:
            top = rail_top(x_at(u, 2.6), side, stage)
            stripe = top - min(STRIPE, (top - base_z) * 0.45)
            zs = HULL_ROWS + [(base_z + stripe) / 2, stripe, top]
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

    def add_face(vs, r):
        clean = []
        for v in vs:
            if not clean or clean[-1] is not v:
                clean.append(v)
        if clean[0] is clean[-1]:
            clean.pop()
        if len(clean) < 3:
            return
        f = bm.faces.new(clean)
        # Slots: 0 paint, 1 trim, 2 tar
        f.material_index = 2 if r < tar_rows else 1 if r == rows - 2 else 0
        for loop in f.loops:
            loop[uv].uv = (loop.vert.co.x / (HULL_TILE * PLANK_STRETCH), loop.vert.co.z / HULL_TILE)

    for side in (1, -1):
        g = grid[side]
        for r in range(rows - 1):
            for c in range(len(us) - 1):
                if side == 1:
                    add_face([g[r][c], g[r + 1][c], g[r + 1][c + 1], g[r][c + 1]], r)
                else:
                    add_face([g[r][c], g[r][c + 1], g[r + 1][c + 1], g[r + 1][c]], r)

    # The transom
    for r in range(rows - 1):
        add_face([grid[-1][r][0], grid[-1][r + 1][0], grid[1][r + 1][0], grid[1][r][0]], r)
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
    # Slots: 0 paint, 1 trim, 2 tar; the inside of the planking +10, the gunwale's top +20
    for i in range(23):
        if i < 3:
            obj.data.materials.append([mats["paint"], mats["trim"], mats["tar"]][i])
        elif 10 <= i <= 12:
            obj.data.materials.append(mats["inner"])
        elif 20 <= i <= 22:
            obj.data.materials.append(mats["trim"])
        else:
            obj.data.materials.append(mats["paint"])

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
    for m in (mats["paint"], mats["trim"], mats["tar"], mats["inner"]):
        baked.materials.append(m)
    for p, i in zip(baked.polygons, indices):
        p.material_index = i
    obj.modifiers.clear()
    old = obj.data
    obj.data = baked
    bpy.data.meshes.remove(old)
    baked.name = "Hull"
    return obj


def deck_outline(z, x0, x1, steps=24):
    xs = [x0 + (x1 - x0) * i / steps for i in range(steps + 1)]
    left = [(x, inner_width(x, z), z) for x in xs if inner_width(x, z) > 0.03]
    right = [(x, -y, z) for x, y, z in reversed(left)]
    return left + right


def gunwale(x, side, stage, out=0.0):
    """A point on top of the gunwale, `out` units outboard of it"""
    z = rail_top(x, side, stage)
    return Vector((x, side * (half_width(x, z) + out), z))


def splinters(parts, center, along, up, half, rng, key="inner"):
    """Broken plank ends sticking up along a break: center and the direction along it, up out of the wood"""
    for k in range(5):
        root = center + along * (half * (k / 2 - 1))
        tip = root + up * (0.25 + 0.3 * rng.random()) + along * 0.1 * (rng.random() - 0.5)
        rod(parts[key], root, tip, 0.06, 0.01, segs=4)


def build_inside(parts, stage, rng):
    """Floorboards, thwarts, the little decks fore and aft, the stem head, the rudder and its tiller"""
    polygon(parts["deck"], deck_outline(FLOOR_Z, x_stern(FLOOR_Z) + 0.6, x_bow(FLOOR_Z) - 0.8), flip=True)
    for k, x in enumerate(THWARTS_X):
        w = inner_width(x, THWART_Z)
        if stage["thwart_split"] and k == 2:
            # Split by a shot: both halves sag to the floor from the side they still hang on
            for side in (1, -1):
                a = Vector((x, side * w, THWART_Z))
                b = Vector((x + 0.15 * side, side * 0.25, THWART_Z - 0.75))
                d = b - a
                axes = (Vector((1, 0, 0)), d.normalized(), Vector((1, 0, 0)).cross(d.normalized()))
                box(parts["deck"], (a + b) / 2, (0.7, d.length, 0.14), axes)
                splinters(parts, b, Vector((1, 0, 0)), d.normalized(), 0.28, rng, "deck")
            continue
        box(parts["deck"], (x, 0, THWART_Z), (0.7, 2 * w, 0.14))
        # Knees holding it to the side
        for side in (1, -1):
            box(parts["inner"], (x, side * (w - 0.15), THWART_Z - 0.35), (0.16, 0.3, 0.7))

    zf = rail_z(FOREDECK_X) - 0.22
    polygon(parts["deck"], deck_outline(zf, FOREDECK_X, x_bow(zf) - 0.05, 10), flip=True)
    box(parts["inner"], (FOREDECK_X, 0, zf - 0.12), (0.2, 2 * inner_width(FOREDECK_X, zf), 0.24))
    za = aftdeck_z()
    polygon(parts["deck"], deck_outline(za, x_stern(za) + 0.05, AFTDECK_X, 10), flip=True)
    box(parts["inner"], (AFTDECK_X, 0, za - 0.12), (0.2, 2 * inner_width(AFTDECK_X, za), 0.24))

    # The stem head standing above the bow
    top = rail_z(x_bow(3.3))
    rod(parts["trim"], (x_bow(top - 1.0) - 0.1, 0, top - 1.0), (x_bow(top + 0.4) - 0.05, 0, top + 0.45), 0.13, 0.11, segs=6)

    # The rudder hung on the transom, and the tiller over the afterdeck
    xr = x_stern(1.0)
    pts = [(xr - 0.15, 0, -0.7), (xr - 1.05, 0, -0.45), (xr - 0.95, 0, 1.0), (x_stern(2.4) - 0.25, 0, 2.4), (x_stern(2.4) - 0.1, 0, 2.95), (x_stern(-0.6) - 0.05, 0, -0.6)]
    for dy in (0.08, -0.08):
        polygon(parts["paint"], [(x, dy, z) for x, _, z in pts], flip=dy < 0)
    head = Vector((x_stern(2.8) - 0.2, 0, 2.85))
    rod(parts["spar"], head, (-5.6, 0.1, 3.15), 0.09, 0.07, segs=6)


def build_mast(parts, stage):
    """The mast with its lug sail, yard, halyard and pennant. In stage 4 only its stump is left: fallen_rig() lays
    the rest over the side"""
    mt = Matrix.Translation((MAST_X, 0, 0))
    if stage["mast_broken"]:
        lathe(parts["spar"], [(0.26, FLOOR_Z), (0.24, MAST_BREAK_Z - 0.3), (0.15, MAST_BREAK_Z + 0.1), (0.04, MAST_BREAK_Z + 0.4)], 10, mt, uv_along=SPAR_TILE)
        rng = np.random.default_rng(5)
        splinters(parts, Vector((MAST_X - 0.1, 0, MAST_BREAK_Z - 0.1)), Vector((0, 1, 0)), Vector((0, 0, 1)), 0.16, rng, "spar")
        return
    lathe(parts["spar"], [(0.26, FLOOR_Z), (0.24, THWART_Z + 0.5), (0.15, MAST_TOP), (0.18, MAST_TOP + 0.1), (0.04, MAST_TOP + 0.3)], 10, mt, uv_along=SPAR_TILE)
    lug_sail(parts, MAST_X, LUG, "sail", 0.12, MAST_TOP - 0.6)

    # A pennant streaming from the masthead; damage shreds it, fire burns it away
    if stage["pennant"] > 0:
        length = 3.4 * stage["pennant"]
        z0 = MAST_TOP + 0.1

        def pennant(u, v):
            half = 0.32 * (1 - u) + 0.05
            return Vector((MAST_X - 0.1 - length * u, 0.35 * math.sin(u * 4.0) * u, z0 - 0.35 + (v * 2 - 1) * half))

        grid_surface(parts["pennant"], pennant, 10, 2)


def braced(mast_x, along, across, z):
    """A point in a sail's frame (along = forward, across = to port), the sail sheeted out to port by BRACE"""
    c, s = math.cos(-BRACE), math.sin(-BRACE)
    return Vector((mast_x + along * c - across * s, along * s + across * c, z))


def lug_sail(parts, mast_x, corners, key, yard_r, halyard_z):
    """A lug sail: four corners, the head laced to a yard slung across the mast; it bellies out to leeward, to port"""
    tack, throat, peak, clew = (Vector(corners[k]) for k in ("tack", "throat", "peak", "clew"))

    def point(u, v):
        foot = tack.lerp(clew, u)
        head = throat.lerp(peak, u)
        along, z = foot.lerp(head, v)
        # Laced to the yard along the head, loose along the foot
        belly = SAIL_BELLY * math.sin(math.pi * u) ** 0.8 * math.sin(math.pi * (0.15 + 0.85 * v)) ** 0.7
        # A sail's foot sags a little between its corners
        z -= 0.25 * math.sin(math.pi * u) * (1 - v) ** 3
        return braced(mast_x, along, belly, z)

    grid_surface(parts[key], point, 16, 12)
    # The yard along the head, a little longer than it at both ends
    d = (peak - throat).normalized()
    lift = Vector((0, 0.15))
    a2 = throat - d * 0.5 + lift
    b2 = peak + d * 0.4 + lift
    a = braced(mast_x, a2.x, 0, a2.y)
    b = braced(mast_x, b2.x, 0, b2.y)
    rod(parts["spar"], a, b, yard_r, yard_r * 0.6, segs=6, uv_along=SPAR_TILE)
    # The halyard from the yard up to the masthead
    rod(parts["rope"], a.lerp(b, 0.3), (mast_x, 0, halyard_z), 0.035, segs=4, caps=False)


def build_rigging(parts, stage):
    """Shrouds from the masthead to the gunwale and a forestay to the stem; the sheet from the clew to the port
    quarter. In stage 4 the mast took them with it"""
    if stage["mast_broken"]:
        return
    rope = parts["rope"]
    head = Vector((MAST_X, 0, MAST_TOP - 1.2))
    for side in (1, -1):
        for dx in (-0.9, -2.2):
            rod(rope, head + Vector((0, side * 0.15, 0)), gunwale(MAST_X + dx, side, stage, 0.05), 0.04, segs=4, caps=False)
    rod(rope, head, (x_bow(rail_z(9.5) + 0.4) - 0.05, 0, rail_z(9.5) + 0.4), 0.04, segs=4, caps=False)
    clew = braced(MAST_X, LUG["clew"][0], 0, LUG["clew"][1])
    rod(rope, clew, gunwale(-7.0, 1, stage, 0.0), 0.035, segs=4, caps=False)


def fallen_rig(parts, stage, tilt):
    """Stage 4: the mast snapped and went over the port side. It rests on the gunwale with its head in the water, the
    yard floats alongside and the sail spreads on the water between them. Built over the listed boat (tilt is the
    boat's list and sinking), so what floats lies on the water"""
    head = Vector((MAST_X + 1.8, 8.8, 0.12))
    rest = tilt @ gunwale(MAST_X + 1.1, 1, stage, 0.05) + Vector((0, 0, 0.2))
    d = (rest - head).normalized()
    foot = head + d * (MAST_TOP - MAST_BREAK_Z)
    rod(parts["spar"], foot, head, 0.22, 0.15, segs=10, uv_along=SPAR_TILE)
    splinters(parts, foot, Vector((1, 0, 0)), d, 0.15, np.random.default_rng(8), "spar")

    # The yard alongside, half awash, and the sail spread from it back to the gunwale, where its foot is still caught
    tack, throat, peak, clew = (Vector(LUG[k]) for k in ("tack", "throat", "peak", "clew"))
    yard_a = Vector((MAST_X + 2.2, 8.0, 0.14))
    yard_b = yard_a + Vector((-1.0, 0.12, 0)).normalized() * ((peak - throat).length + 0.9)
    rod(parts["spar"], yard_a, yard_b, 0.12, 0.07, segs=6, uv_along=SPAR_TILE)
    rng = np.random.default_rng(9)
    phases = [rng.random() * 6.28 for _ in range(3)]

    def point(u, v):
        x = MAST_X + tack.x + (clew.x - tack.x) * u
        caught = tilt @ gunwale(x, 1, stage, -0.4) + Vector((0, 0, 0.1))
        over = tilt @ gunwale(x, 1, stage, 0.25) + Vector((0, 0, 0.12))
        yard = yard_a.lerp(yard_b, 0.04 + 0.9 * u) + Vector((0, -0.25, 0))
        if v < 0.12:
            return caught.lerp(over, v / 0.12)
        k = (v - 0.12) / 0.88
        p = over.lerp(yard, k)
        # Down the side to the water, then floating in folds out to the yard
        wave = 0.08 * sum(math.sin(u * (9 + 4 * i) + v * (5 + 3 * i) + ph) for i, ph in enumerate(phases))
        p.z = max(0.07 + wave * min(1.0, k * 4), over.z * (1 - k * 3)) if k < 0.33 else 0.07 + wave
        return p

    grid_surface(parts["sail"], point, 16, 14)


def build_mizzen(parts, stage):
    """The pots boat's little mizzen at the transom, sheeted to a spar out over the stern"""
    mt = Matrix.Translation((MIZZEN_X, 0, 0))
    lathe(parts["spar"], [(0.15, FLOOR_Z + 0.5), (0.1, MIZZEN_TOP), (0.03, MIZZEN_TOP + 0.2)], 8, mt, uv_along=SPAR_TILE)
    lug_sail(parts, MIZZEN_X, MIZZEN, "mizzen", 0.08, MIZZEN_TOP - 0.3)
    root = Vector((x_stern(2.6) + 0.3, 0.25, 2.65))
    end = Vector((MIZZEN_X + MIZZEN["clew"][0] - 0.8, 0.1, 2.75))
    rod(parts["spar"], root, end, 0.08, 0.06, segs=6)
    clew = braced(MIZZEN_X, MIZZEN["clew"][0], 0, MIZZEN["clew"][1])
    rod(parts["rope"], clew, end, 0.03, segs=4, caps=False)


# ---------------------------------------------------------------------------
# Gear and catch
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
    for zz in (0.12, h - 0.12):
        rr = r * 0.92 + 0.03
        lathe(parts["iron"], [(rr, zz - 0.04), (rr, zz + 0.04)], 12, m, False, False)


def crate(parts, x, y, z, s, rot):
    axes = turned(rot)
    box(parts["crate"], (x, y, z + s / 2), (s, s, s), axes)
    for k in (-1, 1):
        c = Vector((x, y, z + s / 2)) + axes[0] * (k * s * 0.42)
        box(parts["spar"], c, (0.1, s + 0.03, s + 0.03), axes)


def basket(parts, x, y, z, r, h, fish=True):
    """A wicker basket, full of silver fish to the brim"""
    m = Matrix.Translation((x, y, z))
    lathe(parts["wicker"], [(r * 0.8, 0), (r, h * 0.8), (r * 1.05, h)], 10, m, cap_top=False)
    lathe(parts["wicker"], [(r * 1.05, h), (r * 1.12, h + 0.06), (r * 0.98, h + 0.06)], 10, m, False, False)
    if fish:
        lathe(parts["fish"], [(r * 0.98, h - 0.05), (r * 0.6, h + 0.12), (0.01, h + 0.16)], 10, m, False, False)


def coil(parts, x, y, z, r=0.5):
    m = Matrix.Translation((x, y, z))
    for k in range(3):
        rr = r - k * 0.11
        lathe(parts["rope"], [(rr, 0.02 + k * 0.08), (rr + 0.09, 0.05 + k * 0.08), (rr, 0.1 + k * 0.08)], 12, m, False, False)


def oar(parts, a, b):
    a, b = Vector(a), Vector(b)
    rod(parts["spar"], a, b, 0.07, segs=5, uv_along=SPAR_TILE)
    d = (b - a).normalized()
    side = d.cross(Vector((0, 0, 1))).normalized()
    box(parts["spar"], b - d * 0.6, (1.3, 0.34, 0.05), (d, side, d.cross(side)))


def anchor(parts, x, y, z):
    """A small grapnel lying on the foredeck with its rope coiled by it"""
    rod(parts["iron"], (x - 0.7, y, z + 0.08), (x + 0.5, y, z + 0.08), 0.06, segs=5)
    for a in angles(4):
        d = Vector((0.0, math.cos(a), math.sin(a))) * 0.35
        tip = Vector((x - 0.7, y, z + 0.08)) + d + Vector((0.25, 0, 0))
        rod(parts["iron"], (x - 0.7, y, z + 0.08), tip, 0.05, segs=4)
    coil(parts, x + 0.1, y - 0.75, z, 0.32)


def lobster_pot(parts, x, y, z, rot=0.0):
    """A pot: a frame of laths with a net stretched over it, an entrance hole in each end"""
    sx, sy, sz = 1.2, 0.8, 0.62
    axes = turned(rot)
    c = Vector((x, y, z + sz / 2))
    box(parts["net"], c, (sx, sy, sz), axes)
    ex, ey, ez = axes[0] * (sx / 2), axes[1] * (sy / 2), axes[2] * (sz / 2)
    # The frame's twelve edges: four along each axis
    for a, b, e in ((ey, ez, ex), (ex, ez, ey), (ex, ey, ez)):
        for i in (-1, 1):
            for j in (-1, 1):
                rod(parts["lath"], c + a * i + b * j - e, c + a * i + b * j + e, 0.035, segs=4)
    for s in (-1, 1):
        rod(parts["lath"], c + ex * (s * 0.5) - ey, c + ex * (s * 0.5) + ey, 0.03, segs=4)


def marker_buoy(parts, x, y, z):
    """A float with a pole and a little black flag: it marks where a string of pots lies"""
    ball(parts["buoy"], (x, y, z + 0.35), 0.35, 10, 1.0)
    rod(parts["spar"], (x, y, z + 0.5), (x, y, z + 2.1), 0.04, segs=5)
    polygon(parts["flag"], [(x, y, z + 2.1), (x - 0.55, y + 0.05, z + 1.95), (x - 0.55, y + 0.05, z + 1.65), (x, y, z + 1.75)])


HEAP = dict(x=-0.6, y=0.35, rx=2.4, ry=2.1, h=2.0)  # the nets boat's heap amidships


def heap_z(x, y):
    """Height of the top of the heap of nets"""
    r = math.hypot((x - HEAP["x"]) / HEAP["rx"], (y - HEAP["y"]) / HEAP["ry"])
    return FLOOR_Z + HEAP["h"] * max(0.0, 1 - r * r) ** 0.55


def net_heap(parts, rng):
    """Nets piled in the middle of the boat: a lumpy mound of twine"""
    x, y, rx, ry = HEAP["x"], HEAP["y"], HEAP["rx"], HEAP["ry"]
    bumps = [(rng.random() * 6.28, 0.6 + rng.random()) for _ in range(5)]

    def point(u, v):
        a = 2 * math.pi * u
        r = 1 - v
        lump = 1 + 0.12 * sum(math.sin(k * a + p) * s for k, (p, s) in enumerate(bumps, 2)) / len(bumps)
        px, py = x + rx * r * math.cos(a) * lump, y + ry * r * math.sin(a) * lump
        return Vector((px, py, heap_z(x + rx * r * math.cos(a), y + ry * r * math.sin(a)) * lump))

    grid_surface(parts["heap"], point, 24, 8, (rx * 2 * math.pi, max(rx, ry)))


def drape_net(parts, x0, x1, side, stage, floats):
    """A net hung over the gunwale to dry: from the heap over the rail and down the outside, corks on its foot"""

    def point(u, v):
        x = x0 + (x1 - x0) * u
        sag = 0.25 * math.sin(math.pi * u)
        top = rail_top(x, side, stage) + 0.08
        w = half_width(x, top)
        if v < 0.35:  # inside, up from the heap to the rail
            k = v / 0.35
            return Vector((x, side * (w - 0.9 + 0.9 * k), top - 0.7 * (1 - k) ** 2 - sag * (1 - k)))
        k = (v - 0.35) / 0.65  # outside, down the planking
        z = top - (top - 0.55 - sag) * k
        p, n = hull_point(x, max(z, 0.4), side)
        return p + n * 0.06 + Vector((0, 0, z - max(z, 0.4)))

    grid_surface(parts["net"], point, 12, 8, (x1 - x0, 3.0))
    for i in range(floats):
        p = point((i + 0.5) / floats, 1.0)
        ball(parts["float_orange" if i % 2 == 0 else "float_white"], p + Vector((0, side * 0.12, 0.0)), 0.2, 8, 0.8)


def build_catch(parts, stage, look, rng):
    """What fills the boat, by its look. Each list is ordered so the last items go first: a stage keeps the first
    `cargo` share of it"""
    cargo = look["cargo"]
    if cargo == "nets":
        net_heap(parts, rng)
        drape_net(parts, -2.6, 1.4, -1, stage, 5)
        items = [
            lambda: basket(parts, 4.0, 1.45, FLOOR_Z, 0.55, 0.8),
            lambda: coil(parts, 4.0, -1.4, FLOOR_Z, 0.5),
            lambda: basket(parts, -5.3, -1.1, FLOOR_Z + 0.05, 0.5, 0.75),
            lambda: basket(parts, 4.1, -0.2, FLOOR_Z, 0.5, 0.7),
            lambda: basket(parts, -5.2, 1.2, FLOOR_Z + 0.05, 0.5, 0.75, fish=False),
        ]
        corks = [(-2.6, 1.8), (-1.4, 2.25), (0.3, 2.0), (1.2, 1.1), (-0.2, -1.2), (-1.9, -1.0), (-2.9, 0.4), (0.9, -0.3)]
        for i, (cx, cy) in enumerate(corks):
            key = "float_orange" if i % 3 else "float_white"
            items.append(lambda cx=cx, cy=cy, key=key: ball(parts[key], (cx, cy, heap_z(cx, cy) + 0.12), 0.22, 8, 0.8))
    elif cargo == "barrels":
        items = [
            lambda: barrel(parts, -0.6, 1.35, FLOOR_Z, 0.55, 1.25),
            lambda: barrel(parts, -0.6, -1.3, FLOOR_Z, 0.55, 1.25),
            lambda: barrel(parts, -2.0, 1.25, FLOOR_Z, 0.55, 1.25),
            lambda: crate(parts, -5.3, 0.9, FLOOR_Z, 0.95, 0.15),
            lambda: barrel(parts, -2.0, -1.2, FLOOR_Z, 0.55, 1.25),
            lambda: barrel(parts, 0.75, 0.0, FLOOR_Z, 0.5, 1.15),
            lambda: crate(parts, -5.2, -0.95, FLOOR_Z, 0.9, -0.2),
            lambda: barrel(parts, 4.0, 0.0, FLOOR_Z + 0.5, 0.45, 1.6, axis=(0, 1, 0)),
            lambda: barrel(parts, -2.0, 0.05, FLOOR_Z + 0.5, 0.42, 1.0),
            lambda: crate(parts, -5.25, 0.85, FLOOR_Z + 0.95, 0.75, 0.6),
            # A second tier lying on the first, over the gunwale
            lambda: barrel(parts, -1.3, -1.25, FLOOR_Z + 1.67, 0.42, 1.35, axis=(1, 0, 0)),
            lambda: barrel(parts, -1.3, 1.3, FLOOR_Z + 1.67, 0.42, 1.35, axis=(1, 0, 0)),
        ]
        # The lantern on its post at the stern stays, whatever the damage
        post = Vector((-8.3, 0.9, aftdeck_z()))
        rod(parts["spar"], post, post + Vector((0, 0, 1.6)), 0.05, segs=5)
        lathe(parts["lantern"], [(0.16, 1.45), (0.2, 1.65), (0.14, 1.85)], 6, Matrix.Translation(post))
        lathe(parts["iron"], [(0.2, 1.85), (0.06, 2.05)], 6, Matrix.Translation(post), cap_bottom=True)
    else:
        items = [
            lambda: lobster_pot(parts, -2.4, 0.95, FLOOR_Z, 0.05),
            lambda: lobster_pot(parts, -2.4, -0.95, FLOOR_Z, -0.05),
            lambda: lobster_pot(parts, -0.95, 1.0, FLOOR_Z, 0.0),
            lambda: coil(parts, 4.0, 1.3, FLOOR_Z, 0.5),
            lambda: lobster_pot(parts, -0.95, -1.0, FLOOR_Z, 0.08),
            lambda: marker_buoy(parts, -7.2, -1.35, aftdeck_z()),
            lambda: lobster_pot(parts, 0.45, 0.6, FLOOR_Z, -0.1),
            lambda: lobster_pot(parts, -1.7, 0.45, FLOOR_Z + 0.62, 0.1),
            lambda: marker_buoy(parts, -7.9, -0.6, aftdeck_z()),
            lambda: lobster_pot(parts, -0.25, 0.1, FLOOR_Z + 0.62, 0.15),
            lambda: coil(parts, 4.1, -1.2, FLOOR_Z, 0.45),
            lambda: lobster_pot(parts, -1.6, -0.5, FLOOR_Z + 0.62, -0.12),
            lambda: lobster_pot(parts, -1.0, 0.0, FLOOR_Z + 1.24, 0.05),
        ]
    for add in keep(items, stage["cargo"]):
        add()

    # Gear every boat carries: the oars on the thwarts and a grapnel on the foredeck
    oars = (((-5.3, 1.9, THWART_Z + 0.12), (5.6, 1.45, THWART_Z + 0.16)), ((-5.0, -2.0, THWART_Z + 0.12), (5.8, -1.55, THWART_Z + 0.16)))
    for a, b in oars[: stage["oars"]]:
        oar(parts, a, b)
    anchor(parts, 8.4, 0.35, rail_z(FOREDECK_X) - 0.22)


def build_damage(parts, stage, rng):
    """Shot holes in the hull with scorched rims and splinters, and broken plank ends where the gunwale broke"""
    for x, z, side, r in HULL_HOLES[: stage["hull_holes"]]:
        p, n = hull_point(x, z, side)
        t, n, b = side_frame(n)
        center = p + n * 0.03
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
        # Scorched wood round the hole, a little behind it
        scorch = [center - n * 0.015 + (q - center) * (1.5 + 0.2 * rng.random()) for q in rim]
        face = polygon(parts["burnt"], scorch)
        face.normal_update()
        if face.normal.dot(n) < 0:
            face.normal_flip()
        for _ in range(4):
            a = rng.random() * 2 * math.pi
            d = t * math.cos(a) + b * math.sin(a)
            root = center + d * r * 0.85
            tip = root + d * r * (0.5 + 0.5 * rng.random()) + n * (0.12 + 0.2 * rng.random())
            rod(parts["paint"], root, tip, 0.06, 0.015, segs=4)

    # Broken plank ends standing up at both ends of a chunk gone from the gunwale
    for bx, side, half, _ in RAIL_BREAKS[: stage["rail_breaks"]]:
        for end in (-1, 1):
            x = bx + end * half * 0.85
            top = gunwale(x, side, stage)
            splinters(parts, top, Vector((1, 0, 0)), Vector((0, side * 0.2, 1)).normalized(), 0.12, rng, "paint")



def bilge_water(parts, tilt):
    """Water in a boat listing and low in the water: the sea's level inside the hull, over the floorboards where they
    went under. Built over the listed boat, from where its inside meets the waterline"""
    level = 0.04

    def wet_z(x, side):
        # Bisection for the height on the inside of the planking that the list and the sinking bring to the level
        lo, hi = KEEL_Z, rail_z(x)
        for _ in range(30):
            mid = (lo + hi) / 2
            p = tilt @ Vector((x, side * inner_width(x, mid), mid))
            lo, hi = (mid, hi) if p.z < level else (lo, mid)
        return (lo + hi) / 2

    xs = [x_stern(1.0) + 0.3 + (x_bow(0.0) - 0.4 - x_stern(1.0)) * i / 30 for i in range(31)]
    edge = []
    for side in (1, -1):
        for x in xs if side == 1 else reversed(xs):
            z = wet_z(x, side)
            p = tilt @ Vector((x, side * inner_width(x, z), z))
            edge.append((p.x, p.y, level))
    polygon(parts["water"], edge, flip=True)


def build_debris(parts, stage, look, rng):
    """Wreckage floating round the boat: planks, an oar, corks, and its catch. Built on the water, not listed with
    the boat"""
    cargo = look["cargo"]
    for i in range(stage["debris"]):
        a = rng.random() * 2 * math.pi
        dist = 9 + 5 * rng.random()
        c = Vector((math.cos(a) * dist * 1.3, math.sin(a) * dist, 0.06))
        rot = rng.random() * math.pi
        kind = i % 4
        if kind == 1 and cargo == "barrels":
            barrel(parts, c.x, c.y, -0.15, 0.45, 1.1, axis=(math.cos(rot), math.sin(rot), 0))  # floating on its side
        elif kind == 1 and cargo == "pots":
            lobster_pot(parts, c.x, c.y, -0.3, rot)
        elif kind == 1:
            basket(parts, c.x, c.y, -0.45, 0.5, 0.75, fish=False)
        elif kind == 2:
            for j in range(3):
                q = c + Vector((math.cos(rot + j), math.sin(rot + j), 0)) * 0.6
                ball(parts["float_orange" if j else "float_white"], (q.x, q.y, 0.0), 0.22, 8, 0.8)
        elif kind == 3:
            oar(parts, c - Vector((math.cos(rot), math.sin(rot), 0)) * 2.4, c + Vector((math.cos(rot), math.sin(rot), 0.02)) * 1.0)
        else:
            # Light planks: dark ones would read as black specks on the water
            box(parts["deck"], c, (2.0 + rng.random(), 0.35, 0.12), turned(rot))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

OBJECT_NAMES = {
    "paint": "Rudder",
    "trim": "StemHead",
    "inner": "Knees",
    "deck": "Boards",
    "spar": "Spars",
    "rope": "Rigging",
    "sail": "Sail",
    "mizzen": "Mizzen",
    "pennant": "Pennant",
    "barrel": "Barrels",
    "crate": "Crates",
    "iron": "Iron",
    "heap": "NetHeap",
    "net": "Nets",
    "wicker": "Baskets",
    "fish": "Fish",
    "float_orange": "FloatsOrange",
    "float_white": "FloatsWhite",
    "buoy": "Buoys",
    "flag": "Flags",
    "lath": "Laths",
    "lantern": "Lantern",
    "hole": "ShotHoles",
    "water": "BilgeWater",
    "burnt": "Scorch",
}
# Parts whose UVs come from box projection, with the tile size that sets the plank width
BOX_UV_TILE = {
    "paint": HULL_TILE,
    "trim": HULL_TILE,
    "inner": HULL_TILE,
    "deck": DECK_TILE,
    "spar": SPAR_TILE,
    "crate": 2.0,
    "iron": 2.0,
    "net": 1.0,  # in units: the net's material scales it by NET_TILE
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


def build(damage=None, variant=None):
    """damage: stage (see DAMAGE_STAGES), variant: a name from VARIANTS; by default the scene's "damage" and
    "variant" custom properties, or 0 and the first look"""
    scene = bpy.context.scene
    if damage is None:
        damage = int(scene.get("damage", 0))
    damage = damage if damage in DAMAGE_STAGES else 0
    if variant is None:
        variant = str(scene.get("variant", VARIANT_NAMES[0]))
    variant = variant if variant in VARIANTS else VARIANT_NAMES[0]
    stage = DAMAGE_STAGES[damage]
    look = VARIANTS[variant]
    scene["damage"] = damage
    scene["variant"] = variant
    clear_previous()
    coll = bpy.data.collections.new("Ship")
    scene.collection.children.link(coll)

    mats = make_materials(look, stage, damage, variant)
    # render_sprites.py turns the object named "Ship"; everything else is parented to it
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 6
    coll.objects.link(root)

    hull = build_hull(mats, coll, stage)
    hull.parent = root

    parts = Parts()
    rng = np.random.default_rng(11)
    build_inside(parts, stage, rng)
    build_mast(parts, stage)
    build_rigging(parts, stage)
    if look["mizzen"]:
        build_mizzen(parts, stage)
    build_catch(parts, stage, look, np.random.default_rng(3))
    build_damage(parts, stage, rng)

    # A badly damaged boat sits lower in the water and lists to port. What floats round it is built after, on the water
    tilt = Matrix.Translation((0, 0, -stage["sink"])) @ Matrix.Rotation(-math.radians(stage["list_deg"]), 4, "X")
    add_objects(parts, mats, coll, root)
    for obj in coll.objects:
        if obj.type == "MESH":
            obj.data.transform(tilt)
    afloat = Parts()
    if stage["list_deg"] or stage["sink"]:
        bilge_water(afloat, tilt)
    build_debris(afloat, stage, look, rng)
    if stage["mast_broken"]:
        fallen_rig(afloat, stage, tilt)
    add_objects(afloat, mats, coll, root, "Afloat")
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
        mesh.materials.append(mats[key])
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        obj.parent = root


if __name__ == "__main__":
    build()

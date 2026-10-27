"""
Frigate (line "european", game class "frigate"), built from code: the European line's tier 3. Three masts, the fore
and the main with a course, a topsail and a topgallant each, the mizzen with a spanker and a topsail, two headsails
on a long bowsprit; three tiers of guns: a lower battery of eleven ports a side in the hull, the main battery in the
waist and light guns on the quarterdeck and the forecastle; a stern of two tiers of gallery windows under the royal
crest. Dark varnished planks with two royal blue strakes between gilt mouldings, like the Corsair, only more of it.

Run in Blender: open frigate.blend next to this file, Scripting tab -> Open -> build.py -> Run Script.
It rebuilds the "Ship" collection of the open file, so render_sprites.py works on it unchanged.

Damage: build(damage) builds one of the game's five damage stages by the scene's "damage" property (0-4, see
DAMAGE_STAGES); render_stages.py renders them all. Each stage keeps the damage of the one before and adds to it:
1 soot, shot holes in the hull and the sails; 2 more holes, a torn sail, broken rails, lost gunport lids, dark windows;
3 charred wood and sails burnt from the foot (the game adds the fire); 4 the foremast down over the bow, the main
topmast gone, listing to port, low in the water, wreckage alongside (the game animates the sinking).

Axes and scale match the game: 1 Blender unit = 1 game unit, the bow points to +X, port side to +Y, Z up,
waterline at Z = 0. Hull about 55 units long over the beakhead (the Corsair's 42).

Textures: scanned CC0 wood and metal from Poly Haven (polyhaven.com), shared by all ships in
blender-assets/textures/polyhaven/ and downloaded there on the first run if missing; the sails are generated into
textures/ next to this file. They are linked by relative paths, not packed.
"""

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

KEEL_Z = -2.8
DECK_Z = 7.4  # the upper deck, open in the waist: the main battery stands on it
FORE_Z = 9.9  # forecastle deck
FORE_BACK = 14.5  # back wall of the forecastle
QUARTER_Z = 10.6  # quarterdeck, over the captain's cabin
QUARTER_FRONT = -12.5  # front wall of the quarterdeck
BEAM = 8.8  # largest half-width of the hull
WALL = 0.36  # hull wall thickness

# Masts: where they stand, how high, the square sails on each (bottom, top, half-width at the foot and at the head),
# the top (the platform over the lower mast) and the cross-trees (over the topmast). The mizzen's lowest sail is the
# spanker, fore and aft: its foot on a boom, its head on a gaff, both reaching aft (SPANKER)
MASTS = {
    "fore": dict(x=14.0, top=DECK_Z + 39.0, top_z=25.7, cross_z=37.0,
                 sails=((14.6, 24.5, 10.2, 9.4), (27.0, 36.0, 8.2, 6.8), (38.0, 43.4, 5.8, 4.8))),
    "main": dict(x=-0.5, top=DECK_Z + 43.0, top_z=27.2, cross_z=39.5,
                 sails=((15.2, 26.0, 11.4, 10.4), (28.6, 38.5, 9.0, 7.4), (40.6, 46.6, 6.4, 5.2))),
    "mizzen": dict(x=-15.5, top=DECK_Z + 31.5, top_z=25.4, cross_z=34.0,
                   sails=((26.8, 33.2, 6.6, 5.4),)),
}
SPANKER = dict(foot=14.0, head=24.0, boom=12.0, gaff=9.6, peak=3.6)  # heights, the boom's and gaff's length, the peak's rise
SAIL_BELLY = 3.4  # how far a course bulges forward; the sails above it bulge a little less
SAIL_CREASE = 0.22  # depth of the creases under the yard
BRACE = 0.36  # radians: the yards are turned a little so the sails read from the side too
BOWSPRIT_TIP = Vector((47.0, 0, 18.5))

# Guns: rows of ports along each side, each port a pair (port and starboard). The lower battery's ports are cut in the
# hull below the upper deck, the guns behind them out of sight but their muzzles; the main battery's stand on the
# upper deck in the waist; light guns stand on the quarterdeck and the forecastle, firing through their bulwarks
# prettier-ignore
GUN_ROWS = (
    dict(name="lower", xs=(-20.0, -16.6, -13.2, -9.8, -6.4, -3.0, 0.4, 3.8, 7.2, 10.6, 14.0), z=4.5, deck=None, lids=True, scale=1.0),
    dict(name="main", xs=(-10.4, -7.2, -4.0, -0.8, 2.4, 5.6, 8.8, 12.0), z=DECK_Z + 0.85, deck=DECK_Z, lids=True, scale=1.0),
    dict(name="quarter", xs=(-23.2, -20.4, -17.6), z=QUARTER_Z + 0.8, deck=QUARTER_Z, lids=False, scale=0.75),
    dict(name="fore", xs=(17.6, 20.4), z=FORE_Z + 0.8, deck=FORE_Z, lids=False, scale=0.75),
)

# Real-world size of one texture tile, in game units: sets the plank width on the model
HULL_TILE = 10.0
PLANK_STRETCH = 2.2  # hull planks are long boards, so the tile is stretched along the hull
DECK_TILE = 5.6
SPAR_TILE = 5.6

# Paint and trim colors (sRGB)
COLORS = {
    "royal": 0x2C4F9E,  # royal blue
    "gold_paint": 0xE3B24C,
    "brass": 0xD9A646,
    "lid": 0xA9342B,  # the inside of the gunport lids
    "iron": 0x34343A,
    "sail": 0xE07A30,  # canvas dyed orange
    "crest_blue": 0x23468F,
    "crest_gold": 0xE8B547,
    "rope": 0x8E6B44,
    "port": 0x1C130D,
    "glass": 0xFFCF73,
    "flag_blue": 0x2B4FA3,
    "flag_white": 0xF4F0E4,
    "flag_gold": 0xF0BC40,
    "grate": 0x3A2717,
    "soot": 0x1E1712,
    "char": 0x1A130E,
    "burnt": 0x2B1E15,
    "boat": 0xB9874F,
}

# What each damage stage does to the model. Holes, posts, lids and debris are taken from the lists below in order, so
# every stage keeps the damage of the previous one and adds to it. pennants: what is left of the main's, the fore's and
# the mizzen's
# prettier-ignore
DAMAGE_STAGES = {
    0: dict(soot=0.0, char=0.0, hull_holes=0, sail_holes=0, sail_tear=False, sail_burn=0.0, rail_lost=0,
            lanterns_out=0, windows_out=0, lids_lost=0, pennants=(1.0, 1.0, 1.0), crates=6, ropes_lost=0,
            mast_broken=False, list_deg=0.0, sink=0.0, debris=0),
    1: dict(soot=0.3, char=0.0, hull_holes=4, sail_holes=4, sail_tear=False, sail_burn=0.0, rail_lost=4,
            lanterns_out=0, windows_out=1, lids_lost=2, pennants=(0.8, 0.85, 0.85), crates=6, ropes_lost=0,
            mast_broken=False, list_deg=0.0, sink=0.0, debris=0),
    2: dict(soot=0.5, char=0.0, hull_holes=9, sail_holes=8, sail_tear=True, sail_burn=0.0, rail_lost=10,
            lanterns_out=1, windows_out=5, lids_lost=6, pennants=(0.5, 0.6, 0.6), crates=4, ropes_lost=3,
            mast_broken=False, list_deg=1.5, sink=0.2, debris=0),
    3: dict(soot=0.65, char=0.3, hull_holes=13, sail_holes=11, sail_tear=True, sail_burn=0.36, rail_lost=16,
            lanterns_out=2, windows_out=10, lids_lost=11, pennants=(0.0, 0.4, 0.3), crates=3, ropes_lost=6,
            mast_broken=False, list_deg=3.0, sink=0.45, debris=4),
    4: dict(soot=0.75, char=0.45, hull_holes=18, sail_holes=14, sail_tear=True, sail_burn=0.5, rail_lost=28,
            lanterns_out=3, windows_out=20, lids_lost=20, pennants=(0.0, 0.0, 0.0), crates=1, ropes_lost=99,
            mast_broken=True, list_deg=8.0, sink=1.2, debris=12),
}
# Shot holes in the hull: x, height, side (+1 port, -1 starboard), radius. A sprite shows about 3 pixels per unit, so
# a hole much smaller than a unit is lost; most sit between the waterline and the gilt wale, some in the blue strakes
# prettier-ignore
HULL_HOLES = [
    (-5.0, 2.4, -1, 1.1), (9.0, 2.2, 1, 1.2), (-15.0, 3.0, 1, 1.0), (14.5, 2.8, -1, 1.1), (1.5, 1.7, 1, 1.3),
    (-10.5, 1.6, -1, 1.4), (18.5, 2.4, 1, 1.0), (5.2, 6.3, -1, 0.9), (-18.5, 2.2, -1, 1.2), (-3.0, 6.2, 1, 0.9),
    (11.0, 1.4, -1, 1.3), (-7.5, 3.2, 1, 1.2), (-21.0, 6.4, 1, 1.0), (21.0, 5.9, -1, 0.9), (-1.0, 2.9, -1, 1.2),
    (7.5, 6.5, 1, 0.9), (-13.0, 6.3, -1, 1.0), (16.5, 1.8, 1, 1.1),
]
# Holes in a sail, in its texture: u across, v up, radius. Each sail picks its own share of them (a seed per sail)
SAIL_HOLES = [
    (0.3, 0.58, 0.05), (0.72, 0.33, 0.045), (0.55, 0.82, 0.035), (0.16, 0.25, 0.055), (0.86, 0.63, 0.04),
    (0.44, 0.42, 0.065), (0.65, 0.6, 0.05), (0.25, 0.86, 0.04), (0.8, 0.16, 0.06), (0.1, 0.5, 0.05),
    (0.38, 0.2, 0.045), (0.92, 0.4, 0.035), (0.58, 0.3, 0.05), (0.2, 0.68, 0.045),
]
QUARTER_POSTS = 16  # the quarterdeck balustrade's posts, then the forecastle's
FORE_POSTS = 14


def loss_order(count, seed):
    """The order `count` things are lost in, the same every run: each stage keeps the damage of the one before"""
    return tuple(int(i) for i in np.random.default_rng(seed).permutation(count))


# The balustrades' posts, the quarterdeck's then the forecastle's, in the order they are shot away
RAIL_LOSS_ORDER = loss_order(QUARTER_POSTS + FORE_POSTS, 3)
# The stern's windows going dark: the transom's two rows of six (0-11), then the quarter galleries' (12-19)
WINDOW_LOSS_ORDER = loss_order(20, 4)
LANTERN_LOSS_ORDER = (2, 1, 0)  # the taffrail's lanterns smashed: starboard, port, then the big middle one
FORE_BREAK_Z = DECK_Z + 5.4  # where the foremast snaps in stage 4
FORE_FALL_ANGLE = 96.0  # degrees from upright: the broken foremast lies forward over the forecastle and the bow
FORE_FALL_DIR = (1.0, 0.3)  # forward, a little to port, so the yards stay across the ship and the sails drape the bow
MAIN_BREAK_Z = MASTS["main"]["top_z"] + 1.4  # the main topmast snaps just above the top and goes overboard
WEAR_SEED = 5.3  # soot and char blotches stay in the same places from stage to stage, they only grow


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


SHIP_DIR = os.environ.get("SHIP_OUT") or base_dir()  # this ship's folder: ships/european/frigate
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


PH_URL = "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/{asset}/{asset}_{kind}_1k.jpg"


def polyhaven(asset, kind):
    """kind: diff / nor_gl / rough. Downloaded from Poly Haven (CC0) the first time a ship asks for it"""
    path = os.path.join(PH_DIR, f"{asset}_{kind}_1k.jpg")
    if not os.path.exists(path):
        os.makedirs(PH_DIR, exist_ok=True)
        request = urllib.request.Request(PH_URL.format(asset=asset, kind=kind), headers={"User-Agent": "blender-assets"})
        with urllib.request.urlopen(request, timeout=60) as response, open(path, "wb") as out:
            out.write(response.read())
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

    for amount, color, scale, softness, strength in ((soot, "soot", 0.28, 0.16, 0.9), (char, "char", 0.5, 0.1, 0.8)):
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
            mul = nodes.new("ShaderNodeMix")
            mul.data_type = "RGBA"
            mul.blend_type = "MULTIPLY"
            mul.inputs[0].default_value = 1.0
            mul.inputs[6].default_value = linear(tint)
            links.new(grain.outputs["Result"], mul.inputs[7])
            color_out = mul.outputs[2]
        else:
            mul = nodes.new("ShaderNodeMix")
            mul.data_type = "RGBA"
            mul.blend_type = "MULTIPLY"
            mul.inputs[0].default_value = 1.0
            mul.inputs[6].default_value = linear(tint)
            links.new(color_out, mul.inputs[7])
            color_out = mul.outputs[2]
    color_out = add_wear(nt, color_out, *wear)
    links.new(color_out, bsdf.inputs["Base Color"])

    rough = nodes.new("ShaderNodeTexImage")
    rough.image = polyhaven(asset, "rough")
    if rough_add:
        add = nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        add.use_clamp = True
        add.inputs[1].default_value = rough_add
        links.new(rough.outputs["Color"], add.inputs[0])
        links.new(add.outputs["Value"], bsdf.inputs["Roughness"])
    else:
        links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    nor = nodes.new("ShaderNodeTexImage")
    nor.image = polyhaven(asset, "nor_gl")
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


def cloth(name, image):
    """Sail canvas: some sunlight shines through it, and a fine bump keeps it from looking like plastic"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    out = nodes.get("Material Output")
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.95
    bsdf.inputs["Specular IOR Level"].default_value = 0.15
    bsdf.inputs["Sheen Weight"].default_value = 0.3
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 1.6
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
    holes = nodes.new("ShaderNodeMixShader")
    clear = nodes.new("ShaderNodeBsdfTransparent")
    links.new(tex.outputs["Alpha"], holes.inputs["Fac"])
    links.new(clear.outputs["BSDF"], holes.inputs[1])
    links.new(mix.outputs["Shader"], holes.inputs[2])
    links.new(holes.outputs["Shader"], out.inputs["Surface"])
    m.diffuse_color = linear(COLORS["sail"])
    m.use_backface_culling = False
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


def box(bm, center, size, axes=None):
    """A box centred at `center` with `size` along `axes` (three vectors)"""
    if axes is None:
        axes = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    rot = Matrix((axes[0], axes[1], axes[2])).transposed().to_4x4()
    m = Matrix.Translation(Vector(center)) @ rot @ Matrix.Diagonal((size[0], size[1], size[2], 1.0))
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)


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


def grid_surface(bm, point_at, cols, rows):
    """A cols x rows grid; point_at(u, v) -> Vector, u, v in 0..1. UV = (u, v). Collapsed corners are welded"""
    uv = bm.loops.layers.uv.active
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
                loop[uv].uv = c
    bmesh.ops.remove_doubles(bm, verts=[v for row in verts for v in row], dist=1e-5)



# ---------------------------------------------------------------------------
# Hull shape
# ---------------------------------------------------------------------------


def x_bow(z):
    """The stem leans forward and curves up into the beakhead"""
    return 24.5 + 0.55 * z - 0.011 * z * z


def x_stern(z):
    """The transom rakes aft as it rises"""
    return -24.0 - 0.2 * z


def section(z):
    """Width of the cross-section at height z (0..1): round bilge, and the sides fall in above the wale (tumblehome)"""
    widest = 4.6
    if z <= widest:
        t = (widest - z) / (widest - KEEL_Z)
        return max(0.0, 1 - t * t) ** 0.5
    return 1 - 0.0036 * (z - widest) ** 2


def plan(x, z):
    """Half-width at height z depending on x: a full bow, a long straight run and a narrower stern"""
    xs, xb = x_stern(z), x_bow(z)
    if x >= xb:
        return 0.0
    if x > 6:
        # A fine entry: the bow narrows to a sharp stem rather than a round one
        t = (x - 6) / (xb - 6)
        return BEAM * max(0.0, 1 - t * t) ** 0.85
    if x < -10:
        t = min(1.0, (-10 - x) / (-10 - xs))
        return BEAM * (1 - 0.3 * t**1.6)
    return BEAM


def half_width(x, z):
    return plan(x, z) * section(z)


def rail_z(x):
    """Top of the side: the waist's bulwark, stepping up at the quarterdeck and the forecastle"""
    return (
        DECK_Z
        + 1.65
        + (QUARTER_Z - DECK_Z) * smoothstep(QUARTER_FRONT + 1.2, QUARTER_FRONT - 1.6, x)
        + 0.7 * smoothstep(-20.5, -25.5, x)
        + (FORE_Z - DECK_Z) * smoothstep(FORE_BACK - 1.2, FORE_BACK + 1.6, x)
        + 0.6 * smoothstep(22.5, 27.5, x)
    )


# ---------------------------------------------------------------------------
# Sails
# ---------------------------------------------------------------------------


def sail_texture(name, size=1024, seed=5, crest=False, stage=None, holes=()):
    """Canvas: vertical cloths of slightly different tone, stitched seams, doubled edges and a reef band, weave and
    weathering towards the foot. crest: the royal crest painted on it, a blue shield with a gilt border and crown.
    stage: a DAMAGE_STAGES entry, holes: which of SAIL_HOLES this sail gets (in the order they come); holes, a tear and
    a burnt foot are cut out through alpha"""
    rng = np.random.default_rng(seed)
    n = (np.arange(size) + 0.5) / size
    xs = n[None, :]
    ys = 1 - n[:, None]  # 0 = foot, 1 = head
    base = np.array(srgb(COLORS["sail"]))

    shade = np.ones((size, size))
    panels = 9
    cloth_ = np.clip((xs * panels).astype(int), 0, panels - 1)
    shade *= (1 + 0.03 * (rng.random(panels) - 0.5))[cloth_]
    shade *= 1 - 0.02 * (np.sin(np.arange(size)[None, :] * 2.2) ** 2)
    shade *= 1 - 0.015 * (np.sin(np.arange(size)[:, None] * 2.0) ** 2)
    shade *= 1 + 0.02 * (rng.random((size, size)) - 0.5)
    shade *= 1 - 0.05 * value_noise(size, 5, rng)
    shade *= 1 - 0.08 * np.clip(1 - ys / 0.3, 0, 1) ** 1.6 * (0.5 + value_noise(size, 12, rng))

    pos = (xs * panels) % 1
    overlap = (pos < 0.025) | (pos > 0.995)
    shade = np.where(overlap, shade * 0.95, shade)
    stitch = (np.abs(pos - 0.005) < 0.0018) | (np.abs(pos - 0.022) < 0.0018)
    dash = (np.arange(size)[:, None] % 6) < 4
    shade = np.where(stitch & dash, shade * 0.87, shade)
    band = np.abs(ys - 0.82) < 0.012
    shade = np.where(band, shade * 0.95, shade)
    points = (np.abs(ys - 0.82) < 0.022) & (np.abs(((xs * 18) % 1) - 0.5) < 0.035)
    shade = np.where(points, shade * 0.8, shade)
    edge = np.minimum(np.minimum(xs, 1 - xs), np.minimum(ys, 1 - ys))
    shade = np.where(edge < 0.03, shade * 0.95, shade)
    shade = np.where(edge < 0.007, shade * 0.76, shade)
    rgb = base[None, None, :] * shade[..., None]

    if crest:
        rgb = paint_crest(rgb, xs, ys, shade)
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
    ragged = value_noise(size, 40, rng)

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
        # A bottom corner is ripped away
        d = (1 - xs) + ys * 0.9
        edge = 0.18 + 0.05 * (ragged - 0.5) + 0.02 * np.sin(ys * 60)
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


def paint_crest(rgb, xs, ys, shade):
    """A heater shield in the middle of the sail: royal blue, a gilt border, a gilt cross, and a crown over it.
    The paint takes the canvas's shading, so the seams and weathering show through"""
    cx, cy, w, h = 0.5, 0.47, 0.17, 0.25
    u = (xs - cx) / w  # -1..1 across the shield
    v = (ys - cy) / h  # -1 (point) .. 1 (top)
    # The shield: straight top half, the lower half narrowing to a point along a circular arc
    half = np.where(v > 0, 1.0, np.sqrt(np.clip(1 - (v * 1.0) ** 2, 0, 1)) * (1 + 0.15 * v))
    inside = (np.abs(u) <= half) & (v >= -1) & (v <= 1)
    border = inside & ((np.abs(u) > half - 0.12) | (v > 0.9) | (v < -0.88))
    cross = inside & ((np.abs(u) < 0.13) | (np.abs(v - 0.15) < 0.11))
    blue = np.array(srgb(COLORS["crest_blue"]))
    gold = np.array(srgb(COLORS["crest_gold"]))
    tone = shade[..., None]
    rgb = np.where(inside[..., None], blue[None, None, :] * tone, rgb)
    rgb = np.where((cross & ~border)[..., None], gold[None, None, :] * tone, rgb)
    rgb = np.where(border[..., None], gold[None, None, :] * tone * 0.92, rgb)
    # Crown: a band with three points and a ball on each, above the shield
    cu = (xs - cx) / (w * 0.75)
    cv = (ys - (cy + h * 1.08)) / (h * 0.32)
    band = (np.abs(cu) < 1) & (cv > 0) & (cv < 0.45)
    teeth = np.zeros_like(band)
    balls = np.zeros_like(band)
    for bu in (-0.75, 0.0, 0.75):
        # A point narrowing from the band up to its tip, and a ball on the tip
        teeth |= (cv >= 0.45) & (cv < 1.25) & (np.abs(cu - bu) < 0.3 * (1.25 - cv) / 0.8)
        balls |= ((cu - bu) ** 2 * 6 + (cv - 1.35) ** 2 * 4) < 0.09
    crown = band | teeth | balls
    rgb = np.where(crown[..., None], gold[None, None, :] * tone, rgb)
    return rgb


# Which of SAIL_HOLES each sail's texture gets, in order: every sail is shot through in its own places
SAIL_HOLE_PICKS = {
    "sail": (0, 5, 3, 8, 11, 1, 9, 6, 13, 2, 10, 4, 12, 7),
    "topsail": (6, 1, 12, 4, 9, 0, 13, 3, 7, 10, 2, 11, 5, 8),
    "crest_sail": (1, 9, 4, 12, 0, 7, 11, 3, 13, 6, 2, 10, 8, 5),
}


def sails(stage, index):
    """The three sail textures for a stage: the fore course, the headsails and the spanker; the topsails and the
    topgallants; and the main course with the crest. A stage with holes or fire gets its own images, so the intact
    ones stay as they are"""
    damaged = stage["sail_holes"] > 0 or stage["sail_burn"] > 0 or stage["sail_tear"]
    suffix = f"_d{index}" if damaged else ""
    hurt = stage if damaged else None
    return {
        "sail": cloth("FrigateSail", sail_texture("frigate_sail" + suffix, stage=hurt, holes=SAIL_HOLE_PICKS["sail"])),
        "topsail": cloth(
            "FrigateTopsail",
            sail_texture("frigate_topsail" + suffix, seed=9, stage=hurt, holes=SAIL_HOLE_PICKS["topsail"]),
        ),
        "crest_sail": cloth(
            "FrigateCrestSail",
            sail_texture(
                "frigate_sail_crest" + suffix, seed=7, crest=True, stage=hurt, holes=SAIL_HOLE_PICKS["crest_sail"]
            ),
        ),
    }


def make_materials(stage, index):
    wear = (stage["soot"], stage["char"])
    light_wear = (stage["soot"] * 0.6, stage["char"] * 0.5)
    return sails(stage, index) | {
        # Dark varnished planks for the hull, light planks for the decks
        "hull": scanned("FrigateHull", "dark_wooden_planks", hue=0.485, saturation=1.45, value=0.95, wear=wear),
        "deck": scanned("FrigateDeck", "wood_planks", saturation=0.9, value=1.2, wear=wear),
        "weathered": scanned("FrigateWeathered", "weathered_brown_planks", value=0.6, wear=wear),
        "royal": scanned("FrigateRoyal", "weathered_brown_planks", tint=COLORS["royal"], normal=0.5, wear=wear),
        "gold_paint": scanned("FrigateGilt", "wood_planks", tint=COLORS["gold_paint"], normal=0.4, wear=wear),
        "lid": scanned("FrigateLid", "wood_planks", tint=COLORS["lid"], normal=0.4, wear=wear),
        "spar": scanned("FrigateSpar", "wood_planks", saturation=0.9, value=0.7, wear=light_wear),
        "iron": scanned("FrigateIron", "rusty_metal_02", tint=COLORS["iron"], paint=False, value=1.7, metal=0.5),
        "brass": plain("FrigateBrass", COLORS["brass"], rough=0.32, metal=1.0),
        "rope": plain("FrigateRope", COLORS["rope"], rough=1.0),
        "port": plain("FrigateGunport", COLORS["port"], rough=1.0),
        "glass": plain("FrigateGlass", COLORS["glass"], rough=0.3, emission=1.5),
        "lantern": plain("FrigateLantern", COLORS["glass"], rough=0.3, emission=5.0),
        "pennant_blue": plain("FrigatePennantBlue", COLORS["flag_blue"], rough=0.9, two_sided=True),
        "pennant_white": plain("FrigatePennantWhite", COLORS["flag_white"], rough=0.9, two_sided=True),
        "grate": plain("FrigateGrate", COLORS["grate"], rough=1.0),
        "boat": scanned("FrigateBoat", "wood_planks", saturation=0.9, value=1.0, wear=wear),
        "burnt": plain("FrigateBurnt", COLORS["burnt"], rough=1.0),
    }


# ---------------------------------------------------------------------------
# Hull
# ---------------------------------------------------------------------------

HULL_ROWS = [-2.8, -2.5, -1.8, -1.0, 0.0, 0.8, 1.6, 2.4, 3.3, 3.6, 4.5, 5.4, 5.7, 6.4, 7.05, 7.35, 8.2, 9.05]
TOP_ROWS = 5
HULL_COLS = 90
# Bands painted on the hull, by height: weathered below the waterline, varnish up to a gilt wale, the lower battery's
# strake royal blue up to a gilt moulding, varnish, another gilt moulding and the main battery's strake royal blue up to
# the rail in the waist (higher at the bow and stern: varnish again)
WEATHERED_TOP = 0.8
GOLD = ((3.3, 3.6), (5.4, 5.7), (7.05, 7.35))
ROYAL = ((3.6, 5.4), (7.35, 9.1))


def build_hull(mats, coll):
    bm = bmesh.new()
    uv = bm.loops.layers.uv.verify()
    us = [0.5 - 0.5 * math.cos(math.pi * i / HULL_COLS) for i in range(HULL_COLS + 1)]
    base_z = HULL_ROWS[-1]

    def x_at(u, z):
        return x_stern(z) + u * (x_bow(z) - x_stern(z))

    columns = []
    for u in us:
        top = rail_z(x_at(u, base_z))
        zs = HULL_ROWS + [base_z + (top - base_z) * k / TOP_ROWS for k in range(1, TOP_ROWS + 1)]
        columns.append([(x_at(u, z), z) for z in zs])

    shared = {}

    def vert(c, r, side):
        x, z = columns[c][r]
        w = half_width(x, z)
        if w < 1e-4:
            key = (c, r)
            if key not in shared:
                shared[key] = bm.verts.new((x, 0.0, z))
            return shared[key]
        return bm.verts.new((x, side * w, z))

    rows = len(columns[0])
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
        if zc < WEATHERED_TOP:
            f.material_index = 2
        elif any(lo <= zc <= hi for lo, hi in GOLD):
            f.material_index = 1
        elif any(lo < zc < hi for lo, hi in ROYAL):
            f.material_index = 3
        else:
            f.material_index = 0
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
    # Slots: 0 wood, 1 gilt, 2 weathered, 3 royal blue; the inside of the bulwark +10, the rail cap +20
    for i in range(24):
        if i < 4:
            obj.data.materials.append([mats["hull"], mats["gold_paint"], mats["weathered"], mats["royal"]][i])
        elif 10 <= i <= 13:
            obj.data.materials.append(mats["deck"])
        elif 20 <= i <= 23:
            obj.data.materials.append(mats["gold_paint"])
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
    remap = {0: 0, 1: 1, 2: 2, 3: 3, 10: 4, 11: 4, 12: 4, 13: 4, 20: 1, 21: 1, 22: 1, 23: 1}
    indices = [remap.get(p.material_index, 0) for p in baked.polygons]
    baked.materials.clear()
    for m in (mats["hull"], mats["gold_paint"], mats["weathered"], mats["royal"], mats["deck"]):
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


def bulkhead(parts, x, z0, z1, key="hull_wood"):
    """A wall across the ship at x from z0 up to z1, as wide as the hull there"""
    steps = 6
    zs = [z0 + (z1 - z0) * i / steps for i in range(steps + 1)]
    left = [(x, inner_width(x, z), z) for z in zs]
    right = [(x, -y, z) for _, y, z in reversed(left)]
    polygon(parts[key], left + right)


def balustrade(parts, x, z, w, posts, lost=(), facing=1):
    """A gilt rail on turned posts across the ship at x, from -w to w. lost: the posts shot away (a stump is left);
    with four or more gone the rail snaps, one half drooping to the deck on the side it faces (facing: +1 bow)"""
    for i in range(posts + 1):
        y = -w + 2 * w * i / posts
        if i in lost:
            rod(parts["spar"], (x, y, z), (x + 0.05 * facing, y, z + 0.25), 0.07, segs=6)
            continue
        lathe(parts["spar"], [(0.08, 0), (0.12, 0.25), (0.07, 0.5), (0.11, 0.75), (0.08, 0.95)], 6, Matrix.Translation((x, y, z)))
    top = z + 1.0
    if len(lost) < 4:
        box(parts["gold_paint"], (x, 0, top), (0.2, 2 * w + 0.2, 0.14))
    else:
        rod(parts["gold_paint"], (x, -w - 0.1, top), (x, -0.5, top), 0.08, segs=6)
        rod(parts["gold_paint"], (x, w + 0.1, top), (x + 0.6 * facing, 0.7, z - 0.9), 0.08, segs=6)


def lost_posts(stage, first, count):
    """The posts of a balustrade (numbered from `first` in RAIL_LOSS_ORDER) shot away by this stage"""
    gone = RAIL_LOSS_ORDER[: stage["rail_lost"]]
    return {i - first for i in gone if first <= i < first + count}


def build_decks(parts, stage):
    deck = parts["deck"]
    polygon(deck, deck_outline(DECK_Z, x_stern(DECK_Z) + WALL, x_bow(DECK_Z)), flip=True)
    polygon(deck, deck_outline(QUARTER_Z, x_stern(QUARTER_Z) + WALL, QUARTER_FRONT, 18), flip=True)
    polygon(deck, deck_outline(FORE_Z, FORE_BACK, x_bow(FORE_Z), 18), flip=True)

    # The quarterdeck's front wall: the captain's cabin, with two doors and a gilt moulding
    bulkhead(parts, QUARTER_FRONT, DECK_Z, QUARTER_Z)
    w = inner_width(QUARTER_FRONT, QUARTER_Z)
    box(parts["gold_paint"], (QUARTER_FRONT + 0.07, 0, QUARTER_Z - 0.1), (0.24, 2 * w, 0.22))
    for y in (-2.9, 2.9):
        box(parts["gold_paint"], (QUARTER_FRONT + 0.06, y, DECK_Z + 1.2), (0.12, 1.6, 2.4))
        box(parts["port"], (QUARTER_FRONT + 0.11, y, DECK_Z + 1.15), (0.1, 1.2, 2.1))
        box(parts["brass"], (QUARTER_FRONT + 0.17, y - 0.4, DECK_Z + 1.1), (0.08, 0.12, 0.12))
    for y in (-1.0, 1.0, -5.0, 5.0):
        box(parts["gold_paint"], (QUARTER_FRONT + 0.07, y, DECK_Z + 1.9), (0.1, 1.0, 0.95))
        box(parts["glass"], (QUARTER_FRONT + 0.1, y, DECK_Z + 1.9), (0.1, 0.8, 0.75))
    # Gilt pilasters between the doors and windows
    for y in (-4.0, -1.9, 0.0, 1.9, 4.0):
        box(parts["gold_paint"], (QUARTER_FRONT + 0.08, y, (DECK_Z + QUARTER_Z) / 2), (0.14, 0.22, QUARTER_Z - DECK_Z))
    balustrade(parts, QUARTER_FRONT + 0.18, QUARTER_Z, w - 0.2, QUARTER_POSTS - 1, lost_posts(stage, 0, QUARTER_POSTS), 1)

    # The forecastle's back wall and its rail
    bulkhead(parts, FORE_BACK, DECK_Z, FORE_Z)
    w = inner_width(FORE_BACK, FORE_Z)
    box(parts["gold_paint"], (FORE_BACK - 0.07, 0, FORE_Z - 0.1), (0.24, 2 * w, 0.22))
    for y in (-2.2, 2.2):
        box(parts["gold_paint"], (FORE_BACK - 0.06, y, DECK_Z + 1.0), (0.12, 1.5, 2.0))
        box(parts["port"], (FORE_BACK - 0.1, y, DECK_Z + 0.95), (0.1, 1.1, 1.8))
    balustrade(parts, FORE_BACK - 0.18, FORE_Z, w - 0.2, FORE_POSTS - 1, lost_posts(stage, QUARTER_POSTS, FORE_POSTS), -1)

    # Ladders up to both raised decks
    for x0, x1, z1 in ((QUARTER_FRONT + 2.2, QUARTER_FRONT + 0.2, QUARTER_Z), (FORE_BACK - 2.0, FORE_BACK - 0.2, FORE_Z)):
        for y in (4.3, -4.3):
            a = Vector((x0, y, DECK_Z))
            b = Vector((x1, y, z1))
            for s in (-0.45, 0.45):
                rod(parts["spar"], a + Vector((0, s, 0)), b + Vector((0, s, 0)), 0.07, segs=6)
            for i in range(1, 6):
                box(parts["deck"], a.lerp(b, i / 6), (0.22, 0.85, 0.07))


# The ports with lids, as (row, port along the side, side), and the order damage shoots their lids off
LIDDED = [
    (r, k, side) for r, row in enumerate(GUN_ROWS) if row["lids"] for k in range(len(row["xs"])) for side in (1, -1)
]
LID_LOSS_ORDER = tuple(LIDDED[i] for i in loss_order(len(LIDDED), 5))


def build_cannons(parts, stage):
    """Every row of GUN_ROWS: a gilt frame round each port, the lid hinged up, red inside, and a cannon run out, on its
    carriage where the deck is open, its muzzle alone out of the lower battery. Damage shoots lids off: one hangs from
    a hinge, the next is gone"""
    lost = LID_LOSS_ORDER[: stage["lids_lost"]]
    for r, row in enumerate(GUN_ROWS):
        z, s = row["z"], row["scale"]
        for k, x in enumerate(row["xs"]):
            for side in (1, -1):
                inner = inner_width(x, z)
                p, n = hull_point(x, z, side)
                t, n, b = side_frame(n)
                box(parts["gold_paint"], p + n * 0.03, (1.15 * s, 0.12, 1.0 * s), (t, n, b))
                box(parts["port"], p + n * 0.08, (0.85 * s, 0.12, 0.72 * s), (t, n, b))
                # The lid, swung up above the port: its painted inside faces out
                if row["lids"] and (r, k, side) not in lost:
                    lid_at = p + n * 0.32 + b * 0.78
                    lid_up = (b + n * 0.9).normalized()
                    lid_n = lid_up.cross(t).normalized() * (1 if lid_up.cross(t).dot(n) > 0 else -1)
                    box(parts["lid"], lid_at, (0.95, 0.09, 0.8), (t, lid_n, lid_up))
                elif row["lids"] and lost.index((r, k, side)) % 2 == 0:
                    # Hanging by one hinge, twisted down the side
                    hang = (t * 0.5 - b).normalized()
                    box(parts["lid"], p + n * 0.15 + t * 0.3 - b * 0.55, (0.8, 0.09, 0.95), (hang.cross(n).normalized(), n, hang))

                if row["deck"] is None:
                    # The lower battery: only the muzzle shows, run out through the port
                    start = Vector((x, side * (inner - 0.3), z))
                else:
                    # Carriage and barrel on the deck, pointing out through the port
                    deck = row["deck"]
                    cy = side * (inner - 1.05 * s)
                    box(parts["hull_wood"], (x, cy, deck + 0.34 * s), (1.05 * s, 1.35 * s, 0.48 * s))
                    for dx in (-0.42 * s, 0.42 * s):
                        for dy in (-0.46 * s, 0.46 * s):
                            c = Vector((x + dx, cy + dy, deck + 0.21 * s))
                            rod(parts["iron"], c - Vector((0.08, 0, 0)), c + Vector((0.08, 0, 0)), 0.21 * s, segs=10)
                    start = Vector((x, cy - side * 0.75 * s, z))
                m = Matrix.Translation(start) @ basis(Vector((0, side, 0)))
                length = abs(p.y - start.y) + 0.65 * s
                lathe(
                    parts["iron"],
                    [(0.32 * s, 0), (0.35 * s, 0.12), (0.32 * s, 0.3), (0.25 * s, length - 0.2 * s), (0.3 * s, length - 0.12 * s), (0.3 * s, length), (0.17 * s, length + 0.01)],
                    12,
                    m,
                )


STERN_WINDOW_Y = (-3.75, -2.25, -0.75, 0.75, 2.25, 3.75)
STERN_ROWS = (5.6, 8.9)  # the wardroom's windows and the captain's cabin's over them
GALLERY_X = (-21.6, -19.9)


def build_stern(parts, stage):
    """The transom: two rows of gallery windows, the royal crest over them, gilt mouldings and pilasters; the rudder,
    the quarter galleries on the sides, two tiers each, and three lanterns on the taffrail. Damage darkens windows and
    smashes lanterns"""
    dark = set(WINDOW_LOSS_ORDER[: stage["windows_out"]])
    nx = Vector((-1, 0, -0.2)).normalized()
    up = Vector((-0.2, 0, 1)).normalized()
    side = Vector((0, 1, 0))
    for row, zc in enumerate(STERN_ROWS):
        for k, y in enumerate(STERN_WINDOW_Y):
            c = Vector((x_stern(zc), y, zc)) + nx * 0.03
            box(parts["gold_paint"], c, (1.25, 0.12, 1.55), (side, nx, up))
            box(parts["port" if row * 6 + k in dark else "glass"], c + nx * 0.05, (0.95, 0.12, 1.25), (side, nx, up))
            box(parts["gold_paint"], c + nx * 0.08, (0.08, 0.1, 1.25), (side, nx, up))  # the mullion
            box(parts["gold_paint"], c + nx * 0.08, (0.95, 0.1, 0.07), (side, nx, up))  # the transom bar
    # Mouldings across the stern, and pilasters between the windows
    for z in (4.1, 7.25, 10.45, 12.6):
        w = half_width(x_stern(z), z)
        box(parts["gold_paint"], Vector((x_stern(z), 0, z)) + nx * 0.06, (2 * w - 0.2, 0.16, 0.3), (side, nx, up))
    for zc in STERN_ROWS:
        for y in (-4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5):
            box(parts["gold_paint"], Vector((x_stern(zc), y, zc)) + nx * 0.07, (0.18, 0.12, 2.6), (side, nx, up))

    # The royal crest on the taffrail: a blue shield in a gilt frame under a crown, held by two gilt scrolls
    c = Vector((x_stern(11.6), 0, 11.6)) + nx * 0.1
    box(parts["gold_paint"], c, (2.8, 0.14, 2.3), (side, nx, up))
    box(parts["royal"], c + nx * 0.06, (2.3, 0.12, 1.85), (side, nx, up))
    box(parts["gold_paint"], c + nx * 0.1, (0.36, 0.1, 1.55), (side, nx, up))
    box(parts["gold_paint"], c + nx * 0.1 + up * 0.18, (1.7, 0.1, 0.34), (side, nx, up))
    crown = c + up * 1.5 + nx * 0.05
    box(parts["brass"], crown, (1.6, 0.18, 0.42), (side, nx, up))
    for dy in (-0.68, 0.0, 0.68):
        lathe(parts["brass"], [(0.14, 0), (0.1, 0.36), (0.16, 0.5), (0.02, 0.66)], 6, Matrix.Translation(crown + side * dy + up * 0.18))
    for s in (-1, 1):
        m = Matrix.Translation(c + side * s * 2.0 + nx * 0.05) @ basis(Vector((0, -s * 0.6, 1)))
        lathe(parts["brass"], [(0.12, -1.0), (0.32, -0.6), (0.24, 0.0), (0.34, 0.5), (0.1, 1.0)], 8, m)
    # Gilt figures at the corners of the transom, from the lower moulding up to the taffrail
    for s in (-1, 1):
        z = 8.0
        y = s * (half_width(x_stern(z), z) - 0.3)
        m = Matrix.Translation(Vector((x_stern(z), y, z)) + nx * 0.12) @ basis(Vector((0, 0, 1)))
        lathe(parts["brass"], [(0.18, -3.6), (0.36, -3.1), (0.24, -2.0), (0.34, -0.8), (0.22, 0.6), (0.38, 1.8), (0.3, 3.2), (0.1, 4.4)], 10, m)

    # Quarter galleries: a bay of windows on each side of the stern, two tiers, a gilt cupola over them
    for i, s in enumerate((1, -1)):
        for tier, zc in enumerate(STERN_ROWS):
            for j, x in enumerate(GALLERY_X):
                p, n = hull_point(x, zc, s)
                t, n, b = side_frame(n)
                box(parts["gold_paint"], p + n * 0.2, (1.3, 0.4, 1.7), (t, n, b))
                lit = 12 + i * 4 + tier * 2 + j not in dark
                box(parts["glass" if lit else "port"], p + n * 0.42, (1.0, 0.06, 1.3), (t, n, b))
            p, n = hull_point(sum(GALLERY_X) / 2, zc - 1.25, s)
            box(parts["hull_wood"], p + n * 0.25, (4.0, 0.55, 0.4))
            p, n = hull_point(sum(GALLERY_X) / 2, zc + 1.2, s)
            box(parts["gold_paint"], p + n * 0.25, (4.0, 0.6, 0.3))
        # A low gilt dome over the galleries and a drop under them, flattened against the side
        for z, profile in (
            (STERN_ROWS[-1] + 1.35, [(1.0, 0), (0.8, 0.35), (0.4, 0.7), (0.05, 1.0)]),
            (STERN_ROWS[0] - 1.45, [(0.05, -1.1), (0.3, -0.7), (0.75, -0.3), (0.95, 0.0)]),
        ):
            p, n = hull_point(sum(GALLERY_X) / 2, z, s)
            m = Matrix.Translation(p + n * 0.2) @ Matrix.Diagonal((1.6, 0.45, 1.0, 1.0))
            lathe(parts["brass"], profile, 10, m)

    # Rudder
    top = STERN_ROWS[0] - 1.6  # the rudder head goes into the counter under the stern windows
    pts = []
    for z, back in ((-2.6, 2.3), (0.0, 2.2), (2.4, 1.6), (top, 0.7)):
        xs = x_stern(z)
        pts.append((xs - 0.05, z, xs - 0.05 - back))
    prof = [(xa, z) for xa, z, xb in pts] + [(xb, z) for xa, z, xb in reversed(pts)]
    bm = parts["weathered_part"]
    th = 0.44
    front = [bm.verts.new((x, -th / 2, z)) for x, z in prof]
    back = [bm.verts.new((x, th / 2, z)) for x, z in prof]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    k = len(prof)
    for i in range(k):
        j = (i + 1) % k
        bm.faces.new((front[j], front[i], back[i], back[j]))
    for z in (0.3, 2.0, 3.6):
        xs = x_stern(z)
        box(parts["brass"], (xs - 0.6, 0, z), (1.2, th + 0.08, 0.18))

    # Three lanterns on the taffrail, the middle one the biggest; a smashed one hangs dark and crooked
    out = set(LANTERN_LOSS_ORDER[: stage["lanterns_out"]])
    for k, (y, s) in enumerate(((0.0, 1.6), (-3.4, 1.15), (3.4, 1.15))):
        base = Vector((x_stern(13.0) + 0.7, y, rail_z(-26) + 0.1))
        post = Vector((0.5, 0.35 * (1 if y >= 0 else -1), 1.25)) * s if k in out else Vector((0, 0, 1.4 * s))
        rod(parts["spar"], base, base + post, 0.1, segs=6)
        m = Matrix.Translation(base + post) @ (basis(post) if k in out else Matrix.Identity(4)) @ Matrix.Diagonal((s, s, s, 1))
        lathe(parts["port" if k in out else "lantern"], [(0.26, 0), (0.36, 0.34), (0.33, 0.85), (0.18, 0.96)], 6, m)
        lathe(parts["brass"], [(0.3, 0.9), (0.44, 0.98), (0.05, 1.35)], 6, m)


def harpoon_launcher(parts, at, aim):
    """A harpoon launcher on a turned post: the game's harpoon slots"""
    lathe(parts["hull_wood"], [(0.55, 0), (0.45, 0.6), (0.3, 0.9)], 8, Matrix.Translation(at))
    aim = aim.normalized()
    across = Vector((0, 0, 1)).cross(aim).normalized()
    mount = at + Vector((0, 0, 1.05))
    rod(parts["iron"], mount - aim * 1.0, mount + aim * 1.6, 0.13, 0.1, segs=8)
    for s in (1, -1):
        bow_end = mount + aim * 0.9 + across * (s * 1.2) + Vector((0, 0, -0.2))
        rod(parts["spar"], mount + aim * 0.9, bow_end, 0.08, 0.05, segs=6)
        rod(parts["rope"], bow_end, mount - aim * 0.5, 0.03, segs=4, caps=False)
    rod(parts["brass"], mount + aim * 1.6, mount + aim * 2.3, 0.05, 0.0, segs=6)


def build_deck_details(parts, stage):
    # Gratings over the hatches in the waist
    for x, sx, sy in ((-5.0, 2.4, 2.4), (9.0, 2.4, 2.4), (-9.6, 1.8, 1.8)):
        box(parts["grate"], (x, 0, DECK_Z + 0.18), (sx, sy, 0.36))
        for dx in (-1, 1):
            box(parts["hull_wood"], (x + dx * sx / 2, 0, DECK_Z + 0.22), (0.18, sy + 0.18, 0.44))
        for dy in (-1, 1):
            box(parts["hull_wood"], (x, dy * sy / 2, DECK_Z + 0.22), (sx + 0.18, 0.18, 0.44))

    # Two boats, keel up, side by side on the booms over the waist between the masts
    for bx in (2.6, 6.6):
        for y in (-3.2, 3.2):
            rod(parts["spar"], (bx, y, DECK_Z), (bx, y, DECK_Z + 1.3), 0.12, segs=6)
        rod(parts["spar"], (bx, -3.6, DECK_Z + 1.3), (bx, 3.6, DECK_Z + 1.3), 0.14, segs=6, uv_along=SPAR_TILE)
    for y in (-1.5, 1.5):
        boat(parts, 4.6, y, DECK_Z + 1.45)

    # Capstan between the main and the mizzen
    cx = -7.6
    m = Matrix.Translation((cx, 0, DECK_Z + 0.36))
    lathe(parts["hull_wood"], [(0.8, 0), (0.62, 0.3), (0.5, 1.0), (0.7, 1.15), (0.56, 1.4)], 10, m)
    for a in angles(8):
        d = Vector((math.cos(a), math.sin(a), 0))
        c = Vector((cx, 0, DECK_Z + 1.45))
        rod(parts["spar"], c, c + d * 1.8, 0.06, segs=5)

    # Barrels by the mainmast, crates on the forecastle and the quarterdeck
    barrels = ((-2.4, 2.4, 0.5, 1.1), (-3.2, 3.2, 0.45, 1.0), (-2.6, -2.5, 0.5, 1.1), (-3.4, -3.3, 0.42, 0.95))
    for bx, by, r, h in barrels:
        barrel(parts, bx, by, DECK_Z, r, h)
    crates = (
        (16.2, 3.4, FORE_Z, 1.0, 0.2), (16.0, -3.5, FORE_Z, 1.0, -0.15), (16.1, 3.4, FORE_Z + 1.0, 0.8, 0.5),
        (-13.9, 4.6, QUARTER_Z, 0.9, 0.1), (-13.8, -4.6, QUARTER_Z, 1.0, -0.2), (-13.9, 4.6, QUARTER_Z + 0.9, 0.7, 0.4),
    )
    for args in crates[: stage["crates"]]:
        crate(parts, *args)

    # Coils of rope by the masts
    for x, y, z in ((MASTS["fore"]["x"] - 1.4, 1.8, DECK_Z), (MASTS["main"]["x"] + 1.5, -1.9, DECK_Z), (MASTS["mizzen"]["x"] + 1.4, 1.8, QUARTER_Z)):
        m = Matrix.Translation((x, y, z))
        for k in range(3):
            r = 0.6 - k * 0.13
            lathe(parts["rope"], [(r, 0.02 + k * 0.1), (r + 0.1, 0.06 + k * 0.1), (r, 0.12 + k * 0.1)], 14, m, False, False)

    # The helm on the quarterdeck: a double wheel on gilt pedestals
    hx = -19.2
    for wx in (hx - 0.6, hx + 0.6):
        box(parts["gold_paint"], (wx, 0, QUARTER_Z + 0.7), (0.4, 0.5, 1.4))
        c = Vector((wx, 0, QUARTER_Z + 1.75))
        pts = [c + Vector((0, math.cos(a), math.sin(a))) * 1.0 for a in angles(16)]
        for i in range(16):
            rod(parts["spar"], pts[i], pts[(i + 1) % 16], 0.07, segs=5, caps=False)
        for a in angles(8):
            rod(parts["spar"], c, c + Vector((0, math.cos(a), math.sin(a))) * 1.3, 0.05, segs=5)
        lathe(parts["brass"], [(0.17, -0.1), (0.17, 0.12)], 8, Matrix.Translation(c) @ basis(Vector((1, 0, 0))))
    rod(parts["brass"], (hx - 0.6, 0, QUARTER_Z + 1.75), (hx + 0.6, 0, QUARTER_Z + 1.75), 0.08, segs=6)

    # The ship's bell on the forecastle, in a gilt belfry
    bx = FORE_BACK + 1.2
    for y in (-0.75, 0.75):
        rod(parts["gold_paint"], (bx, y, FORE_Z), (bx, y, FORE_Z + 1.9), 0.08, segs=6)
    rod(parts["gold_paint"], (bx, -0.85, FORE_Z + 1.9), (bx, 0.85, FORE_Z + 1.9), 0.09, segs=6)
    lathe(parts["gold_paint"], [(0.9, 0), (0.5, 0.5), (0.05, 0.8)], 8, Matrix.Translation((bx, 0, FORE_Z + 1.95)))
    m = Matrix.Translation((bx, 0, FORE_Z + 1.85))
    lathe(parts["brass"], [(0.05, 0), (0.2, -0.17), (0.27, -0.55), (0.38, -0.8)], 10, m, cap_bottom=False)

    # Harpoon launchers: one on the forecastle aiming ahead, two at the front of the quarterdeck aiming out
    harpoon_launcher(parts, Vector((22.6, 0, FORE_Z)), Vector((1, 0, 0.18)))
    for s in (1, -1):
        harpoon_launcher(parts, Vector((-14.0, s * 2.6, QUARTER_Z)), Vector((0.2, s, 0.18)))

    # Anchors at the bows, hanging from the catheads
    for s in (1, -1):
        p, n = hull_point(20.5, FORE_Z - 0.6, s)
        o = n * 0.4
        top = p + o + Vector((0, 0, 0.7))
        bottom = p + o + Vector((-0.4, 0, -3.8))
        rod(parts["iron"], top, bottom, 0.15, segs=6)
        rod(parts["spar"], top + Vector((-1.1, 0, 0)), top + Vector((1.1, 0, 0)), 0.15, segs=6)
        for dx in (-1.35, 1.35):
            tip = bottom + Vector((dx, 0, 1.25))
            rod(parts["iron"], bottom, tip, 0.13, segs=6)
            box(parts["iron"], tip, (0.6, 0.16, 0.5))
        # The cathead itself, a beam out over the side
        rod(parts["hull_wood"], p + Vector((0, 0, 0.9)) - n * 0.6, p + n * 1.2 + Vector((0, 0, 1.1)), 0.24, segs=6)

    build_head(parts)


# The head: a knee of the head standing out from the stem, from an iron ram at the waterline up to the figurehead
HEAD = ((-0.6, 2.4), (0.6, 3.6), (2.0, 3.9), (3.5, 3.6), (5.0, 3.5), (6.4, 4.0), (7.6, 4.8))  # (height, reach past the stem)
HEAD_THICK = 0.56


def head_point(z):
    """The front edge of the knee of the head at height z"""
    for (z0, r0), (z1, r1) in zip(HEAD, HEAD[1:]):
        if z <= z1:
            t = max(0.0, (z - z0) / (z1 - z0))
            return Vector((x_bow(z) + r0 + (r1 - r0) * t, 0, z))
    return Vector((x_bow(HEAD[-1][0]) + HEAD[-1][1], 0, HEAD[-1][0]))


def build_head(parts):
    """The bow made to look for a fight: a knee of the head standing out from the stem like a blade, painted royal
    blue and gilt along its edge, an iron ram at its foot on the waterline, and a gilt figurehead at its top, crowned,
    with swept-back wings; head rails from the catheads down to it"""
    bm = parts["royal"]
    front = [head_point(z) for z, _ in HEAD]
    top_z = HEAD[-1][0] + 0.6
    back = [Vector((x_bow(z) - 0.4, 0, z)) for z in (top_z, 6.0, 4.0, 2.0, 0.4, HEAD[0][0])]
    outline = front + [front[-1] + Vector((-0.8, 0, 0.6))] + back
    half = HEAD_THICK / 2
    near = [bm.verts.new(p + Vector((0, half, 0))) for p in outline]
    far = [bm.verts.new(p - Vector((0, half, 0))) for p in outline]
    bm.faces.new(near)
    bm.faces.new(list(reversed(far)))
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        bm.faces.new((near[j], near[i], far[i], far[j]))
    # Gilt along the front edge
    for a, b in zip(front, front[1:]):
        rod(parts["gold_paint"], a + Vector((0.08, 0, 0)), b + Vector((0.08, 0, 0)), 0.2, segs=6)

    # The ram: an iron spike just over the waterline, pointing ahead from the knee's foot, with two gilt collars
    base = head_point(0.9)
    aim = Vector((1, 0, 0.05)).normalized()
    m = Matrix.Translation(base - aim * 1.0) @ basis(aim)
    lathe(parts["iron"], [(0.8, 0), (0.9, 0.8), (0.75, 2.2), (0.45, 3.6), (0.05, 4.8)], 12, m)
    for at in (0.45, 1.5):
        lathe(parts["brass"], [(0.94, at - 0.15), (0.99, at), (0.92, at + 0.15)], 12, m, False, False)

    # The figurehead: a gilt beast leaning out over the ram, its chest forward, a crown on its head and wings swept
    # back along the head rails
    tip = head_point(HEAD[-1][0])
    lean = Vector((1, 0, 0.75)).normalized()
    m = Matrix.Translation(tip + Vector((-0.4, 0, -0.2))) @ basis(lean)
    lathe(parts["brass"], [(0.3, -0.4), (0.85, 0.2), (0.95, 1.0), (0.75, 1.8), (0.5, 2.4), (0.62, 2.8), (0.35, 3.3), (0.08, 3.6)], 12, m)
    crown = tip + lean * 3.1 + Vector((-0.4, 0, 0.1))
    lathe(parts["brass"], [(0.42, 0), (0.5, 0.35), (0.24, 0.6), (0.05, 0.9)], 8, Matrix.Translation(crown))
    for s in (1, -1):
        root = tip + lean * 1.4 + Vector((-0.4, s * 0.5, 0))
        for k, (back, rise, width) in enumerate(((2.8, 1.3, 0.5), (2.4, 0.4, 0.42), (1.9, -0.4, 0.34))):
            end = root + Vector((-back, s * (1.2 + 0.25 * k), rise))
            rod(parts["brass"], root, end, width, 0.05, segs=5)

    # Head rails: from the catheads sweeping down and forward to the figurehead, two a side
    for s in (1, -1):
        for start_z, end, r in ((FORE_Z - 0.4, tip + Vector((-0.6, s * 0.35, 0.6)), 0.13), (FORE_Z - 2.0, tip + Vector((-1.6, s * 0.3, -1.2)), 0.11)):
            p, n = hull_point(x_bow(start_z) - 3.0, start_z, s)
            a = p + n * 0.1
            mid = a.lerp(end, 0.5) + Vector((0, s * 0.5, -0.6))
            rod(parts["gold_paint"], a, mid, r, segs=6)
            rod(parts["gold_paint"], mid, end, r, segs=6)


def boat(parts, x, y, z):
    """A rowing boat, keel up: a lathed half-shell squashed into a boat's lines"""
    length, beam, depth = 6.2, 1.25, 0.9
    bm = parts["boat_part"]
    segs, rings = 12, 14
    verts = []
    for i in range(rings + 1):
        u = i / rings
        along = (u - 0.5) * length
        w = beam * math.sin(math.pi * u) ** 0.55
        ring = []
        for j in range(segs + 1):
            a = math.pi * j / segs  # half circle: the hull's skin from gunwale to gunwale over the keel
            ring.append(bm.verts.new((x + along, y + w * math.cos(a), z + depth * math.sin(a) * math.sin(math.pi * u) ** 0.3)))
        verts.append(ring)
    for i in range(rings):
        for j in range(segs):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))


def barrel(parts, x, y, z, r, h):
    m = Matrix.Translation((x, y, z))
    prof = [(r * 0.86, 0), (r, h * 0.3), (r * 1.05, h * 0.5), (r, h * 0.7), (r * 0.86, h)]
    lathe(parts["spar"], prof, 12, m, uv_along=SPAR_TILE)
    for zz in (0.15, h - 0.15):
        rr = r * 0.92 + 0.03
        lathe(parts["iron"], [(rr, zz - 0.05), (rr, zz + 0.05)], 12, m, False, False)


def crate(parts, x, y, z, s, rot):
    axes = (Vector((math.cos(rot), math.sin(rot), 0)), Vector((-math.sin(rot), math.cos(rot), 0)), Vector((0, 0, 1)))
    box(parts["deck"], (x, y, z + s / 2), (s, s, s), axes)
    for k in (-1, 1):
        c = Vector((x, y, z + s / 2)) + axes[0] * (k * s * 0.42)
        box(parts["hull_wood"], c, (0.12, s + 0.03, s + 0.03), axes)


# ---------------------------------------------------------------------------
# Masts, sails, rigging
# ---------------------------------------------------------------------------


def braced(mast_x, along, across, z):
    """A point in a sail's frame (along = forward, across = to port), with the yard turned by BRACE"""
    c, s = math.cos(BRACE), math.sin(BRACE)
    x0 = mast_x + 0.5
    return Vector((x0 + along * c - across * s, along * s + across * c, z))


def splinters(parts, x, z, r):
    """Broken wood sticking up round the top of a snapped spar of radius r at height z"""
    for a in angles(5):
        d = Vector((math.cos(a), math.sin(a), 0))
        foot = Vector((x, 0, z - 0.2)) + d * r * 0.7
        rod(parts["spar"], foot, foot + d * 0.15 + Vector((0, 0, 0.5 + 0.3 * math.sin(3 * a))), 0.07, 0.01, segs=4)


def build_mast(parts, upper, name, stage):
    """A mast in three pieces (the lower mast up to the top, the topmast up to the cross-trees, the topgallant mast up
    to the truck), its square sails between their yards and a pennant at the masthead. upper: where the foremast's part
    above FORE_BREAK_Z goes. In stage 4 it is a separate set of parts that build() topples over the bow, and the main
    topmast is gone overboard; otherwise `upper` is `parts` itself"""
    spec = MASTS[name]
    mx, top, top_z, cross_z = spec["x"], spec["top"], spec["top_z"], spec["cross_z"]
    mt = Matrix.Translation((mx, 0, 0))
    big = name != "mizzen"
    r0 = 0.64 if big else 0.5
    fore_down = stage["mast_broken"] and name == "fore"
    topmast_lost = stage["mast_broken"] and name == "main"
    up = upper if fore_down else parts
    # Lower mast, and above the top the topmast and the topgallant mast, each thinner
    if fore_down:
        rb = r0 - 0.1 * (FORE_BREAK_Z - DECK_Z) / (top_z + 0.6 - DECK_Z)
        lathe(parts["spar"], [(r0, DECK_Z - 0.5), (r0 - 0.03, DECK_Z), (rb, FORE_BREAK_Z - 0.3), (rb * 0.6, FORE_BREAK_Z + 0.2), (0.05, FORE_BREAK_Z + 0.5)], 12, mt, uv_along=SPAR_TILE)
        splinters(parts, mx, FORE_BREAK_Z, rb)
        lathe(up["spar"], [(rb, FORE_BREAK_Z + 0.4), (r0 - 0.12, top_z + 0.6), (r0 - 0.25, top_z + 0.6)], 12, mt, uv_along=SPAR_TILE)
    else:
        lathe(parts["spar"], [(r0, DECK_Z - 0.5), (r0 - 0.03, DECK_Z), (r0 - 0.12, top_z + 0.6), (r0 - 0.25, top_z + 0.6)], 12, mt, uv_along=SPAR_TILE)
    r1 = r0 * 0.62
    if topmast_lost:
        lathe(parts["spar"], [(r1, top_z - 1.2), (r1 - 0.03, top_z + 0.6), (r1 - 0.05, MAIN_BREAK_Z - 0.3), (r1 * 0.5, MAIN_BREAK_Z + 0.2), (0.04, MAIN_BREAK_Z + 0.5)], 10, mt, uv_along=SPAR_TILE)
        splinters(parts, mx, MAIN_BREAK_Z, r1 - 0.05)
    else:
        lathe(up["spar"], [(r1, top_z - 1.2), (r1 - 0.04, cross_z + 0.6), (r1 * 0.55, cross_z + 0.6)], 10, mt, uv_along=SPAR_TILE)
        lathe(up["spar"], [(r1 * 0.62, cross_z - 1.0), (r1 * 0.5, top), (r1 * 0.62, top + 0.15), (0.05, top + 0.4)], 8, mt, uv_along=SPAR_TILE)
    for z in (DECK_Z + 1.4, DECK_Z + 6.5, top_z - 3.0):
        if z > top_z - 1.5 or (name == "mizzen" and z < QUARTER_Z + 0.5):
            continue
        lathe((up if fore_down and z > FORE_BREAK_Z else parts)["iron"], [(r0 - 0.04, z - 0.08), (r0 - 0.04, z + 0.08)], 12, mt, False, False)

    # The top: a half-round platform with a gilt rim, and the cross-trees higher up
    R = 2.5 if big else 1.9
    lathe(up["deck"], [(0.3, top_z - 0.2), (R, top_z - 0.2), (R, top_z + 0.12), (0.3, top_z + 0.12)], 18, mt)
    lathe(up["gold_paint"], [(R - 0.05, top_z + 0.12), (R + 0.06, top_z + 0.12), (R + 0.06, top_z + 0.32), (R - 0.05, top_z + 0.32)], 18, mt, False, False)
    for a in angles(8):
        d = Vector((math.cos(a), math.sin(a), 0))
        rod(up["spar"], Vector((mx, 0, top_z - 2.2)) + d * 0.45, Vector((mx, 0, top_z - 0.2)) + d * (R - 0.3), 0.07, segs=5)
    if not topmast_lost:
        rod(up["spar"], (mx, -1.6, cross_z), (mx, 1.6, cross_z), 0.11, segs=6)
        rod(up["spar"], (mx - 0.6, -1.2, cross_z), (mx - 0.6, 1.2, cross_z), 0.09, segs=6)

    # The square sails, each between its yards: the main's course with the crest, a course or a topsail elsewhere
    for k, (lo, hi, half_lo, half_hi) in enumerate(spec["sails"]):
        if topmast_lost and k >= 1:
            continue
        level = k if big else k + 1  # the mizzen's first square sail is a topsail: the spanker is under it
        belly = SAIL_BELLY * (1.0, 0.8, 0.62)[level]
        key = ("crest_sail" if name == "main" else "sail") if level == 0 else "topsail"

        def point(u, v, lo=lo, hi=hi, half_lo=half_lo, half_hi=half_hi, belly=belly):
            s = u * 2 - 1
            hw = half_lo + (half_hi - half_lo) * v
            fv = math.sin(math.pi * v) ** 0.8 * 0.85 + 0.15 * (1 - v)
            along = belly * (1 - s * s) ** 0.8 * fv
            along += SAIL_CREASE * math.sin(s * math.pi * 5.5 + v * 1.3) * v**1.5 * (1 - s * s)
            z = lo + (hi - lo) * v
            return braced(mx, along, -s * hw, z)

        grid_surface(up[key], point, 28, 18)
        for z, hw, r in ((hi + 0.25, half_hi + 0.9, 0.24 - 0.04 * level), (lo - 0.2, half_lo + 0.6, 0.22 - 0.04 * level)):
            mid = braced(mx, 0, 0, z)
            for end in (braced(mx, 0, hw, z), braced(mx, 0, -hw, z)):
                rod(up["spar"], mid, end, r, r * 0.5, segs=8, uv_along=SPAR_TILE)

    # A long pennant streaming from the masthead: blue on the main, white on the fore and the mizzen; damage shreds
    # it, fire burns it
    if topmast_lost:
        return
    pole_top = top + 2.8
    rod(up["spar"], (mx, 0, top), (mx, 0, pole_top), 0.08, segs=6)
    key, length, left = {
        "main": ("pennant_blue", 9.5, stage["pennants"][0]),
        "fore": ("pennant_white", 6.5, stage["pennants"][1]),
        "mizzen": ("pennant_white", 5.0, stage["pennants"][2]),
    }[name]
    if left > 0:
        length *= left

        def pennant(u, v, length=length):
            half = 0.6 * (1 - u) + 0.08
            fork = 0.35 * max(0.0, u - 0.8) / 0.2  # a swallowtail at the end
            z = pole_top - 0.6 + (v * 2 - 1) * half * (1 - fork * (1 - abs(v * 2 - 1)))
            return Vector((mx - 0.1 - length * u, 0.55 * math.sin(u * 4.0) * u, z))

        grid_surface(up[key], pennant, 14, 2)


def spanker_corners():
    """The spanker's corners: tack and throat on the mizzen, clew at the boom's end, peak at the gaff's, swung a little
    to starboard like the headsails"""
    mx = MASTS["mizzen"]["x"]
    sp = SPANKER
    swing = Vector((-math.cos(0.18), -math.sin(0.18), 0))
    tack = Vector((mx - 0.7, 0, sp["foot"]))
    throat = Vector((mx - 0.7, 0, sp["head"]))
    clew = tack + swing * sp["boom"] + Vector((0, 0, 0.3))
    peak = throat + swing * sp["gaff"] + Vector((0, 0, sp["peak"]))
    return tack, throat, clew, peak


def build_spanker(parts, stage):
    """The mizzen's spanker: a fore-and-aft sail on a boom and a gaff"""
    tack, throat, clew, peak = spanker_corners()

    def point(u, v):
        foot = tack.lerp(clew, u)
        head = throat.lerp(peak, u)
        return foot.lerp(head, v) + Vector((0, -1.1, 0)) * math.sin(math.pi * u) ** 0.9 * math.sin(math.pi * v) ** 0.8

    grid_surface(parts["sail"], point, 16, 14)
    rod(parts["spar"], tack, clew + (clew - tack).normalized() * 0.9, 0.22, 0.15, segs=8, uv_along=SPAR_TILE)
    rod(parts["spar"], throat, peak + (peak - throat).normalized() * 0.5, 0.18, 0.12, segs=8, uv_along=SPAR_TILE)
    # The vang from the peak down to the quarter, and the sheet from the boom's end
    rod(parts["rope"], peak, Vector((x_stern(12) + 0.4, -3.0, rail_z(-25))), 0.04, segs=4, caps=False)
    rod(parts["rope"], clew, Vector((x_stern(12) + 0.6, -0.4, rail_z(-25.5))), 0.05, segs=4, caps=False)


def mast_point(name, z):
    return Vector((MASTS[name]["x"], 0, z))


# Every rope damage can part, as (kind, mast, side, which), in the order they are shot away
ROPES = [
    (kind, name, side, k)
    for name in MASTS
    for side in (1, -1)
    for kind, count in (("brace", len(MASTS[name]["sails"])), ("backstay", 1), ("topshroud", 2))
    for k in range(count)
]
ROPE_LOSS_ORDER = tuple(ROPES[i] for i in loss_order(len(ROPES), 6))
SHROUDS = {"fore": (-0.4, -1.5, -2.6, -3.7), "main": (-0.4, -1.5, -2.6, -3.7), "mizzen": (-0.4, -1.4, -2.4)}


def build_rigging(parts, stage):
    """Bowsprit, stays, two headsails, shrouds, backstays and braces. In stage 4 the foremast's rigging went down with
    it and the main's topmast took its own; damage parts ropes before that (ROPE_LOSS_ORDER)"""
    rope = parts["rope"]
    fore_down = stage["mast_broken"]
    topmast_lost = stage["mast_broken"]
    skipped = set(ROPE_LOSS_ORDER[: stage["ropes_lost"]])
    # Bowsprit and jib-boom
    root = Vector((x_bow(FORE_Z) - 3.2, 0, FORE_Z + 0.5))
    rod(parts["spar"], root, BOWSPRIT_TIP.lerp(root, 0.36), 0.52, 0.36, segs=10, uv_along=SPAR_TILE)
    rod(parts["spar"], BOWSPRIT_TIP.lerp(root, 0.48), BOWSPRIT_TIP, 0.28, 0.15, segs=8, uv_along=SPAR_TILE)
    rod(rope, BOWSPRIT_TIP.lerp(root, 0.34), head_point(3.0) - Vector((0.3, 0, 0)), 0.07, segs=4, caps=False)  # bobstay
    rod(rope, BOWSPRIT_TIP, head_point(5.0) - Vector((0.3, 0, 0)), 0.05, segs=4, caps=False)  # martingale
    for s in (1, -1):
        p, n = hull_point(x_bow(FORE_Z) - 4.0, FORE_Z - 0.4, s)
        rod(rope, BOWSPRIT_TIP.lerp(root, 0.4), p + n * 0.2, 0.05, segs=4, caps=False)  # bowsprit shrouds

    fore, main, mizzen = MASTS["fore"], MASTS["main"], MASTS["mizzen"]
    # Stays: from each mast forward and down
    if not fore_down:
        rod(rope, mast_point("fore", fore["top"] - 0.5), BOWSPRIT_TIP, 0.06, segs=4, caps=False)
        rod(rope, mast_point("fore", fore["cross_z"] + 0.3), BOWSPRIT_TIP.lerp(root, 0.3), 0.065, segs=4, caps=False)
        rod(rope, mast_point("fore", fore["top_z"] + 0.6), BOWSPRIT_TIP.lerp(root, 0.62), 0.08, segs=4, caps=False)
    if not topmast_lost:
        rod(rope, mast_point("main", main["top"] - 0.5), mast_point("fore", fore["cross_z"] + 0.5), 0.06, segs=4, caps=False)
        rod(rope, mast_point("main", main["cross_z"] + 0.3), mast_point("fore", fore["top_z"] + 0.8), 0.065, segs=4, caps=False)
    rod(rope, mast_point("main", main["top_z"] + 0.6), Vector((FORE_BACK + 0.6, 0, FORE_Z + 0.4)), 0.08, segs=4, caps=False)
    rod(rope, mast_point("mizzen", mizzen["cross_z"] + 0.3), mast_point("main", main["top_z"] + 1.0), 0.055, segs=4, caps=False)
    rod(rope, mast_point("mizzen", mizzen["top_z"] + 0.6), mast_point("main", DECK_Z + 4.0), 0.065, segs=4, caps=False)

    if not fore_down:
        # The headsails: triangles from the fore stays down to the bowsprit, bellying out to leeward
        for stay_top, stay_foot, lo, hi, clew, belly in (
            (fore["top"] - 0.5, BOWSPRIT_TIP, 0.36, 0.95, Vector((x_bow(FORE_Z) + 3.8, -1.4, FORE_Z + 5.4)), 0.8),
            (fore["cross_z"] + 0.3, BOWSPRIT_TIP.lerp(root, 0.3), 0.3, 0.93, Vector((x_bow(FORE_Z) + 0.6, -1.8, FORE_Z + 4.2)), 0.9),
        ):
            top_point = mast_point("fore", stay_top)
            head = top_point.lerp(stay_foot, lo)
            tack = top_point.lerp(stay_foot, hi)

            def jib(u, v, head=head, tack=tack, clew=clew, belly=belly):
                # Along the stay (u), out to the clew (v): the cloth bellies out to leeward between them
                edge = head.lerp(tack, u)
                bulge = Vector((0, -belly, 0)) * math.sin(math.pi * u) * math.sin(math.pi * v)
                return edge.lerp(clew, v) + bulge

            grid_surface(parts["sail"], jib, 10, 6)

    for name, spec in MASTS.items():
        mx, top_z, cross_z = spec["x"], spec["top_z"], spec["cross_z"]
        gone = fore_down and name == "fore"
        top_gone = gone or (topmast_lost and name == "main")
        R = 2.5 if name != "mizzen" else 1.9
        for side in (1, -1):
            for dx in SHROUDS[name]:
                x = mx + dx
                p, n = hull_point(x, rail_z(x) - 0.4, side)
                if not gone:
                    # Shrouds from the top down to the channels on the side, slightly aft of the mast
                    rod(rope, Vector((mx, side * 0.4, top_z - 0.3)), p + n * 0.45, 0.055, segs=4, caps=False)
                box(parts["iron"], p + n * 0.4, (0.2, 0.14, 0.6))
            if not gone:
                # Ratlines across the shrouds, a few of them, so they read as a ladder
                first, last = SHROUDS[name][0], SHROUDS[name][-1]
                pa, na = hull_point(mx + first, rail_z(mx + first) - 0.4, side)
                pb, nb = hull_point(mx + last, rail_z(mx + last) - 0.4, side)
                a0, b0 = pa + na * 0.45, pb + nb * 0.45
                a1 = Vector((mx, side * 0.4, top_z - 0.3))
                for t in (0.15, 0.3, 0.45, 0.6, 0.75):
                    rod(rope, a0.lerp(a1, t), b0.lerp(a1, t), 0.03, segs=3, caps=False)
            if not top_gone:
                # Topmast shrouds from the cross-trees to the rim of the top
                for j, dx in enumerate((-0.4, -1.3)):
                    if ("topshroud", name, side, j) in skipped:
                        continue
                    rod(rope, Vector((mx, side * 0.3, cross_z)), Vector((mx + dx, side * (R - 0.1), top_z)), 0.045, segs=4, caps=False)
                # A backstay from the masthead down to the side aft
                if ("backstay", name, side, 0) not in skipped:
                    x = mx - 10.0
                    p, n = hull_point(x, rail_z(x) - 0.3, side)
                    rod(rope, Vector((mx, side * 0.25, spec["top"] - 1.0)), p + n * 0.35, 0.05, segs=4, caps=False)
            # Braces from the yard ends aft to the rail
            for k, (lo, hi, half_lo, half_hi) in enumerate(spec["sails"]):
                if gone or (top_gone and k >= 1) or ("brace", name, side, k) in skipped:
                    continue
                end = braced(mx, 0, side * (half_hi + 0.9), hi + 0.25)
                x = max(mx - 6.5, -23.0)
                p, n = hull_point(x, rail_z(x), side)
                rod(rope, end, p, 0.045, segs=4, caps=False)
        # The channels: boards along the side that spread the shrouds
        for side in (1, -1):
            dxs = SHROUDS[name]
            x = mx + (dxs[0] + dxs[-1]) / 2
            p, n = hull_point(x, rail_z(x) - 0.5, side)
            t, n2, b = side_frame(n)
            box(parts["hull_wood"], p + n2 * 0.4, (abs(dxs[-1] - dxs[0]) + 1.4, 0.8, 0.18), (t, n2, b))


def build_damage(parts, stage, rng):
    """Shot holes in the hull with scorched rims and splintered planks round them, and wreckage floating alongside"""
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
        face = polygon(parts["port"], rim)
        face.normal_update()
        if face.normal.dot(n) < 0:
            face.normal_flip()
        # Scorched wood round the hole, a little behind it
        scorch = [center - n * 0.02 + (q - center) * (1.5 + 0.2 * rng.random()) for q in rim]
        face = polygon(parts["burnt"], scorch)
        face.normal_update()
        if face.normal.dot(n) < 0:
            face.normal_flip()
        # Splinters: broken plank ends sticking out of the rim
        for _ in range(5):
            a = rng.random() * 2 * math.pi
            d = t * math.cos(a) + b * math.sin(a)
            root = center + d * r * 0.85
            tip = root + d * r * (0.5 + 0.5 * rng.random()) + n * (0.15 + 0.25 * rng.random())
            rod(parts["hull_wood"], root, tip, 0.08, 0.02, segs=4)

    for i in range(stage["debris"]):
        a = rng.random() * 2 * math.pi
        dist = 15 + 8 * rng.random()
        c = Vector((math.cos(a) * dist * 1.5, math.sin(a) * dist, 0.06))
        rot = rng.random() * math.pi
        axes = (Vector((math.cos(rot), math.sin(rot), 0)), Vector((-math.sin(rot), math.cos(rot), 0)), Vector((0, 0, 1)))
        if i % 3 == 2:
            barrel(parts, c.x, c.y, -0.5, 0.5, 1.1)  # half sunk
        elif i % 4 == 1:
            crate(parts, c.x, c.y, -0.45, 1.0, rot)
        else:
            # Light deck planks: the dark hull's would read as black specks on the water
            box(parts["deck"], c, (2.8 + rng.random() * 1.4, 0.45, 0.16), axes)


def topple(upper, parts):
    """Swings the foremast's broken top over the bow round the break, then merges it into `parts`"""
    pivot = Vector((MASTS["fore"]["x"], 0, FORE_BREAK_Z))
    fall = Vector((FORE_FALL_DIR[0], FORE_FALL_DIR[1], 0)).normalized()
    axis = Vector((0, 0, 1)).cross(fall)
    m = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(FORE_FALL_ANGLE), 4, axis) @ Matrix.Translation(-pivot)
    for key, bm in upper.meshes.items():
        bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
        tmp = bpy.data.meshes.new("toppled")
        bm.to_mesh(tmp)
        bm.free()
        parts[key].from_mesh(tmp)
        bpy.data.meshes.remove(tmp)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

OBJECT_NAMES = {
    "deck": "Decks",
    "hull_wood": "Woodwork",
    "weathered_part": "Rudder",
    "gold_paint": "Gilt",
    "royal": "RoyalPaint",
    "lid": "PortLids",
    "port": "Gunports",
    "iron": "Iron",
    "brass": "Brass",
    "glass": "Windows",
    "lantern": "Lanterns",
    "spar": "Spars",
    "rope": "Rigging",
    "sail": "Sails",
    "topsail": "Topsails",
    "crest_sail": "CrestSail",
    "burnt": "Scorch",
    "pennant_blue": "PennantBlue",
    "pennant_white": "PennantWhite",
    "grate": "Hatches",
    "boat_part": "Boat",
}
PART_MATERIAL = {"hull_wood": "hull", "weathered_part": "weathered", "boat_part": "boat"}
# Parts whose UVs come from box projection, with the tile size that sets the plank width
BOX_UV_TILE = {
    "deck": DECK_TILE,
    "hull_wood": HULL_TILE,
    "weathered_part": HULL_TILE,
    "gold_paint": HULL_TILE,
    "royal": HULL_TILE,
    "lid": 3.0,
    "spar": SPAR_TILE,
    "iron": 3.0,
    "boat_part": 3.0,
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


def build(damage=None):
    """damage: stage (see DAMAGE_STAGES); by default the scene's "damage" custom property, or 0"""
    if damage is None:
        damage = int(bpy.context.scene.get("damage", 0))
    damage = damage if damage in DAMAGE_STAGES else 0
    stage = DAMAGE_STAGES[damage]
    bpy.context.scene["damage"] = damage
    clear_previous()
    coll = bpy.data.collections.new("Ship")
    bpy.context.scene.collection.children.link(coll)

    mats = make_materials(stage, damage)
    # render_sprites.py turns the object named "Ship"; everything else is parented to it
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 10
    coll.objects.link(root)

    hull = build_hull(mats, coll)
    hull.parent = root

    parts = Parts()
    upper = Parts() if stage["mast_broken"] else parts
    build_decks(parts, stage)
    build_cannons(parts, stage)
    build_stern(parts, stage)
    build_deck_details(parts, stage)
    for name in MASTS:
        build_mast(parts, upper, name, stage)
    build_spanker(parts, stage)
    build_rigging(parts, stage)
    build_damage(parts, stage, np.random.default_rng(11))
    if upper is not parts:
        topple(upper, parts)

    for key, bm in parts.meshes.items():
        bm.normal_update()
        if key in BOX_UV_TILE:
            box_project_uvs(bm, BOX_UV_TILE[key])
        mesh = bpy.data.meshes.new(OBJECT_NAMES[key])
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(mats[PART_MATERIAL.get(key, key)])
        obj = bpy.data.objects.new(OBJECT_NAMES[key], mesh)
        coll.objects.link(obj)
        obj.parent = root

    # A badly damaged ship sits lower in the water and lists to port
    if stage["list_deg"] or stage["sink"]:
        tilt = Matrix.Translation((0, 0, -stage["sink"])) @ Matrix.Rotation(-math.radians(stage["list_deg"]), 4, "X")
        for obj in coll.objects:
            if obj.type == "MESH":
                obj.data.transform(tilt)
    return root


if __name__ == "__main__":
    build()

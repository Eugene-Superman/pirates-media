"""
Starter Sloop (line "starter", game class "sloop"), built from code: the ship every player starts on.

Run in Blender: open sloop.blend next to this file, Scripting tab -> Open -> build.py -> Run Script.
It rebuilds the "Ship" collection of the open file, so render_sprites.py works on it unchanged.

Damage: build(damage) with damage 0..4 builds one of the stages of the game's health scale
(src/game/ships/damage.ts): 0 intact, 1 minor, 2 heavy, 3 burning, 4 wrecked and sinking.
The fire, the smoke and the sinking itself are animated by the game on top of these sprites.
render_stages.py (in the blender-assets root) renders all five atlases in one go.

Axes and scale match the game: 1 Blender unit = 1 game unit, the bow points to +X, port side to +Y, Z up,
waterline at Z = 0. Hull 31 units long, collision radius 9 in the game.

Textures: scanned CC0 wood and metal from Poly Haven (polyhaven.com), shared by all ships in
blender-assets/textures/polyhaven/; the sail is generated into textures/ next to this file.
They are linked by relative paths, not packed.
"""

import math
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------
# Dimensions (game units)
# ---------------------------------------------------------------------------

KEEL_Z = -1.6
DECK_Z = 4.2  # main deck
STERN_DECK_Z = 6.3  # raised deck at the stern with the helm
STERN_FRONT = -8.6  # front wall of the stern deck
BEAM = 5.6  # largest half-width of the hull
WALL = 0.28  # hull wall thickness

MAST_X = 1.5
MAST_TOP = DECK_Z + 26.5
NEST_Z = MAST_TOP - 3.4  # crow's nest floor
SAIL_BOTTOM = 9.6
SAIL_TOP = 24.2
SAIL_HALF_BOTTOM = 9.4
SAIL_HALF_TOP = 8.6
SAIL_BELLY = 3.0  # how far the sail bulges forward
SAIL_CREASE = 0.22  # depth of the creases under the yard
BRACE = 0.4  # radians: the yard is turned a little so the sail reads from the side too

CANNONS_X = (-2.2,)  # one cannon per side at each x

# Real-world size of one texture tile, in game units: sets the plank width on the model
HULL_TILE = 9.0
PLANK_STRETCH = 2.2  # hull planks are long boards, so the tile is stretched along the hull
DECK_TILE = 5.2
SPAR_TILE = 5.2

# Paint and trim colors (sRGB)
COLORS = {
    "teal": 0x2F8F8B,
    "gold_paint": 0xE2AE45,
    "brass": 0xD6A24A,
    "iron": 0x34343A,
    "sail": 0xE3CE9F,  # warm unbleached canvas
    "rope": 0x8E6B44,
    "port": 0x20150E,
    "glass": 0xFFCF73,
    "pennant_red": 0xD8402E,
    "pennant_yellow": 0xF1B53B,
    "grate": 0x3A2717,
    "soot": 0x1E1712,
    "char": 0x1A130E,
    "burnt": 0x2B1E15,
}

# What each damage stage does to the model. Holes, posts and debris are taken from the lists below
# in order, so every stage keeps the damage of the previous one and adds to it
# prettier-ignore
DAMAGE_STAGES = {
    0: dict(soot=0.0, char=0.0, hull_holes=0, sail_holes=0, sail_tear=False, sail_burn=0.0, rail_lost=0,
            lantern_out=False, windows_out=0, pennants=(1.0, 1.0), crates=3, ropes_lost=0, mast_broken=False,
            list_deg=0.0, sink=0.0, debris=0),
    1: dict(soot=0.3, char=0.0, hull_holes=1, sail_holes=3, sail_tear=False, sail_burn=0.0, rail_lost=2,
            lantern_out=False, windows_out=0, pennants=(0.8, 0.85), crates=3, ropes_lost=0, mast_broken=False,
            list_deg=0.0, sink=0.0, debris=0),
    2: dict(soot=0.5, char=0.0, hull_holes=3, sail_holes=6, sail_tear=True, sail_burn=0.0, rail_lost=4,
            lantern_out=True, windows_out=1, pennants=(0.5, 0.6), crates=2, ropes_lost=1, mast_broken=False,
            list_deg=1.5, sink=0.15, debris=0),
    3: dict(soot=0.65, char=0.3, hull_holes=5, sail_holes=8, sail_tear=True, sail_burn=0.36, rail_lost=6,
            lantern_out=True, windows_out=2, pennants=(0.0, 0.4), crates=2, ropes_lost=3, mast_broken=False,
            list_deg=3.0, sink=0.3, debris=2),
    4: dict(soot=0.75, char=0.45, hull_holes=7, sail_holes=10, sail_tear=True, sail_burn=0.5, rail_lost=8,
            lantern_out=True, windows_out=2, pennants=(0.0, 0.0), crates=1, ropes_lost=99, mast_broken=True,
            list_deg=8.0, sink=0.7, debris=7),
}
# Holes in the hull: x, height, side (+1 port, -1 starboard), radius
# (a sprite shows about 2.8 pixels per unit, so anything much smaller than a unit is lost)
HULL_HOLES = [
    (-3.0, 2.0, -1, 0.8), (5.5, 1.8, 1, 0.9), (-10.0, 3.1, 1, 0.7), (8.5, 2.9, -1, 0.85),
    (0.5, 1.4, 1, 1.0), (-6.5, 1.3, -1, 1.2), (11.0, 1.8, 1, 1.0),
]
# Holes in the sail, in its texture: u across, v up, radius
SAIL_HOLES = [
    (0.3, 0.58, 0.05), (0.72, 0.33, 0.045), (0.55, 0.82, 0.035), (0.16, 0.25, 0.055), (0.86, 0.63, 0.04),
    (0.44, 0.42, 0.065), (0.65, 0.6, 0.05), (0.25, 0.86, 0.04), (0.8, 0.16, 0.06), (0.1, 0.5, 0.05),
]
RAIL_LOSS_ORDER = (2, 6, 4, 0, 7, 1, 5, 3)  # which posts of the stern-deck rail break first
MAST_BREAK_Z = DECK_Z + 3.4  # where the mast snaps in stage 4
MAST_FALL_ANGLE = 97.0  # degrees from upright: the broken top lies along the foredeck, resting on the bow
# Falling forward keeps the yard across the ship, so the sail ends up draped over the bow rather than sticking up
MAST_FALL_DIR = (1.0, 0.25)  # forward, a little to port
WEAR_SEED = 3.7  # soot and char blotches stay in the same places from stage to stage, they only grow


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


SHIP_DIR = os.environ.get("SHIP_OUT") or base_dir()  # this ship's folder: ships/starter/sloop
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


# ---------------------------------------------------------------------------
# Hull shape
# ---------------------------------------------------------------------------


def x_bow(z):
    """The stem leans forward: the higher, the further the bow"""
    return 14.0 + 0.55 * z - 0.02 * z * z


def x_stern(z):
    """The transom overhangs a little"""
    return -13.6 - 0.18 * z


def section(z):
    """Width of the cross-section at height z (0..1): round bottom, sides lean in at the top"""
    widest = 3.0
    if z <= widest:
        t = (widest - z) / (widest - KEEL_Z)
        return max(0.0, 1 - t * t) ** 0.5
    return 1 - 0.006 * (z - widest) ** 2


def plan(x, z):
    """Half-width at height z depending on x: full round bow, narrower stern"""
    xs, xb = x_stern(z), x_bow(z)
    if x >= xb:
        return 0.0
    if x > 2:
        t = (x - 2) / (xb - 2)
        return BEAM * max(0.0, 1 - t * t) ** 0.6
    if x < -5:
        t = min(1.0, (-5 - x) / (-5 - xs))
        return BEAM * (1 - 0.3 * t**1.5)
    return BEAM


def half_width(x, z):
    return plan(x, z) * section(z)


def rail_z(x):
    """Top of the side: raised at the stern deck, a little at the bow"""
    return (
        5.6
        + 2.4 * smoothstep(-6.5, -9.5, x)
        + 0.4 * smoothstep(-12, -15, x)
        + 1.0 * smoothstep(8, 12, x)
        + 0.4 * smoothstep(13, 17, x)
    )


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


def sail_texture(name="sloop_sail", size=1024, seed=5, stage=None):
    """Canvas: vertical cloths of slightly different tone, stitched seams, doubled edges (tabling),
    a reef band with reef points, weave and weathering that darkens towards the foot.
    stage: a DAMAGE_STAGES entry; holes, a tear and a burnt foot are cut out through alpha"""
    rng = np.random.default_rng(seed)
    n = (np.arange(size) + 0.5) / size
    xs = n[None, :]
    ys = 1 - n[:, None]  # 0 = foot, 1 = head
    base = np.array(srgb(COLORS["sail"]))

    shade = np.ones((size, size))
    # Each cloth was cut from a different bolt, so their tones differ a little
    panels = 7
    cloth = np.clip((xs * panels).astype(int), 0, panels - 1)
    shade *= (1 + 0.035 * (rng.random(panels) - 0.5))[cloth]
    # Weave: fine threads in both directions plus per-pixel grain
    shade *= 1 - 0.02 * (np.sin(np.arange(size)[None, :] * 2.2) ** 2)
    shade *= 1 - 0.015 * (np.sin(np.arange(size)[:, None] * 2.0) ** 2)
    shade *= 1 + 0.025 * (rng.random((size, size)) - 0.5)
    # Weathering: soft blotches, and grime that climbs from the foot
    shade *= 1 - 0.06 * value_noise(size, 5, rng)
    shade *= 1 - 0.1 * np.clip(1 - ys / 0.3, 0, 1) ** 1.6 * (0.5 + value_noise(size, 12, rng))

    # Seams between cloths: an overlap with a stitch line on both sides
    pos = (xs * panels) % 1
    overlap = (pos < 0.025) | (pos > 0.995)
    shade = np.where(overlap, shade * 0.95, shade)
    stitch = (np.abs(pos - 0.005) < 0.0018) | (np.abs(pos - 0.022) < 0.0018)
    dash = (np.arange(size)[:, None] % 6) < 4
    shade = np.where(stitch & dash, shade * 0.86, shade)

    # Reef band across the upper part, with short reef points
    band = np.abs(ys - 0.8) < 0.012
    shade = np.where(band, shade * 0.95, shade)
    points = (np.abs(ys - 0.8) < 0.022) & (np.abs(((xs * 16) % 1) - 0.5) < 0.035)
    shade = np.where(points, shade * 0.78, shade)

    # Tabling: the edges are doubled cloth, with a stitch line along the inner side and the bolt rope outside
    edge = np.minimum(np.minimum(xs, 1 - xs), np.minimum(ys, 1 - ys))
    shade = np.where(edge < 0.03, shade * 0.95, shade)
    edge_px = edge * size
    shade = np.where((np.abs(edge_px - 0.03 * size) < 1.0) & dash & dash.T, shade * 0.85, shade)
    shade = np.where(edge < 0.007, shade * 0.75, shade)

    rgb = base[None, None, :] * shade[..., None]
    alpha = np.ones((size, size))
    if stage is not None:
        rgb, alpha = damage_sail(rgb, alpha, xs, ys, stage, np.random.default_rng(seed + 1))
    rgba = np.concatenate([np.clip(rgb, 0, 1), alpha[..., None]], axis=2)
    return save_image(name, rgba)


def damage_sail(rgb, alpha, xs, ys, stage, rng):
    """Cuts holes with scorched rims, a torn corner and a burnt-away foot into the sail texture"""
    size = rgb.shape[0]
    soot = np.array(srgb(COLORS["soot"]))
    char = np.array(srgb(COLORS["char"]))
    scorch = np.zeros((size, size))  # 0 clean .. 1 charred black
    cut = np.zeros((size, size), dtype=bool)
    ragged = value_noise(size, 40, rng)

    for u, v, r in SAIL_HOLES[: stage["sail_holes"]]:
        dx, dy = xs - u, ys - v
        dist = np.sqrt(dx * dx + dy * dy)
        theta = np.arctan2(dy, dx)
        phase = rng.random() * 6.28
        edge = r * (1 + 0.28 * np.sin(5 * theta + phase) + 0.18 * np.sin(11 * theta + 2 * phase) + 0.25 * (ragged - 0.5))
        cut |= dist < edge
        scorch = np.maximum(scorch, np.clip(1 - (dist - edge) / (r * 0.9), 0, 1) ** 1.5)

    if stage["sail_tear"]:
        # The bottom corner on the starboard side is ripped away
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


def polyhaven(asset, kind):
    """kind: diff / nor_gl / rough"""
    path = os.path.join(PH_DIR, f"{asset}_{kind}_1k.jpg")
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


def make_materials(stage):
    wear = (stage["soot"], stage["char"])
    light_wear = (stage["soot"] * 0.6, stage["char"] * 0.5)
    damaged = stage["sail_holes"] > 0 or stage["sail_burn"] > 0
    sail_name = "sloop_sail" if not damaged else f"sloop_sail_d{stage_index(stage)}"
    return {
        # Warm varnished planks for the hull, lighter natural planks for the deck
        "hull": scanned("SloopHull", "wood_floor_deck", hue=0.53, saturation=0.8, value=1.15, wear=wear),
        "deck": scanned("SloopDeck", "wood_planks", saturation=0.95, value=1.25, wear=wear),
        "weathered": scanned("SloopWeathered", "weathered_brown_planks", value=0.8, wear=wear),
        "teal": scanned("SloopTeal", "weathered_brown_planks", tint=COLORS["teal"], normal=0.5, wear=wear),
        "gold_paint": scanned("SloopGoldPaint", "wood_planks", tint=COLORS["gold_paint"], normal=0.4, wear=wear),
        "spar": scanned("SloopSpar", "wood_planks", saturation=0.9, value=0.75, wear=light_wear),
        "iron": scanned("SloopIron", "rusty_metal_02", tint=COLORS["iron"], paint=False, value=1.7, metal=0.5),
        "brass": plain("SloopBrass", COLORS["brass"], rough=0.35, metal=1.0),
        "sail": cloth("SloopSail", sail_texture(sail_name, stage=stage if damaged else None)),
        "rope": plain("SloopRope", COLORS["rope"], rough=1.0),
        "port": plain("SloopGunport", COLORS["port"], rough=1.0),
        "glass": plain("SloopGlass", COLORS["glass"], rough=0.3, emission=1.5),
        "lantern": plain("SloopLantern", COLORS["glass"], rough=0.3, emission=5.0),
        "pennant_red": plain("SloopPennantRed", COLORS["pennant_red"], rough=0.9, two_sided=True),
        "pennant_yellow": plain("SloopPennantYellow", COLORS["pennant_yellow"], rough=0.9, two_sided=True),
        "grate": plain("SloopGrate", COLORS["grate"], rough=1.0),
        "burnt": plain("SloopBurnt", COLORS["burnt"], rough=1.0),
    }


def stage_index(stage):
    return next(k for k, v in DAMAGE_STAGES.items() if v is stage)


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
# Hull
# ---------------------------------------------------------------------------

HULL_ROWS = [-1.6, -1.35, -0.9, -0.3, 0.4, 1.2, 1.8, 2.4, 2.62, 3.5, 3.75, 4.6, 5.6]
TOP_ROWS = 4
HULL_COLS = 56
# Bands painted on the hull, by height
WEATHERED_TOP = 1.2
GOLD_LOW = (2.4, 2.62)
TEAL = (2.62, 3.5)
GOLD_HIGH = (3.5, 3.75)


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
        elif GOLD_LOW[0] <= zc <= GOLD_LOW[1] or GOLD_HIGH[0] <= zc <= GOLD_HIGH[1]:
            f.material_index = 1
        elif TEAL[0] < zc < TEAL[1]:
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

    # Transom: the flat back of the stern. Planks on it run across, so UVs use Y
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
    # Slots: 0 wood, 1 gold paint, 2 weathered, 3 teal; the inside of the bulwark +10, the rail cap +20
    for i in range(24):
        if i < 4:
            obj.data.materials.append([mats["hull"], mats["gold_paint"], mats["weathered"], mats["teal"]][i])
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
    # clear() resets the indices, so materials first, indices after
    baked.materials.clear()
    for m in (mats["hull"], mats["gold_paint"], mats["weathered"], mats["teal"], mats["deck"]):
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


def build_decks(parts, stage):
    deck = parts["deck"]
    polygon(deck, deck_outline(DECK_Z, x_stern(DECK_Z) + WALL, x_bow(DECK_Z)), flip=True)
    polygon(deck, deck_outline(STERN_DECK_Z, x_stern(STERN_DECK_Z) + WALL, STERN_FRONT, 16), flip=True)

    # Front wall of the stern deck with a door
    steps = 5
    zs = [DECK_Z + (STERN_DECK_Z - DECK_Z) * i / steps for i in range(steps + 1)]
    left = [(STERN_FRONT, inner_width(STERN_FRONT, z), z) for z in zs]
    right = [(STERN_FRONT, -y, z) for _, y, z in reversed(left)]
    polygon(parts["hull_wood"], left + right)
    w = inner_width(STERN_FRONT, STERN_DECK_Z)
    box(parts["gold_paint"], (STERN_FRONT + 0.06, 0, STERN_DECK_Z - 0.08), (0.22, 2 * w, 0.2))
    box(parts["gold_paint"], (STERN_FRONT + 0.05, 0, DECK_Z + 0.95), (0.12, 1.5, 1.9))
    box(parts["port"], (STERN_FRONT + 0.1, 0, DECK_Z + 0.9), (0.1, 1.1, 1.6))
    box(parts["brass"], (STERN_FRONT + 0.16, -0.38, DECK_Z + 0.9), (0.08, 0.12, 0.12))

    # Rail along the front edge of the stern deck. Damage knocks posts out and breaks the handrail
    w = inner_width(STERN_FRONT, STERN_DECK_Z) - 0.15
    n = 8
    lost = set(RAIL_LOSS_ORDER[: stage["rail_lost"]])
    x = STERN_FRONT + 0.15
    for i in range(n + 1):
        y = -w + 2 * w * i / n
        if i in lost:
            # A stump of the post is left standing
            rod(parts["spar"], (x, y, STERN_DECK_Z), (x + 0.05, y, STERN_DECK_Z + 0.25), 0.06, segs=6)
            continue
        rod(parts["spar"], (x, y, STERN_DECK_Z), (x, y, STERN_DECK_Z + 0.9), 0.06, segs=6)
    top = STERN_DECK_Z + 0.95
    if stage["rail_lost"] < 4:
        box(parts["gold_paint"], (x, 0, top), (0.16, 2 * w + 0.16, 0.12))
    else:
        # The handrail is snapped in the middle: one half still sits on its posts, the other droops to the deck
        rod(parts["gold_paint"], (x, -w - 0.08, top), (x, -0.4, top), 0.07, segs=6)
        rod(parts["gold_paint"], (x, w + 0.08, top), (x + 0.5, 0.6, STERN_DECK_Z + 0.25), 0.07, segs=6)

    # Ladder up to the stern deck
    a = Vector((STERN_FRONT + 1.9, 2.6, DECK_Z))
    b = Vector((STERN_FRONT + 0.1, 2.6, STERN_DECK_Z))
    for s in (-0.45, 0.45):
        rod(parts["spar"], a + Vector((0, s, 0)), b + Vector((0, s, 0)), 0.07, segs=6)
    for i in range(1, 5):
        box(parts["deck"], a.lerp(b, i / 5), (0.22, 0.85, 0.07))


def build_cannons(parts):
    """A cannon on a carriage at each side; the barrel sticks out through a port in the bulwark"""
    z = DECK_Z + 0.75
    for x in CANNONS_X:
        for side in (1, -1):
            inner = inner_width(x, z)
            # Port in the bulwark: a dark hole with a painted frame
            p, n = hull_point(x, z, side)
            t, n, b = side_frame(n)
            box(parts["gold_paint"], p + n * 0.03, (1.1, 0.12, 0.95), (t, n, b))
            box(parts["port"], p + n * 0.07, (0.8, 0.12, 0.7), (t, n, b))

            # Carriage with four small wheels
            cy = side * (inner - 1.0)
            box(parts["hull_wood"], (x, cy, DECK_Z + 0.32), (1.0, 1.3, 0.45))
            for dx in (-0.4, 0.4):
                for dy in (-0.45, 0.45):
                    c = Vector((x + dx, cy + dy, DECK_Z + 0.2))
                    rod(parts["iron"], c - Vector((0.08, 0, 0)), c + Vector((0.08, 0, 0)), 0.2, segs=10)

            # Barrel, pointing out through the port
            start = Vector((x, cy - side * 0.7, z))
            m = Matrix.Translation(start) @ basis(Vector((0, side, 0)))
            length = abs(p.y - start.y) + 0.55
            lathe(
                parts["iron"],
                [(0.3, 0), (0.33, 0.12), (0.3, 0.3), (0.24, length - 0.2), (0.28, length - 0.12), (0.28, length), (0.16, length + 0.01)],
                12,
                m,
            )


def build_stern(parts, stage):
    """Transom windows, rudder and the stern lantern"""
    zc = 4.9
    nx = Vector((-1, 0, -0.18)).normalized()
    up = Vector((-0.18, 0, 1)).normalized()
    side = Vector((0, 1, 0))
    for k, y in enumerate((-1.3, 1.3)):
        c = Vector((x_stern(zc), y, zc)) + nx * 0.03
        box(parts["gold_paint"], c, (1.25, 0.12, 1.15), (side, nx, up))
        # Broken windows go dark
        glass = parts["port"] if k < stage["windows_out"] else parts["glass"]
        box(glass, c + nx * 0.05, (0.9, 0.12, 0.8), (side, nx, up))
    for z in (3.0, 6.6):
        w = half_width(x_stern(z), z)
        box(parts["gold_paint"], Vector((x_stern(z), 0, z)) + nx * 0.06, (2 * w - 0.2, 0.14, 0.26), (side, nx, up))

    # Rudder hanging off the transom
    top = rail_z(-15) - 0.3
    pts = []
    for z, back in ((-1.3, 1.5), (0.0, 1.45), (2.5, 1.0), (top, 0.7)):
        xs = x_stern(z)
        pts.append((xs - 0.05, z, xs - 0.05 - back))
    prof = []
    for xa, z, xb in pts:
        prof.append((xa, z))
    for xa, z, xb in reversed(pts):
        prof.append((xb, z))
    bm = parts["weathered_part"]
    th = 0.32
    front = [bm.verts.new((x, -th / 2, z)) for x, z in prof]
    back = [bm.verts.new((x, th / 2, z)) for x, z in prof]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    k = len(prof)
    for i in range(k):
        j = (i + 1) % k
        bm.faces.new((front[j], front[i], back[i], back[j]))
    for z in (0.6, 3.2):
        xs = x_stern(z)
        box(parts["brass"], (xs - 0.55, 0, z), (1.1, th + 0.08, 0.16))
    rod(parts["spar"], (x_stern(top) - 0.6, 0, top), (x_stern(top) + 2.4, 0, top + 0.6), 0.1, segs=6)  # tiller

    # Lantern on a post at the stern; once it is smashed it hangs dark and crooked
    base = Vector((x_stern(8.2) + 0.5, 0, rail_z(-15)))
    tilt = Vector((0.5, 0.3, 1.5)) if stage["lantern_out"] else Vector((0, 0, 1.6))
    rod(parts["spar"], base, base + tilt, 0.08, segs=6)
    m = Matrix.Translation(base + tilt) @ (basis(tilt) if stage["lantern_out"] else Matrix.Identity(4))
    light = parts["port"] if stage["lantern_out"] else parts["lantern"]
    lathe(light, [(0.24, 0), (0.32, 0.3), (0.3, 0.75), (0.16, 0.85)], 6, m)
    lathe(parts["brass"], [(0.28, 0.8), (0.4, 0.88), (0.05, 1.2)], 6, m)


def build_deck_details(parts, stage):
    # Hatch grate in front of the mast
    x, sx, sy = 7.0, 2.4, 2.0
    box(parts["grate"], (x, 0, DECK_Z + 0.18), (sx, sy, 0.36))
    for dx in (-1, 1):
        box(parts["hull_wood"], (x + dx * sx / 2, 0, DECK_Z + 0.22), (0.18, sy + 0.18, 0.44))
    for dy in (-1, 1):
        box(parts["hull_wood"], (x, dy * sy / 2, DECK_Z + 0.22), (sx + 0.18, 0.18, 0.44))
    for i in range(1, 4):
        box(parts["hull_wood"], (x - sx / 2 + sx * i / 4, 0, DECK_Z + 0.38), (0.08, sy, 0.05))

    # Barrels and crates
    barrels = ((4.3, 3.1, 0.5, 1.1), (4.0, 4.2, 0.45, 1.0), (5.2, 3.8, 0.42, 0.95))
    for bx, by, r, h in barrels[: max(1, stage["crates"])]:
        barrel(parts, bx, by, DECK_Z, r, h)
    crates = ((-5.2, -3.4, DECK_Z, 1.1, 0.25), (-6.3, -2.4, DECK_Z, 0.9, -0.1), (-5.3, -3.3, DECK_Z + 1.1, 0.8, 0.6))
    for args in crates[: stage["crates"]]:
        crate(parts, *args)
    if stage["crates"] < 3:
        # The top crate was knocked off and lies on its side on the deck
        crate(parts, -3.9, -1.6, DECK_Z, 0.8, 1.1)

    # Coil of rope
    m = Matrix.Translation((9.6, -2.0, DECK_Z))
    for k in range(3):
        r = 0.55 - k * 0.12
        lathe(parts["rope"], [(r, 0.02 + k * 0.1), (r + 0.1, 0.06 + k * 0.1), (r, 0.12 + k * 0.1)], 14, m, False, False)

    # Helm on the stern deck
    hx = -11.2
    box(parts["hull_wood"], (hx, 0, STERN_DECK_Z + 0.6), (0.4, 0.45, 1.2))
    c = Vector((hx + 0.35, 0, STERN_DECK_Z + 1.45))
    pts = [c + Vector((0, math.cos(a), math.sin(a))) * 0.75 for a in angles(14)]
    for i in range(14):
        rod(parts["spar"], pts[i], pts[(i + 1) % 14], 0.06, segs=5, caps=False)
    for a in angles(8):
        rod(parts["spar"], c, c + Vector((0, math.cos(a), math.sin(a))) * 1.0, 0.045, segs=5)
    lathe(parts["brass"], [(0.14, -0.1), (0.14, 0.1)], 8, Matrix.Translation(c) @ basis(Vector((1, 0, 0))))

    # Anchor on the port bow
    p, n = hull_point(10.5, 4.6, 1)
    o = n * 0.3
    top = p + o + Vector((0, 0, 0.5))
    bottom = p + o + Vector((-0.3, 0, -2.4))
    rod(parts["iron"], top, bottom, 0.1, segs=6)
    rod(parts["spar"], top + Vector((-0.7, 0, 0)), top + Vector((0.7, 0, 0)), 0.1, segs=6)
    for dx in (-0.9, 0.9):
        tip = bottom + Vector((dx, 0, 0.8))
        rod(parts["iron"], bottom, tip, 0.09, segs=6)
        box(parts["iron"], tip, (0.4, 0.12, 0.32))

    # Figurehead scroll under the bowsprit
    z = 4.8
    m = Matrix.Translation((x_bow(z) - 0.1, 0, z)) @ basis(Vector((1, 0, 0.6)))
    lathe(parts["brass"], [(0.08, -0.2), (0.35, 0.15), (0.38, 0.6), (0.25, 1.1), (0.06, 1.35)], 10, m)


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


def build_damage(parts, stage, rng):
    """Shot holes in the hull with splintered planks around them, and wreckage floating alongside"""
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
        # Scorched wood around the hole, a little behind it
        scorch = [center - n * 0.02 + (p_ - center) * (1.5 + 0.2 * rng.random()) for p_ in rim]
        face = polygon(parts["burnt"], scorch)
        face.normal_update()
        if face.normal.dot(n) < 0:
            face.normal_flip()
        # Splinters: broken plank ends sticking out of the rim
        for _ in range(4):
            a = rng.random() * 2 * math.pi
            d = t * math.cos(a) + b * math.sin(a)
            root = center + d * r * 0.85
            tip = root + d * r * (0.5 + 0.5 * rng.random()) + n * (0.15 + 0.25 * rng.random())
            rod(parts["hull_wood"], root, tip, 0.07, 0.02, segs=4)

    for i in range(stage["debris"]):
        a = rng.random() * 2 * math.pi
        dist = 9 + 6 * rng.random()
        c = Vector((math.cos(a) * dist * 1.3, math.sin(a) * dist, 0.06))
        rot = rng.random() * math.pi
        axes = (Vector((math.cos(rot), math.sin(rot), 0)), Vector((-math.sin(rot), math.cos(rot), 0)), Vector((0, 0, 1)))
        if i % 3 == 2:
            barrel(parts, c.x, c.y, -0.5, 0.45, 1.0)  # half sunk
        else:
            box(parts["hull_wood"], c, (2.4 + rng.random(), 0.42, 0.14), axes)


# ---------------------------------------------------------------------------
# Mast, sail, rigging
# ---------------------------------------------------------------------------


def braced(along, across, z):
    """A point in the sail's frame (along = forward, across = to port), with the yard turned by BRACE"""
    c, s = math.cos(BRACE), math.sin(BRACE)
    x0 = MAST_X + 0.45
    return Vector((x0 + along * c - across * s, along * s + across * c, z))


def mast_radius(z):
    return 0.4 - (z - DECK_Z) / (NEST_Z - DECK_Z) * 0.1


def build_mast(parts, upper, stage):
    """upper: where everything above MAST_BREAK_Z goes. In stage 4 it is a separate set of parts that
    build() then topples over the side; otherwise it is `parts` itself"""
    mt = Matrix.Translation((MAST_X, 0, 0))
    if stage["mast_broken"]:
        rb = mast_radius(MAST_BREAK_Z)
        # Stump with a splintered top
        lathe(parts["spar"], [(0.42, DECK_Z - 0.5), (0.4, DECK_Z), (rb, MAST_BREAK_Z - 0.3), (rb * 0.6, MAST_BREAK_Z + 0.2), (0.05, MAST_BREAK_Z + 0.5)], 10, mt, uv_along=SPAR_TILE)
        for a in angles(5):
            d = Vector((math.cos(a), math.sin(a), 0))
            foot = Vector((MAST_X, 0, MAST_BREAK_Z - 0.2)) + d * rb * 0.7
            rod(parts["spar"], foot, foot + d * 0.15 + Vector((0, 0, 0.5 + 0.3 * math.sin(3 * a))), 0.06, 0.01, segs=4)
        lathe(upper["spar"], [(rb, MAST_BREAK_Z + 0.4), (0.3, NEST_Z), (0.22, MAST_TOP), (0.26, MAST_TOP + 0.15), (0.05, MAST_TOP + 0.4)], 10, mt, uv_along=SPAR_TILE)
    else:
        lathe(parts["spar"], [(0.42, DECK_Z - 0.5), (0.4, DECK_Z), (0.3, NEST_Z), (0.22, MAST_TOP), (0.26, MAST_TOP + 0.15), (0.05, MAST_TOP + 0.4)], 10, mt, uv_along=SPAR_TILE)
    # Iron bands around the mast
    for z in (DECK_Z + 1.2, DECK_Z + 6.0, NEST_Z - 3.0):
        r = mast_radius(z) + 0.03
        lathe((upper if z > MAST_BREAK_Z else parts)["iron"], [(r, z - 0.07), (r, z + 0.07)], 10, mt, False, False)
    parts = upper
    spar = parts["spar"]

    # Crow's nest: a small round basket near the top
    R = 1.45
    lathe(parts["deck"], [(0.25, NEST_Z - 0.18), (R, NEST_Z - 0.18), (R, NEST_Z + 0.12), (0.25, NEST_Z + 0.12)], 16, mt)
    lathe(parts["spar"], [(R - 0.1, NEST_Z + 0.12), (R, NEST_Z + 0.12), (R, NEST_Z + 1.05), (R - 0.1, NEST_Z + 1.05)], 16, mt, False, False, uv_along=SPAR_TILE)
    lathe(parts["gold_paint"], [(R - 0.12, NEST_Z + 1.05), (R + 0.04, NEST_Z + 1.05), (R + 0.04, NEST_Z + 1.17), (R - 0.12, NEST_Z + 1.17)], 16, mt, False, False)
    for a in angles(6):
        d = Vector((math.cos(a), math.sin(a), 0))
        rod(spar, Vector((MAST_X, 0, NEST_Z - 1.6)) + d * 0.3, Vector((MAST_X, 0, NEST_Z - 0.18)) + d * (R - 0.2), 0.06, segs=5)

    # Square sail between a yard at the head and a boom at the foot
    def point(u, v):
        s = u * 2 - 1
        hw = SAIL_HALF_BOTTOM + (SAIL_HALF_TOP - SAIL_HALF_BOTTOM) * v
        fv = math.sin(math.pi * v) ** 0.8 * 0.85 + 0.15 * (1 - v)
        along = SAIL_BELLY * (1 - s * s) ** 0.8 * fv
        # Shallow creases hanging from the yard, fading towards the foot where the wind pulls the cloth taut
        along += SAIL_CREASE * math.sin(s * math.pi * 5.5 + v * 1.3) * v**1.5 * (1 - s * s)
        z = SAIL_BOTTOM + (SAIL_TOP - SAIL_BOTTOM) * v
        return braced(along, -s * hw, z)

    grid_surface(parts["sail"], point, 28, 18)
    for z, hw in ((SAIL_TOP + 0.25, SAIL_HALF_TOP + 0.9), (SAIL_BOTTOM - 0.2, SAIL_HALF_BOTTOM + 0.6)):
        mid = braced(0, 0, z)
        for end in (braced(0, hw, z), braced(0, -hw, z)):
            rod(spar, mid, end, 0.2, 0.11, segs=8, uv_along=SPAR_TILE)

    # Two pennants on a short pole at the masthead; damage shreds them and fire burns them away
    pole_top = MAST_TOP + 2.4
    rod(spar, (MAST_X, 0, MAST_TOP), (MAST_X, 0, pole_top), 0.07, segs=6)
    for (key, z0, length), left in zip(
        (("pennant_red", pole_top - 0.15, 4.0), ("pennant_yellow", pole_top - 1.25, 3.2)), stage["pennants"]
    ):
        if left <= 0:
            continue
        length *= left

        def pennant(u, v, z0=z0, length=length):
            half = 0.5 * (1 - u)
            return Vector((MAST_X - 0.1 - length * u, 0.35 * math.sin(u * 4.0) * u, z0 - 0.5 + (v * 2 - 1) * half))

        grid_surface(parts[key], pennant, 10, 1)


def build_rigging(parts, stage):
    rope = parts["rope"]
    tip = Vector((26.0, 0, 9.8))
    rod(parts["spar"], (12.4, 0, 5.9), tip, 0.32, 0.16, segs=8, uv_along=SPAR_TILE)  # bowsprit
    rod(rope, tip, (x_bow(1.5) - 0.2, 0, 1.5), 0.05, segs=4, caps=False)  # bobstay
    if stage["mast_broken"]:
        return  # with the mast gone the rest of the rigging is gone too
    rod(rope, (MAST_X, 0, MAST_TOP - 0.4), tip, 0.06, segs=4, caps=False)  # forestay

    # Damage parts ropes: the first `ropes_lost` of these are skipped
    skipped = {("backstay", -1), ("brace_low", 1), ("backstay", 1)}
    skipped = set(list(sorted(skipped))[: stage["ropes_lost"]])

    for side in (1, -1):
        # Shrouds from under the crow's nest to the rail, slightly aft of the mast
        for dx in (-0.6, -2.4):
            x = MAST_X + dx
            p, n = hull_point(x, rail_z(x) - 0.3, side)
            rod(rope, Vector((MAST_X, side * 0.25, NEST_Z - 0.4)), p + n * 0.25, 0.05, segs=4, caps=False)
            box(parts["iron"], p + n * 0.2, (0.18, 0.12, 0.5))
        # Backstay to the stern
        x = -11.5
        p, n = hull_point(x, rail_z(x) - 0.3, side)
        if ("backstay", side) not in skipped:
            rod(rope, Vector((MAST_X, side * 0.2, MAST_TOP - 1.0)), p + n * 0.2, 0.045, segs=4, caps=False)
        # Braces from the yard ends back to the rail
        for name, z, hw in (("brace_high", SAIL_TOP + 0.25, SAIL_HALF_TOP + 0.9), ("brace_low", SAIL_BOTTOM - 0.2, SAIL_HALF_BOTTOM + 0.6)):
            if (name, side) in skipped:
                continue
            end = braced(0, side * hw, z)
            x = -6.0
            p, n = hull_point(x, rail_z(x), side)
            rod(rope, end, p, 0.05, segs=4, caps=False)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

OBJECT_NAMES = {
    "deck": "Decks",
    "hull_wood": "Woodwork",
    "weathered_part": "Rudder",
    "gold_paint": "Trim",
    "port": "Gunports",
    "iron": "Iron",
    "brass": "Brass",
    "glass": "Windows",
    "lantern": "Lantern",
    "spar": "Spars",
    "rope": "Rigging",
    "sail": "Sail",
    "pennant_red": "PennantRed",
    "pennant_yellow": "PennantYellow",
    "grate": "Hatch",
    "burnt": "Scorch",
}
PART_MATERIAL = {"hull_wood": "hull", "weathered_part": "weathered"}
# Parts whose UVs come from box projection, with the tile size that sets the plank width
BOX_UV_TILE = {"deck": DECK_TILE, "hull_wood": HULL_TILE, "weathered_part": HULL_TILE, "gold_paint": HULL_TILE, "spar": SPAR_TILE, "iron": 3.0}


def clear_previous():
    coll = bpy.data.collections.get("Ship")
    if coll:
        for obj in list(coll.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)
        bpy.data.collections.remove(coll)
    # Materials and images left over from an earlier model in this file
    for block in (bpy.data.materials, bpy.data.meshes, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def build(damage=None):
    """damage: stage 0..4 (see DAMAGE_STAGES); by default the scene's "damage" custom property, or 0"""
    if damage is None:
        damage = int(bpy.context.scene.get("damage", 0))
    stage = DAMAGE_STAGES[damage]
    bpy.context.scene["damage"] = damage
    clear_previous()
    coll = bpy.data.collections.new("Ship")
    bpy.context.scene.collection.children.link(coll)

    mats = make_materials(stage)
    # render_sprites.py turns the object named "Ship"; everything else is parented to it
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 8
    coll.objects.link(root)

    hull = build_hull(mats, coll)
    hull.parent = root

    parts = Parts()
    upper = Parts() if stage["mast_broken"] else parts
    build_decks(parts, stage)
    build_cannons(parts)
    build_stern(parts, stage)
    build_deck_details(parts, stage)
    build_mast(parts, upper, stage)
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


def topple(upper, parts):
    """Swings the broken top of the mast over the side around the break, then merges it into `parts`"""
    pivot = Vector((MAST_X, 0, MAST_BREAK_Z))
    fall = Vector((MAST_FALL_DIR[0], MAST_FALL_DIR[1], 0)).normalized()
    axis = Vector((0, 0, 1)).cross(fall)
    m = Matrix.Translation(pivot) @ Matrix.Rotation(math.radians(MAST_FALL_ANGLE), 4, axis) @ Matrix.Translation(-pivot)
    for key, bm in upper.meshes.items():
        bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
        tmp = bpy.data.meshes.new("toppled")
        bm.to_mesh(tmp)
        bm.free()
        parts[key].from_mesh(tmp)
        bpy.data.meshes.remove(tmp)


if __name__ == "__main__":
    build()

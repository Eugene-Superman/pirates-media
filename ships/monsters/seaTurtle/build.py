"""
Giant sea turtle (line "monsters", game class "seaTurtle"), built from code: a sea monster that rams and bites ships.
A domed shell of plates with amber streaks and algae, a head with a hooked beak and a jaw that opens, long front
flippers and short hind ones, the tail.

Animated: the head, the jaw, the neck and each flipper hang on an empty (a joint, "Joint.*" in the outliner), and the
joints are keyframed. Swim: frames 1-12, a loop (frame 13 is frame 1 again): the front flippers row back and forth
near the surface (a stroke under it would be lost: the water hides it), the hind ones paddle, the head nods and sways.
Bite: frames 101-106: the mouth opens, the neck shoots the head forward, the jaw snaps shut and the head comes back.
Frame 201 is the dead turtle's pose. The timeline has a marker at each. Edit the keys in the Dope Sheet as you like,
then render; ANIMATIONS below says which frames make the game's animations, and render_stages.py renders every one of
them from every direction.

Run in Blender: open seaTurtle.blend next to this file, Scripting tab -> Open -> build.py -> Run Script. It rebuilds
the "Ship" collection (the joints and their keys too) for the scene's "damage" property (0-4, see DAMAGE_STAGES).

Damage: 1 a harpoon in the shell, scratches; 2 a second harpoon trailing its line, cracks across the plates, wounds;
3 a third harpoon, a piece of the shell's rim broken off, blood in the water round it; 4 dead: belly up, sinking
(the game takes it under).

Axes and scale match the game: 1 Blender unit = 1 game unit, the head points to +X, port side to +Y, Z up, waterline
at Z = 0: the shell rides above it, the flippers stroke at the surface. src/game/ships/shipClasses.ts, seaTurtle:
bow 9, stern -7, half-beam 6.

Textures: scanned CC0 sets from Poly Haven (polyhaven.com) in blender-assets/textures/polyhaven/, downloaded there on the
first run: the shell's pitted plates and their algae, the skin's wrinkles; the plates' pattern and the scales are
generated (textures/ next to this file, and shader nodes).
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

# The shell: its middle, half-length and half-width, the dome's height over the rim and the rim over the water
SHELL = dict(cx=-1.0, a=7.0, b=5.5, h=3.1, rim=0.35, bottom=-0.75)
NECK = dict(x=5.0, z=0.7, length=1.7, r0=1.3, r1=1.1, rise=12.0)  # rise: degrees the neck slants up
HEAD = dict(length=3.5, width=1.3, height=1.15)  # length, half-width and half-height; the beak from 72 % of its length
JAW = dict(x=0.8, z=-0.38, length=2.5, width=1.0, depth=0.5)
# Flippers: the joint (where the flipper leaves the shell), length, widest chord, how far the tip sweeps back
FLIPPERS = {
    "Fore": dict(x=3.4, y=3.9, z=0.45, length=7.0, chord=2.8, sweep=2.5, droop=-0.3),
    "Hind": dict(x=-5.6, y=3.3, z=0.35, length=3.4, chord=2.3, sweep=1.1, droop=-0.2),
}
TAIL = dict(x=-7.9, z=0.15, length=1.6, r=0.45)

# The game's animations: which frames of the timeline, at how many frames a second the game plays them
# prettier-ignore
ANIMATIONS = {
    "swim": dict(start=1, frames=12, fps=12, loop=True),
    "bite": dict(start=101, frames=6, fps=13, loop=False),
}
DEAD = {"swim": dict(start=201, frames=1, fps=1, loop=True)}
SWIM_FRAMES = 12
# The swim's strokes, radians: each flipper rows forward and back (sweep, round `reach` forward of its rest: swept
# far back it would hide under the shell) and rises and dips (flap) round a lift that keeps it at the surface, where it
# can be seen
# prettier-ignore
STROKE = {
    "Fore": dict(lift=0.14, flap=0.22, sweep=0.7, reach=0.2),
    "Hind": dict(lift=0.08, flap=0.12, sweep=0.45, reach=0.0),
}
BITE_START = 101
DEAD_FRAME = 201

SHELL_TILE = 6.0  # world units of the scanned plates' texture
SKIN_TILE = 3.0
SCALE_SIZE = 2.6  # how many scales a unit: the procedural scales on the skin

COLORS = {
    "shell": 0x6B5A2E,
    "shell_dark": 0x4A3D1F,
    "amber": 0xC08A3A,
    "seam": 0x2A2112,
    "skin": 0x5E6A44,
    "skin_edge": 0xC9BC8A,
    "plastron": 0xE3D3A2,
    "plastron_seam": 0xA48E5C,
    "beak": 0x3A3127,
    "eye": 0x0E0E0E,
    "mouth": 0x7A2A2A,
    "wound": 0x5A1010,
    "blood": 0x6A0E0E,
    "scratch": 0xB7A47A,
    "crack": 0x1C1408,
    "shaft": 0x7A5A35,
    "iron": 0x3A3A40,
    "rope": 0x8E6B44,
}

# prettier-ignore
DAMAGE_STAGES = {
    0: dict(harpoons=0, scratches=0, cracks=0, blood=0.0, wounds=0, chunk=False, pool=0.0, dead=False),
    1: dict(harpoons=1, scratches=5, cracks=0, blood=0.1, wounds=0, chunk=False, pool=0.0, dead=False),
    2: dict(harpoons=2, scratches=8, cracks=3, blood=0.25, wounds=2, chunk=False, pool=0.0, dead=False),
    3: dict(harpoons=3, scratches=10, cracks=6, blood=0.45, wounds=3, chunk=True, pool=0.55, dead=False),
    4: dict(harpoons=3, scratches=10, cracks=8, blood=0.55, wounds=3, chunk=True, pool=0.8, dead=True),
}
# Harpoons in the shell: where they went in (shell x, y), the way they point out of it, and whether a line trails from
# the shaft into the water
HARPOONS = [((-3.2, 1.8), (-0.65, 0.3, 0.7), True), ((1.4, -2.6), (-0.5, -0.45, 0.75), True), ((-0.8, 3.4), (-0.3, 0.6, 0.75), False)]
# Wounds on the skin: which part, where along it (0..1), side
WOUNDS = [("Fore", 0.35, 1), ("Neck", 0.5, -1), ("Hind", 0.5, -1)]
CHUNK_ANGLE = 2.35  # radians round the shell (0 = the front, + to port) where a piece of the rim is gone
WEAR_SEED = 2


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


SHIP_DIR = os.environ.get("SHIP_OUT") or base_dir()  # ships/monsters/seaTurtle
TEX_DIR = os.path.join(SHIP_DIR, "textures")
PH_DIR = os.path.join(assets_root(SHIP_DIR), "textures", "polyhaven")


def animations(stage):
    """The game's animations rendered for a damage stage: the dead turtle only lies there"""
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
# Textures
# ---------------------------------------------------------------------------


def shell_uv(x, y):
    """Where a point of the shell is in its texture: seen from above, the whole outline inside 0..1"""
    return ((x - SHELL["cx"]) / (2.3 * SHELL["a"]) + 0.5, y / (2.3 * SHELL["b"]) + 0.5)


def shell_texture(name, stage, size=512):
    """The plates: a row of five down the back, four a side, a ring of small ones round the rim; olive brown with amber
    streaks fanning from the back of each plate and growth rings along its seams. Damage scratches the plates, cracks
    them and stains them with blood"""
    rng = np.random.default_rng(7)
    n = (np.arange(size) + 0.5) / size
    us = (n[None, :] - 0.5) * 2.3  # shell x, in half-lengths
    vs = ((1 - n[:, None]) - 0.5) * 2.3  # shell y, in half-widths
    us, vs = np.broadcast_arrays(us, vs)
    seeds = [(0.62, 0.0), (0.32, 0.0), (0.0, 0.0), (-0.32, 0.0), (-0.62, 0.0)]
    for s in (1, -1):
        seeds += [(0.42, 0.5 * s), (0.14, 0.56 * s), (-0.16, 0.56 * s), (-0.44, 0.5 * s)]
    for k in range(24):
        a = 2 * math.pi * (k + 0.5) / 24
        seeds.append((0.93 * math.cos(a), 0.93 * math.sin(a)))
    pts = np.array(seeds)
    # Distances to every seed, squashed across so the plates are wider than long, as on a real shell
    d = np.sqrt((us[..., None] - pts[:, 0]) ** 2 + ((vs[..., None] - pts[:, 1]) * 0.85) ** 2).astype(np.float32)
    two = np.partition(d, 1, axis=-1)
    nearest, second = two[..., 0], two[..., 1]
    cell = np.argmin(d, axis=-1)
    edge = second - nearest  # 0 on a seam
    tone = (0.85 + 0.3 * rng.random(len(seeds)))[cell]
    base = np.array(srgb(COLORS["shell"]))
    dark = np.array(srgb(COLORS["shell_dark"]))
    amber = np.array(srgb(COLORS["amber"]))
    # Streaks fanning out of each plate's back corner
    cx, cy = pts[cell, 0], pts[cell, 1]
    ang = np.arctan2(vs - cy, us - (cx - 0.12))
    noise = value_noise(size, 24, rng)
    streak = np.clip(np.sin(ang * 9 + noise * 5 + cell * 1.7) * 0.5 + 0.5, 0, 1) ** 3 * (0.4 + 0.6 * noise)
    rgb = base[None, None, :] * tone[..., None]
    rgb = rgb * (1 - 0.55 * streak[..., None]) + amber[None, None, :] * (0.55 * streak[..., None])
    rings = 0.5 + 0.5 * np.sin(edge * 120)
    rgb = rgb * (1 - 0.12 * (rings * (edge < 0.12))[..., None])
    rgb = np.where((edge < 0.035)[..., None], rgb * 0.55 + dark * 0.2, rgb)
    rgb = np.where((edge < 0.015)[..., None], np.array(srgb(COLORS["seam"])), rgb)
    rgb = rgb * (0.9 + 0.2 * value_noise(size, 40, rng))[..., None]

    # Damage, in the same places stage after stage: scratches, then cracks, then blood
    hurt = np.random.default_rng(WEAR_SEED)
    for _ in range(stage["scratches"]):
        x0, y0 = hurt.uniform(-0.8, 0.8), hurt.uniform(-0.7, 0.7)
        a = hurt.uniform(0, math.pi)
        length = hurt.uniform(0.15, 0.35)
        along = (us - x0) * math.cos(a) + (vs - y0) * math.sin(a)
        across = -(us - x0) * math.sin(a) + (vs - y0) * math.cos(a)
        line = (np.abs(across) < 0.008) & (np.abs(along) < length)
        rgb = np.where(line[..., None], np.array(srgb(COLORS["scratch"])), rgb)
    for _ in range(stage["cracks"]):
        x, y = hurt.uniform(-0.6, 0.6), hurt.uniform(-0.6, 0.6)
        a = hurt.uniform(0, 2 * math.pi)
        crack = np.zeros_like(us, dtype=bool)
        for _ in range(9):
            a += hurt.uniform(-0.7, 0.7)
            nx, ny = x + 0.07 * math.cos(a), y + 0.07 * math.sin(a)
            # A segment of the crack: points near the line from (x, y) to (nx, ny)
            t = np.clip(((us - x) * (nx - x) + (vs - y) * (ny - y)) / 0.0049, 0, 1)
            crack |= np.hypot(us - (x + t * (nx - x)), vs - (y + t * (ny - y))) < 0.011
            x, y = nx, ny
        rgb = np.where(crack[..., None], np.array(srgb(COLORS["crack"])), rgb)
    if stage["blood"] > 0:
        stain = value_noise(size, 10, np.random.default_rng(WEAR_SEED + 1))
        mask = np.clip((stain - (1 - stage["blood"] * 0.9)) / 0.08, 0, 1)
        rgb = rgb * (1 - 0.75 * mask[..., None]) + np.array(srgb(COLORS["wound"])) * (0.75 * mask[..., None])
    rgba = np.concatenate([np.clip(rgb, 0, 1), np.ones((size, size, 1))], axis=2)
    return save_image(name, rgba)


def plastron_texture(name, size=512):
    """The belly plates: pale yellow, a seam down the middle and five across"""
    n = (np.arange(size) + 0.5) / size
    us = (n[None, :] - 0.5) * 2.3
    vs = ((1 - n[:, None]) - 0.5) * 2.3
    us, vs = np.broadcast_arrays(us, vs)
    rgb = np.ones((size, size, 3)) * np.array(srgb(COLORS["plastron"]))
    rgb *= (0.92 + 0.12 * value_noise(size, 12, np.random.default_rng(3)))[..., None]
    seam = np.abs(vs) < 0.012
    for u in (0.55, 0.28, 0.0, -0.3, -0.58):
        seam |= np.abs(us - u - 0.05 * np.abs(vs)) < 0.012
    rgb = np.where(seam[..., None], np.array(srgb(COLORS["plastron_seam"])), rgb)
    return save_image(name, np.concatenate([np.clip(rgb, 0, 1), np.ones((size, size, 1))], axis=2))


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


def shell_material(name, image):
    """The plates' pattern (an image seen from above) over the grain of pitted rock, with algae in patches"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.6
    coord = nodes.new("ShaderNodeTexCoord")
    pattern = nodes.new("ShaderNodeTexImage")
    pattern.image = image
    links.new(coord.outputs["UV"], pattern.inputs["Vector"])
    shade, _, normal = grain(nodes, links, "rock_pitted_mossy", coord.outputs["Object"], SHELL_TILE, 0.75, 1.15)
    color = multiply(nodes, links, pattern.outputs["Color"], shade)
    # Algae and weed in patches, thicker towards the rim
    _, algae, _ = grain(nodes, links, "mossy_rock", coord.outputs["Object"], SHELL_TILE * 0.7)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.35
    noise.inputs["Detail"].default_value = 5.0
    links.new(coord.outputs["Object"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.clamp = True
    ramp.inputs["From Min"].default_value = 0.55
    ramp.inputs["From Max"].default_value = 0.7
    ramp.inputs["To Max"].default_value = 0.65
    links.new(noise.outputs["Fac"], ramp.inputs["Value"])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    links.new(ramp.outputs["Result"], mix.inputs[0])
    links.new(color, mix.inputs[6])
    links.new(algae, mix.inputs[7])
    links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    if normal is not None:
        links.new(normal, bsdf.inputs["Normal"])
    m.diffuse_color = linear(COLORS["shell"])
    return m


def skin_material(name):
    """Olive skin in big polygonal scales with pale edges (a Voronoi pattern in the shader), over leathery wrinkles"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.55
    coord = nodes.new("ShaderNodeTexCoord")
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.feature = "DISTANCE_TO_EDGE"
    vor.inputs["Scale"].default_value = SCALE_SIZE
    links.new(coord.outputs["Object"], vor.inputs["Vector"])
    edge = nodes.new("ShaderNodeMapRange")
    edge.clamp = True
    edge.inputs["From Min"].default_value = 0.02
    edge.inputs["From Max"].default_value = 0.09
    links.new(vor.outputs["Distance"], edge.inputs["Value"])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    links.new(edge.outputs["Result"], mix.inputs[0])
    mix.inputs[6].default_value = linear(COLORS["skin_edge"])
    mix.inputs[7].default_value = linear(COLORS["skin"])
    shade, _, normal = grain(nodes, links, "leather_white", coord.outputs["Object"], SKIN_TILE, 0.7, 1.15)
    links.new(multiply(nodes, links, mix.outputs[2], shade), bsdf.inputs["Base Color"])
    if normal is not None:
        links.new(normal, bsdf.inputs["Normal"])
    m.diffuse_color = linear(COLORS["skin"])
    return m


def textured(name, image, rough=0.7):
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = rough
    coord = nodes.new("ShaderNodeTexCoord")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    links.new(coord.outputs["UV"], tex.inputs["Vector"])
    shade, _, _ = grain(nodes, links, "leather_white", coord.outputs["Object"], SKIN_TILE, 0.85, 1.1)
    links.new(multiply(nodes, links, tex.outputs["Color"], shade), bsdf.inputs["Base Color"])
    m.diffuse_color = linear(COLORS["plastron"])
    return m


def make_materials(stage, index):
    return {
        "shell": shell_material("TurtleShell", shell_texture(f"turtle_shell_d{index}" if index else "turtle_shell", stage)),
        "plastron": textured("TurtlePlastron", plastron_texture("turtle_plastron")),
        "skin": skin_material("TurtleSkin"),
        "beak": plain("TurtleBeak", COLORS["beak"], rough=0.45),
        "eye": plain("TurtleEye", COLORS["eye"], rough=0.15),
        "mouth": plain("TurtleMouth", COLORS["mouth"], rough=0.5),
        "wound": plain("TurtleWound", COLORS["wound"], rough=0.35),
        "blood": plain("TurtleBloodInWater", COLORS["blood"], rough=0.2, alpha=0.35),
        "shaft": plain("HarpoonShaft", COLORS["shaft"], rough=0.8),
        "iron": plain("HarpoonIron", COLORS["iron"], rough=0.45, metal=0.7),
        "rope": plain("HarpoonLine", COLORS["rope"], rough=1.0),
    }


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
# Body
# ---------------------------------------------------------------------------


def outline(theta, stage):
    """The shell's edge at an angle round it (0 = the front, + to port), as (x, y): wider in front, drawn to a point
    behind, the rim scalloped by the marginal plates over the tail; a piece broken out of it at CHUNK_ANGLE"""
    c, s = math.cos(theta), math.sin(theta)
    r = 1.0 - 0.03 * abs(math.sin(12 * theta)) * smoothstep(0.0, -0.8, c)
    if stage["chunk"]:
        d = math.atan2(math.sin(theta - CHUNK_ANGLE), math.cos(theta - CHUNK_ANGLE))
        if abs(d) < 0.22:
            r -= 0.13 * (1 - abs(d) / 0.22) ** 0.5 + 0.025 * math.sin(theta * 40)
    x = SHELL["cx"] + SHELL["a"] * r * c * (1 + 0.06 * max(0.0, -c) ** 2)
    y = SHELL["b"] * r * s * (1 + 0.1 * c)
    return x, y


def shell_point(u, v, stage):
    """The dome: u round it, v from its top (0) out to the rim (1)"""
    x, y = outline(2 * math.pi * u, stage)
    px = SHELL["cx"] + (x - SHELL["cx"]) * v
    py = y * v
    z = SHELL["rim"] + SHELL["h"] * max(0.0, 1 - v**2.2) ** 0.6
    # A low ridge down the middle of the back
    z += 0.22 * math.exp(-((py / SHELL["b"]) / 0.12) ** 2) * (1 - v**3)
    return Vector((px, py, z))


def shell_z(x, y):
    """Height of the top of the shell over a point inside it"""
    best = SHELL["rim"]
    dx = (x - SHELL["cx"]) / SHELL["a"]
    dy = y / SHELL["b"]
    v = min(1.0, math.hypot(dx, dy))
    best += SHELL["h"] * max(0.0, 1 - v**2.2) ** 0.6
    return best


def build_shell(bm, stage):
    inside = Vector((SHELL["cx"], 0, SHELL["rim"]))
    faces = surface(bm, lambda u, v: shell_point(u, v, stage), 48, 14, lambda p: shell_uv(p.x, p.y), mat=0, closed_u=True)
    # The rim's underside down into the water, and the belly
    def skirt(u, v):
        x, y = outline(2 * math.pi * u, stage)
        k = 1 - 0.06 * v
        return Vector((SHELL["cx"] + (x - SHELL["cx"]) * k, y * k, SHELL["rim"] + (SHELL["bottom"] - SHELL["rim"]) * v))

    faces += surface(bm, skirt, 48, 2, lambda p: shell_uv(p.x, p.y), mat=0, closed_u=True)

    def belly(u, v):
        x, y = outline(2 * math.pi * u, stage)
        k = 0.94 * (1 - v)
        return Vector((SHELL["cx"] + (x - SHELL["cx"]) * k, y * k, SHELL["bottom"] - 0.25 * (1 - (1 - v) ** 2)))

    faces += surface(bm, belly, 48, 6, lambda p: shell_uv(p.x, p.y), mat=1, closed_u=True)
    orient(faces, lambda _f: inside)


def build_tail(bm):
    m = Matrix.Translation((TAIL["x"] + 0.6, 0, TAIL["z"])) @ basis(Vector((-1, 0, -0.15)))
    lathe(bm, [(TAIL["r"], 0), (TAIL["r"] * 0.6, TAIL["length"] * 0.6), (0.05, TAIL["length"])], 8, m, mat=2, smooth=True)


def flipper(bm, spec, side):
    """A flipper from its joint outward along y (port for side 1), sweeping back to its tip: a flattened airfoil whose
    chord grows out from the root and narrows to a point"""
    length, chord, sweep, droop = spec["length"], spec["chord"], spec["sweep"], spec["droop"]

    def point(u, v):
        t = v
        a = 2 * math.pi * u
        c = chord * (math.sin(math.pi * min(1.0, t * 1.15)) ** 0.6 * (1 - 0.85 * t**3)) + 0.3 * (1 - t)
        thick = 0.42 * (1 - 0.75 * t)
        cx = -sweep * t**1.6 - 0.15 * c
        x = cx + 0.5 * c * math.cos(a) * (1 + 0.15 * math.cos(a))  # the leading edge rounder
        z = droop * t + 0.5 * thick * math.sin(a)
        return Vector((x, side * length * t, z))

    def spine(f):
        c = f.calc_center_median()
        t = min(1.0, abs(c.y) / length)
        return Vector((-sweep * t**1.6 - 0.15 * chord * math.sin(math.pi * min(1.0, t * 1.15)) ** 0.6, c.y, droop * t))

    orient(surface(bm, point, 12, 12, mat=2, closed_u=True), spine)


def build_head(bm_head, bm_jaw):
    """The head from its joint forward: a blunt ellipsoid whose front narrows to a hooked beak, the eyes on its sides;
    the jaw, hinged under it, with the mouth's red inside on its top"""
    L, W, H = HEAD["length"], HEAD["width"], HEAD["height"]

    def snout(x, y, z):
        f = max(0.0, x)
        squeeze = 1 - 0.38 * f**2
        hook = -0.18 * f**4  # the beak's tip curves down
        lower = 0.65 if z < 0 and x > 0.1 else 1.0  # the jaw fills the front of the underside
        return x, y * squeeze, z * squeeze * lower + hook

    ellipsoid(bm_head, (L / 2, 0, 0.05), (L / 2, W, H), mat=2, shape=snout)
    for f in bm_head.faces:
        if f.calc_center_median().x > L * 0.72:
            f.material_index = 3
    for s in (1, -1):
        ellipsoid(bm_head, (L * 0.6, s * W * 0.9, H * 0.35), (0.24, 0.2, 0.22), mat=4, segs=8, rings=6)

    # Jaw, in the jaw joint's frame: from the hinge forward
    jl, jw, jd = JAW["length"], JAW["width"], JAW["depth"]

    def jaw(x, y, z):
        f = max(0.0, x)
        squeeze = 1 - 0.4 * f**2
        return x, y * squeeze, min(z, 0.0)

    ellipsoid(bm_jaw, (jl * 0.5, 0, 0), (jl * 0.5, jw, jd), mat=2, segs=12, rings=8, shape=jaw)
    for f in bm_jaw.faces:
        if f.calc_center_median().x > jl * 0.62:
            f.material_index = 3
    # The mouth: the jaw's top, red
    mouth = [Vector((jl * 0.5 + jl * 0.45 * math.cos(a), jw * 0.85 * math.sin(a) * (1 - 0.35 * max(0.0, math.cos(a)) ** 2), 0.02)) for a in angles(12)]
    polygon(bm_jaw, mouth, mat=5)


def build_neck(bm):
    """The neck along x from its joint, in the neck joint's frame: a joint that stretches along x as the head shoots out"""
    m = basis(Vector((1, 0, 0)))
    lathe(bm, [(NECK["r0"], -0.6), (NECK["r0"], 0.0), (NECK["r1"] * 1.05, NECK["length"] * 0.6), (NECK["r1"], NECK["length"] + 0.4)], 12, m, mat=2, smooth=True)


def harpoon(bm, at, direction, trailing):
    """A harpoon stuck in the shell: its iron in, the shaft out, a line from the shaft's end down into the water"""
    d = Vector(direction).normalized()
    base = at - d * 0.5
    end = at + d * 4.2
    rod(bm, base, end, 0.11, 0.09, segs=6, mat=6)
    rod(bm, at - d * 0.1, at + d * 0.45, 0.16, 0.13, segs=6, mat=7)
    for k in (-1, 1):
        fin = end - d * 0.5 + d.cross(Vector((0, 0, 1))).normalized() * 0.35 * k
        rod(bm, end - d * 0.9, fin, 0.04, 0.02, segs=4, mat=6)
    if trailing:
        a = end - d * 0.2
        b = Vector((a.x - 3.5, a.y + 1.4 * math.copysign(1, a.y), -0.2))
        mid = a.lerp(b, 0.5) + Vector((0, 0, -0.8))
        for p, q in ((a, mid), (mid, b)):
            rod(bm, p, q, 0.05, segs=4, mat=8, caps=False)


def wound(bm, center, normal, r):
    """A gash on the skin: a dark red patch standing a little off the surface"""
    n = Vector(normal).normalized()
    t = n.cross(Vector((0, 0, 1)))
    if t.length < 1e-3:
        t = Vector((1, 0, 0))
    t.normalize()
    b = n.cross(t)
    pts = [Vector(center) + n * 0.05 + (t * math.cos(a) * 1.6 + b * math.sin(a)) * r * (0.75 + 0.25 * math.sin(3 * a)) for a in angles(9)]
    f = polygon(bm, pts, mat=9)
    f.normal_update()
    if f.normal.dot(n) < 0:
        f.normal_flip()


def blood_pool(bm, amount):
    """Blood spreading in the water round a badly hurt turtle: see-through, lying on the water"""
    rng = np.random.default_rng(4)
    phases = rng.random(4) * 6.28
    pts = []
    for a in angles(28):
        r = (4.5 + 4.5 * amount) * (1 + 0.18 * sum(math.sin((k + 2) * a + p) for k, p in enumerate(phases)) / 4)
        pts.append((SHELL["cx"] - 1.5 + r * math.cos(a) * 1.25, r * math.sin(a), 0.03))
    polygon(bm, pts, mat=10)


# ---------------------------------------------------------------------------
# Joints and their keys
# ---------------------------------------------------------------------------

MATERIAL_ORDER = ("shell", "plastron", "skin", "beak", "eye", "mouth", "shaft", "iron", "rope", "wound", "blood")


def joint(coll, name, parent, location, rotation=(0.0, 0.0, 0.0)):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "SPHERE"
    obj.empty_display_size = 0.4
    coll.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.rotation_mode = "XYZ"
    obj.rotation_euler = rotation
    return obj


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


def new_bm():
    bm = bmesh.new()
    bm.loops.layers.uv.verify()
    return bm


def key(obj, frame, rotation=None, location=None, scale=None):
    if rotation is not None:
        obj.rotation_euler = rotation
        obj.keyframe_insert("rotation_euler", frame=frame)
    if location is not None:
        obj.location = location
        obj.keyframe_insert("location", frame=frame)
    if scale is not None:
        obj.scale = scale
        obj.keyframe_insert("scale", frame=frame)


def animate(joints):
    """Swim (frames 1-8, frame 9 = 1), bite (101-106) and the dead pose (201) on every joint"""
    neck, head, jaw = joints["neck"], joints["head"], joints["jaw"]
    neck_rot = tuple(neck.rotation_euler)
    head_loc = tuple(head.location)
    rise = math.radians(NECK["rise"])
    for k in range(SWIM_FRAMES + 1):
        phi = 2 * math.pi * k / SWIM_FRAMES
        frame = 1 + k
        for name in ("Fore", "Hind"):
            s = STROKE[name]
            for side in (1, -1):
                j = joints[f"{name}.{'L' if side > 0 else 'R'}"]
                if name == "Fore":
                    # The front flippers row together: up and forward, then down and back, the power stroke
                    flap, sweep = s["lift"] + s["flap"] * math.sin(phi), -s["reach"] - s["sweep"] * math.cos(phi)
                else:
                    # The hind ones paddle against them
                    flap, sweep = s["lift"] + s["flap"] * math.sin(phi + math.pi), s["sweep"] * math.sin(phi + math.pi / 2)
                key(j, frame, rotation=(side * flap, 0.0, side * sweep))
        # The neck nods with the strokes and sways a little from side to side
        key(neck, frame, rotation=(neck_rot[0], neck_rot[1] - 0.08 * math.sin(phi), neck_rot[2] + 0.12 * math.sin(phi + 0.6)), scale=(1, 1, 1))
        key(head, frame, location=(head_loc[0], head_loc[1], head_loc[2] + 0.25 * math.sin(phi)), rotation=(0, -rise + 0.08 * math.sin(phi + 1), 0))
        key(jaw, frame, rotation=(0, 0, 0))
    # The bite: the mouth opens, the neck shoots the head forward, the jaw snaps shut, back again
    # prettier-ignore
    bite = [  # lunge (units), jaw open (degrees), head pitch (degrees, + nods down), fore flippers spread
        (0.0, 12, 0, 0.1), (1.3, 36, -6, 0.35), (2.6, 42, -10, 0.45), (2.9, 0, -3, 0.3), (2.0, 0, 0, 0.15), (0.9, 6, 0, 0.05),
    ]
    for k, (lunge, open_deg, pitch, spread) in enumerate(bite):
        frame = BITE_START + k
        reach = (NECK["length"] + lunge) / NECK["length"]
        key(neck, frame, rotation=neck_rot, scale=(reach, 1, 1))
        dx = lunge * math.cos(rise)
        dz = lunge * math.sin(rise)
        key(head, frame, location=(head_loc[0] + dx, head_loc[1], head_loc[2] + dz), rotation=(0, -rise + math.radians(pitch), 0))
        key(jaw, frame, rotation=(0, math.radians(open_deg), 0))
        for name in ("Fore", "Hind"):
            for side in (1, -1):
                j = joints[f"{name}.{'L' if side > 0 else 'R'}"]
                key(j, frame, rotation=(side * spread * (1 if name == "Fore" else 0.3), 0.0, -side * spread * 0.6))
    # Dead: flippers limp, the head hanging, the mouth a little open
    key(neck, DEAD_FRAME, rotation=(neck_rot[0], neck_rot[1] + 0.3, neck_rot[2]), scale=(1, 1, 1))
    key(head, DEAD_FRAME, location=head_loc, rotation=(0, -rise + 0.5, 0))
    key(jaw, DEAD_FRAME, rotation=(0, math.radians(14), 0))
    for name in ("Fore", "Hind"):
        for side in (1, -1):
            key(joints[f"{name}.{'L' if side > 0 else 'R'}"], DEAD_FRAME, rotation=(-side * 0.35, 0.0, side * 0.25))


def set_timeline():
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = SWIM_FRAMES
    scene.render.fps = ANIMATIONS["swim"]["fps"]
    scene.timeline_markers.clear()
    for name, frame in (("swim", 1), ("bite", BITE_START), ("dead", DEAD_FRAME)):
        scene.timeline_markers.new(name, frame=frame)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


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
    mats = make_materials(stage, damage)

    # render_sprites.py turns the object named "Ship"; the body under it turns over when the turtle is dead
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 6
    coll.objects.link(root)
    body = joint(coll, "Body", root, (0, 0, 0))
    if stage["dead"]:
        # Belly up, a little on its side, the belly out of the water
        body.rotation_euler = (math.pi - 0.3, 0.0, 0.0)
        body.location = (0, 0, -0.1)

    bm = new_bm()
    build_shell(bm, stage)
    build_tail(bm)
    for (x, y), direction, trailing in HARPOONS[: stage["harpoons"]]:
        harpoon(bm, Vector((x, y, shell_z(x, y) - 0.1)), direction, trailing and not stage["dead"])
    mesh_object(coll, "Shell", bm, mats, body)

    rise = math.radians(NECK["rise"])
    neck_joint = joint(coll, "Joint.Neck", body, (NECK["x"], 0, NECK["z"]), (0, -rise, 0))
    bm = new_bm()
    build_neck(bm)
    if stage["wounds"] >= 2:
        wound(bm, Vector((NECK["length"] * 0.5, -NECK["r0"] * 0.95, 0.1)), (0, -1, 0.3), 0.35)
    mesh_object(coll, "Neck", bm, mats, neck_joint)

    head_at = Vector((NECK["x"], 0, NECK["z"])) + Vector((math.cos(rise), 0, math.sin(rise))) * NECK["length"]
    head_joint = joint(coll, "Joint.Head", body, tuple(head_at), (0, -rise, 0))
    jaw_joint = joint(coll, "Joint.Jaw", head_joint, (JAW["x"], 0, JAW["z"]))
    bm_head, bm_jaw = new_bm(), new_bm()
    build_head(bm_head, bm_jaw)
    mesh_object(coll, "Head", bm_head, mats, head_joint)
    mesh_object(coll, "Jaw", bm_jaw, mats, jaw_joint)

    joints = {"neck": neck_joint, "head": head_joint, "jaw": jaw_joint}
    for name, spec in FLIPPERS.items():
        for side in (1, -1):
            j = joint(coll, f"Joint.{name}.{'L' if side > 0 else 'R'}", body, (spec["x"], side * spec["y"], spec["z"]))
            bm = new_bm()
            flipper(bm, spec, side)
            for part, along, wside in WOUNDS[: stage["wounds"]]:
                if part == name and wside == side:
                    t = along
                    wound(bm, Vector((-spec["sweep"] * t**1.6, side * spec["length"] * t, spec["droop"] * t + 0.2)), (0, 0, 1), 0.3)
            mesh_object(coll, f"Flipper.{name}.{'L' if side > 0 else 'R'}", bm, mats, j)
            joints[f"{name}.{'L' if side > 0 else 'R'}"] = j

    if stage["pool"] > 0:
        bm = new_bm()
        blood_pool(bm, stage["pool"])
        mesh_object(coll, "BloodInWater", bm, mats, root)

    animate(joints)
    set_timeline()
    scene.frame_set(DEAD_FRAME if stage["dead"] else 1)
    return root


if __name__ == "__main__":
    build()

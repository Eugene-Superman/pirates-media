"""
Floating loot (the game's chests, state.chests), built from code and rendered like a ship: from every direction for the
game's camera, one atlas a look (render_stages.py). Its looks (VARIANT_NAMES):
  gold   a sea chest bound in brass, its lid thrown open on a heap of gold coins: a chest with gold in it
  goods  two crates and a barrel of goods afloat, roped together: a chest with only goods
  lost   the same with a pole and an orange flag over them: a player's own cargo, lost where their ship went down
The game bobs and rocks them on the waves itself (client/scene/models/ChestSprites.ts), so each look is one pose.

Run in Blender: open chest.blend next to this file, Scripting tab -> Open -> build.py -> Run Script: it builds the look
named by the scene's "variant" property (gold by default). render_stages.py renders every look.

Axes and scale match the game: 1 Blender unit = 1 game unit, Z up, the waterline at Z = 0; the loot floats low, part of
it under the water (cut off at the surface when rendered).

Textures: scanned CC0 wood from Poly Haven (polyhaven.com) in blender-assets/textures/polyhaven/, downloaded there on
the first run; the rest are plain colours.
"""

import json
import math
import os
import urllib.request

import bmesh
import bpy
from mathutils import Matrix, Vector

VARIANT_NAMES = ("gold", "goods", "lost")
DAMAGE_STAGES = {0: {}}  # loot isn't damaged: one atlas a look, "intact"

# prettier-ignore
COLORS = {
    "chest": 0x7A4A22,
    "lid": 0x8C5A2C,
    "brass": 0xC99A3A,
    "iron": 0x34343A,
    "gold": 0xFFC23A,
    "inside": 0x3A2412,
    "crate": 0xA07A4A,
    "batten": 0x6E4F2E,
    "barrel": 0x8A6236,
    "rope": 0xC8B48A,
    "pole": 0x5E4126,
    "flag": 0xFF8A2A,
}
# World units, as the game's vector chest (models/chest3d.ts): a chest 8 long, 6 wide, its body 4.2 high
CHEST = dict(length=8.0, width=6.0, height=4.2, lid=1.8, sunk=1.4, open_deg=105)
# Each crate: x, y (game y: south), its turn (radians); and the barrel lying on its side
CRATE = 3.6
CRATES = ((-2.6, -1.2, 0.3), (2.4, 1.4, -0.4))
BARREL = dict(x=0.2, y=3.4, turn=0.9, length=4.0, radius=1.45)
CRATE_SUNK = 1.0  # of a crate under the water
MARKER = dict(height=9.0, flag=3.4, flag_height=2.2)


def base_dir():
    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()


def assets_root(path):
    """blender-assets itself: the parent of the "loot" folder this lives in"""
    path = os.path.abspath(path)
    while os.path.basename(path) != "loot":
        parent = os.path.dirname(path)
        if parent == path:
            return os.path.abspath(base_dir())
        path = parent
    return os.path.dirname(path)


PH_DIR = os.path.join(assets_root(base_dir()), "textures", "polyhaven")


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


def srgb(hex_color):
    return [((hex_color >> s) & 0xFF) / 255 for s in (16, 8, 0)]


def linear(hex_color):
    return [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb(hex_color)] + [1.0]


def relpath(path):
    try:
        return bpy.path.relpath(path)
    except ValueError:
        return path


POLYHAVEN_KINDS = {"diff": "Diffuse", "nor_gl": "nor_gl", "rough": "Rough"}


def download(asset):
    """Poly Haven's 1k maps of an asset into textures/polyhaven/, the first time they are needed"""
    paths = {kind: os.path.join(PH_DIR, f"{asset}_{kind}_1k.jpg") for kind in POLYHAVEN_KINDS}
    if all(os.path.exists(p) for p in paths.values()):
        return
    os.makedirs(PH_DIR, exist_ok=True)
    req = urllib.request.Request(f"https://api.polyhaven.com/files/{asset}", headers={"User-Agent": "blender-assets"})
    files = json.load(urllib.request.urlopen(req, timeout=60))
    for kind, key in POLYHAVEN_KINDS.items():
        if os.path.exists(paths[kind]) or key not in files:
            continue
        req = urllib.request.Request(files[key]["1k"]["jpg"]["url"], headers={"User-Agent": "blender-assets"})
        with urllib.request.urlopen(req, timeout=120) as r, open(paths[kind], "wb") as fh:
            fh.write(r.read())


def polyhaven(asset, kind):
    download(asset)
    path = os.path.join(PH_DIR, f"{asset}_{kind}_1k.jpg")
    if not os.path.exists(path):
        return None
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = "sRGB" if kind == "diff" else "Non-Color"
    img.filepath = relpath(path)
    return img


def new_material(name):
    old = bpy.data.materials.get(name)
    if old:
        bpy.data.materials.remove(old)
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    return m


def plain(name, color, rough=0.8, metal=0.0):
    m = new_material(name)
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = linear(color)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    m.diffuse_color = linear(color)
    return m


def wood(name, asset, color, tile=2.5, rough=0.8):
    """A colour over the grain of a scanned wood: its brightness, box-mapped from object coordinates, and its bumps"""
    m = new_material(name)
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    coords = nodes.new("ShaderNodeTexCoord").outputs["Object"]
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
    ramp.inputs["To Min"].default_value = 0.6
    ramp.inputs["To Max"].default_value = 1.25
    links.new(bw.outputs["Val"], ramp.inputs["Value"])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    mix.inputs[6].default_value = linear(color)
    links.new(ramp.outputs["Result"], mix.inputs[7])
    links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    nor = polyhaven(asset, "nor_gl")
    if nor is not None:
        ntex = nodes.new("ShaderNodeTexImage")
        ntex.image = nor
        ntex.projection = "BOX"
        ntex.projection_blend = 0.3
        links.new(mapping.outputs["Vector"], ntex.inputs["Vector"])
        nmap = nodes.new("ShaderNodeNormalMap")
        nmap.inputs["Strength"].default_value = 0.9
        links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    m.diffuse_color = linear(color)
    return m


def make_materials():
    return {
        "chest": wood("LootChest", "old_planks_02", COLORS["chest"]),
        "lid": wood("LootLid", "old_planks_02", COLORS["lid"]),
        "brass": plain("LootBrass", COLORS["brass"], rough=0.35, metal=0.9),
        "iron": plain("LootIron", COLORS["iron"], rough=0.5, metal=0.7),
        "gold": plain("LootGold", COLORS["gold"], rough=0.28, metal=0.85),
        "inside": plain("LootInside", COLORS["inside"], rough=0.9),
        "crate": wood("LootCrate", "weathered_planks", COLORS["crate"], tile=2.0),
        "batten": wood("LootBatten", "weathered_planks", COLORS["batten"], tile=2.0),
        "barrel": wood("LootBarrel", "wooden_barrel", COLORS["barrel"], tile=3.0),
        "rope": plain("LootRope", COLORS["rope"], rough=1.0),
        "pole": wood("LootPole", "old_planks_02", COLORS["pole"], tile=1.5),
        "flag": plain("LootFlag", COLORS["flag"], rough=0.9),
    }


MATERIAL_ORDER = ("chest", "lid", "brass", "iron", "gold", "inside", "crate", "batten", "barrel", "rope", "pole", "flag")


def mat(name):
    return MATERIAL_ORDER.index(name)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def box(bm, center, size, m, matrix=Matrix()):
    """A box of `size` (x, y, z) around `center`, then moved by `matrix`"""
    made = bmesh.ops.create_cube(bm, size=1.0)["verts"]
    for v in made:
        v.co = matrix @ Vector((center[0] + v.co.x * size[0], center[1] + v.co.y * size[1], center[2] + v.co.z * size[2]))
    for f in {f for v in made for f in v.link_faces}:
        f.material_index = m
    return made


def cylinder(bm, a, b, r, m, segs=16, r2=None):
    """A closed cylinder (a cone with r2) from a to b"""
    a, b = Vector(a), Vector(b)
    d = b - a
    rot = d.normalized().to_track_quat("Z", "Y").to_matrix().to_4x4()
    made = bmesh.ops.create_cone(
        bm, cap_ends=True, segments=segs, radius1=r, radius2=r if r2 is None else r2, depth=d.length,
        matrix=Matrix.Translation((a + b) / 2) @ rot,
    )["verts"]
    for f in {f for v in made for f in v.link_faces}:
        f.material_index = m
        f.smooth = True


def ball(bm, center, r, m, segs=10, squash=1.0):
    made = bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=max(4, segs // 2), radius=r)["verts"]
    for v in made:
        v.co = Vector((center[0] + v.co.x, center[1] + v.co.y, center[2] + v.co.z * squash))
    for f in {f for v in made for f in v.link_faces}:
        f.material_index = m
        f.smooth = True


def half_cylinder(bm, length, radius, height, z, m, matrix=Matrix(), segs=14):
    """A chest's domed lid: half a cylinder along x, `radius` wide, `height` tall, its flat side down at `z`"""
    rings = []
    for x in (-length / 2, length / 2):
        ring = []
        for k in range(segs + 1):
            a = math.pi * k / segs
            ring.append(bm.verts.new(matrix @ Vector((x, radius * math.cos(a), z + height * math.sin(a)))))
        rings.append(ring)
    faces = []
    for k in range(segs):
        faces.append(bm.faces.new((rings[0][k], rings[0][k + 1], rings[1][k + 1], rings[1][k])))
    faces.append(bm.faces.new(list(reversed(rings[0]))))
    faces.append(bm.faces.new(rings[1]))
    faces.append(bm.faces.new((rings[0][0], rings[1][0], rings[1][-1], rings[0][-1])))
    for f in faces:
        f.material_index = m
        f.smooth = False
    bmesh.ops.recalc_face_normals(bm, faces=faces)


def gold_chest(bm):
    c = CHEST
    L, W, H = c["length"], c["width"], c["height"]
    bottom = -c["sunk"]
    top = bottom + H
    box(bm, (0, 0, bottom + H / 2), (L, W, H), mat("chest"))
    # The inside, a little lower than the rim: the heap of gold sits in it
    box(bm, (0, 0, top - 0.25), (L - 0.6, W - 0.6, 0.6), mat("inside"))
    # Brass bands round the body and corner plates
    for x in (-L * 0.3, L * 0.3):
        box(bm, (x, 0, bottom + H / 2), (0.55, W + 0.14, H + 0.06), mat("brass"))
    for x in (-L / 2, L / 2):
        for y in (-W / 2, W / 2):
            box(bm, (x, y, top - 0.5), (0.5, 0.5, 1.0), mat("brass"))
    # The lock on the front, under the lid
    box(bm, (0, -W / 2 - 0.08, top - 0.9), (1.1, 0.16, 1.3), mat("brass"))
    box(bm, (0, -W / 2 - 0.17, top - 1.0), (0.18, 0.04, 0.45), mat("iron"))
    # Rivets along the bands
    for x in (-L * 0.3, L * 0.3):
        for z in (bottom + 1.6, bottom + 2.6, top - 0.3):
            for y in (-W / 2 - 0.08, W / 2 + 0.08):
                ball(bm, (x, y, z), 0.12, mat("iron"), segs=6)

    # The heap of gold: a mound of coins rising out of the chest, coins lying on it
    heap = bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=10, radius=1.0)["verts"]
    for v in heap:
        v.co = Vector((v.co.x * (L / 2 - 0.5), v.co.y * (W / 2 - 0.5), top - 0.2 + max(v.co.z, 0) * 1.1))
    for f in {f for v in heap for f in v.link_faces}:
        f.material_index = mat("gold")
        f.smooth = True
    coins = [(-2.4, 0.9, 0.6, 0.4), (-1.0, -1.5, 0.75, -0.3), (0.6, 1.4, 0.8, 0.5), (1.9, -0.6, 0.55, 0.2), (-0.2, 0.2, 1.05, -0.5),
             (2.8, 1.3, 0.3, 0.6), (-3.0, -1.1, 0.25, -0.4), (1.2, -1.9, 0.45, 0.3)]
    for x, y, dz, tilt in coins:
        axis = Vector((math.sin(tilt), 0.3 * math.cos(tilt * 3), 1)).normalized()
        cylinder(bm, Vector((x, y, top + dz)) - axis * 0.06, Vector((x, y, top + dz)) + axis * 0.06, 0.42, mat("gold"), segs=12)
    # A few coins spilt over the rim
    for x, y in ((3.6, -2.9), (-3.7, 2.8)):
        cylinder(bm, (x, y, top - 0.05), (x, y, top + 0.07), 0.42, mat("gold"), segs=12)

    # The lid thrown open over the back, hinged along it
    hinge = Matrix.Translation((0, W / 2, top)) @ Matrix.Rotation(-math.radians(c["open_deg"]), 4, "X") @ Matrix.Translation((0, -W / 2, 0))
    half_cylinder(bm, L, W / 2, c["lid"], 0, mat("lid"), hinge)
    for x in (-L * 0.3, L * 0.3):
        half_cylinder(bm, 0.55, W / 2 + 0.07, c["lid"] + 0.07, -0.01, mat("brass"), hinge @ Matrix.Translation((x, 0, 0)), segs=10)


def crate(bm, x, y, turn):
    """A crate of goods: planks with darker battens along its edges, a rope round it"""
    m = Matrix.Translation((x, -y, 0)) @ Matrix.Rotation(turn, 4, "Z")
    s = CRATE
    zc = -CRATE_SUNK + s / 2
    box(bm, (0, 0, zc), (s, s, s), mat("crate"), m)
    t = 0.32
    for dx in (-1, 1):
        for dy in (-1, 1):
            box(bm, (dx * (s / 2 - t / 2 + 0.04), dy * (s / 2 - t / 2 + 0.04), zc), (t, t, s + 0.06), mat("batten"), m)
    for dz in (-1, 1):
        for d in (-1, 1):
            box(bm, (d * (s / 2 - t / 2 + 0.04), 0, zc + dz * (s / 2 - t / 2 + 0.04)), (t, s + 0.06, t), mat("batten"), m)
            box(bm, (0, d * (s / 2 - t / 2 + 0.04), zc + dz * (s / 2 - t / 2 + 0.04)), (s + 0.06, t, t), mat("batten"), m)
    # A rope over the top
    box(bm, (0, 0, zc + s / 2 + 0.08), (s + 0.1, 0.22, 0.16), mat("rope"), m)
    box(bm, (0.9, 0, zc), (0.2, s + 0.14, s + 0.14), mat("rope"), m)


def barrel(bm):
    b = BARREL
    m = Matrix.Translation((b["x"], -b["y"], b["radius"] - CRATE_SUNK - 0.4)) @ Matrix.Rotation(b["turn"], 4, "Z")
    half = b["length"] / 2
    # Bellied: a little wider in the middle
    for k in range(4):
        x0 = -half + b["length"] * k / 4
        x1 = x0 + b["length"] / 4
        r0 = b["radius"] * (0.88 + 0.12 * math.sin(math.pi * k / 4))
        r1 = b["radius"] * (0.88 + 0.12 * math.sin(math.pi * (k + 1) / 4))
        cylinder(bm, m @ Vector((x0, 0, 0)), m @ Vector((x1, 0, 0)), r0, mat("barrel"), segs=18, r2=r1)
    for x in (-half * 0.75, -half * 0.25, half * 0.25, half * 0.75):
        r = b["radius"] * (0.9 + 0.1 * math.cos(x / half * math.pi / 2)) + 0.05
        cylinder(bm, m @ Vector((x - 0.12, 0, 0)), m @ Vector((x + 0.12, 0, 0)), r, mat("iron"), segs=18)


def goods(bm):
    for x, y, turn in CRATES:
        crate(bm, x, y, turn)
    barrel(bm)
    # The rope that ties them together, from crate to crate and to the barrel
    points = [Vector((x, -y, 1.0)) for x, y, _ in CRATES] + [Vector((BARREL["x"], -BARREL["y"], 0.9))]
    for a, b in zip(points, points[1:] + points[:1]):
        cylinder(bm, a, b, 0.11, mat("rope"), segs=6)


def marker(bm):
    """A pole on the middle crate with an orange flag: whose cargo it is, seen from afar"""
    x, y, _ = CRATES[0]
    base = Vector((x, -y, -CRATE_SUNK + CRATE))
    tip = base + Vector((0, 0, MARKER["height"]))
    cylinder(bm, base, tip, 0.16, mat("pole"), segs=8)
    ball(bm, tip, 0.28, mat("brass"), segs=8)
    # The flag, a little wavy, flying from the top of the pole
    cols, rows = 8, 3
    verts = []
    for j in range(rows + 1):
        row = []
        for i in range(cols + 1):
            u = i / cols
            v = j / rows
            px = -u * MARKER["flag"]
            py = 0.35 * math.sin(u * math.pi * 1.6) * u
            pz = MARKER["height"] - 0.3 - v * MARKER["flag_height"]
            row.append(bm.verts.new(base + Vector((px, py, pz))))
        verts.append(row)
    for j in range(rows):
        for i in range(cols):
            f = bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            f.material_index = mat("flag")
            f.smooth = True


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
    for block in (bpy.data.materials, bpy.data.meshes, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def build(damage=0, variant=None):
    """variant: one of VARIANT_NAMES; by default the scene's "variant" property, or the first"""
    scene = bpy.context.scene
    if variant is None:
        variant = scene.get("variant", VARIANT_NAMES[0])
    variant = variant if variant in VARIANT_NAMES else VARIANT_NAMES[0]
    scene["variant"] = variant
    scene["damage"] = 0
    clear_previous()
    coll = bpy.data.collections.new("Ship")
    scene.collection.children.link(coll)
    mats = make_materials()

    # render_sprites.py turns the object named "Ship": the loot turns with it
    root = bpy.data.objects.new("Ship", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 4
    coll.objects.link(root)

    bm = bmesh.new()
    if variant == "gold":
        gold_chest(bm)
    else:
        goods(bm)
        if variant == "lost":
            marker(bm)
    bm.normal_update()
    mesh = bpy.data.meshes.new(f"Loot.{variant}")
    bm.to_mesh(mesh)
    bm.free()
    for key in MATERIAL_ORDER:
        mesh.materials.append(mats[key])
    obj = bpy.data.objects.new(f"Loot.{variant}", mesh)
    coll.objects.link(obj)
    obj.parent = root
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = 0.08
    bevel.segments = 2
    bevel.limit_method = "ANGLE"
    return root


if __name__ == "__main__":
    build()

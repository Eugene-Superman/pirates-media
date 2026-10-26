"""
The harbour view: the picture the game shows in a window while the player's ship is in port. Saltwind Harbour seen
from its roadstead late in the afternoon, ships in the bay; and a medallion for each of the port's buildings, which the
game puts over the picture where the building stands (the tavern, the market, the shipyard...).

Run in a background Blender after build_port.py, whose scene (port/port.blend) it opens and changes only in memory:
    blender --background --python port/build_harbour.py
(about 3 minutes on a GTX 1060). HARBOUR_PREVIEW=1 renders a small, quick picture with the buildings' spots marked
into frames/harbour/preview.png (and the medallions into frames/harbour/medallions.png) and writes nothing into the
game; HARBOUR_ONLY=picture or HARBOUR_ONLY=medallions makes one of the two.

What it makes, in canvas/public/sprites/port/:
  harbour.webp     the picture
  medallions.webp  the buildings' medallions in a row, each MEDALLION pixels square
  harbour.json     the picture's size; for each building where on the picture it stands (shares of the picture's width
                   and height, from the top left corner) and which medallion is its own

The sky (an HDRI), the ships in the bay and the things on the medallions are from Poly Haven (polyhaven.com, CC0),
downloaded into textures/polyhaven/ and models/polyhaven/ on the first run.
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
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Matrix, Vector

PREVIEW = bool(os.environ.get("HARBOUR_PREVIEW"))
ONLY = os.environ.get("HARBOUR_ONLY", "")
WIDTH, HEIGHT = (960, 600) if PREVIEW else (2048, 1280)  # pixels: the picture, 16:10
SAMPLES = int(os.environ.get("HARBOUR_SAMPLES") or (24 if PREVIEW else 192))
MEDALLION = 256  # pixels a side of a medallion
MEDALLION_SAMPLES = 24 if PREVIEW else 96

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()
for _text in bpy.data.texts:
    if _text.filepath and os.path.basename(_text.filepath) == "build_harbour.py":
        SCRIPT_DIR = os.path.dirname(bpy.path.abspath(_text.filepath))
BLEND = os.path.join(SCRIPT_DIR, "port.blend")
if os.path.normcase(os.path.abspath(bpy.data.filepath or ".")) != os.path.normcase(BLEND):
    bpy.ops.wm.open_mainfile(filepath=BLEND)
sys.path.insert(0, SCRIPT_DIR)
import build_port as P  # noqa: E402  the port's geometry: its layout, the buildings' places, ground heights

ASSETS_DIR = os.path.dirname(SCRIPT_DIR)
MODELS_DIR = os.path.join(ASSETS_DIR, "models", "polyhaven")
FRAMES_DIR = os.path.join(ASSETS_DIR, "frames", "harbour")
SPRITES_DIR = P.SPRITES_DIR

# The sky: a Poly Haven HDRI without ground, turned so its sun shines on the town from behind the camera's left
SKY = "evening_road_01_puresky"
SKY_RES = "4k"
SKY_STRENGTH = float(os.environ.get("HARBOUR_SKY") or 0.7)
# Degrees: the sun's bearing from the camera's view, to the left (0 = straight ahead, negative to the right)
SUN_FROM = float(os.environ.get("HARBOUR_SUN") or -150.0)
# Degrees above the horizon: higher than the HDRI's own sun, so the town isn't in the hill's shadow
SUN_ELEVATION = float(os.environ.get("HARBOUR_SUN_EL") or 20.0)
SUN_STRENGTH = float(os.environ.get("HARBOUR_SUN_STRENGTH") or 5.5)
SUN_COLOR = tuple(map(float, (os.environ.get("HARBOUR_SUN_COLOR") or "1.0,0.78,0.55").split(",")))  # late afternoon
EXPOSURE = float(os.environ.get("HARBOUR_EXPOSURE") or 0.0)
# The picture's grade, after the render: more colour, a little more contrast, the corners darker (0 for none)
GRADE = dict(saturation=1.17, contrast=1.06, vignette=0.3)
if os.environ.get("HARBOUR_GRADE"):
    GRADE = dict(zip(("saturation", "contrast", "vignette"), map(float, os.environ["HARBOUR_GRADE"].split(","))))

# The camera, in the harbour's frame (u across the bay, v up from the sea to the town, z up; build_port.py): high
# over the roadstead off the harbour's mouth, looking down across the bay at the town
_cam = os.environ.get("HARBOUR_CAM")  # "u,v,z;u,v,z;lens" to try another view
CAMERA = dict(at=(70.0, -480.0, 78.0), look=(5.0, -150.0, 16.0), lens=32.0)
if _cam:
    a, b, c = _cam.split(";")
    CAMERA = dict(at=tuple(map(float, a.split(","))), look=tuple(map(float, b.split(","))), lens=float(c))

# Ships in the harbour: a Poly Haven model, where (harbour frame), which way its bow points (degrees, from u towards v)
# and the model's own bow axis. Kept clear of the buildings' spots: their masts would stand through the medallions
SHIPS = [
    dict(asset="dutch_ship_large_02", res="2k", u=-30.0, v=-330.0, heading=165.0, bow="y"),
    dict(asset="dutch_ship_large_01", res="2k", u=-45.0, v=-225.0, heading=202.0, bow="x"),
    dict(asset="dutch_ship_medium", res="2k", u=90.0, v=-255.0, heading=-60.0, bow="x"),
]
SHIP_SCALE = 1.4  # the models are life-size; the game's ships are bigger beside the port's houses than that

# The sea
SEA_COLOR = (0.62, 0.86, 0.84)  # what the water lets through (linear)
DEEP_COLOR = (0.01, 0.075, 0.1)  # the sea floor far down: the terrain's fades into it, and the floor beyond its shelf
DEEP = -16.0  # world units: that floor
MURK_DEPTH = 2.2  # world units: how deep the sea floor is seen through the water before it is the deep's colour

# The buildings the game opens a window for: (u, v, z) in the harbour's frame where each one's medallion is put, over
# its roof. The ids are the game's (BuildingId in client/hud/HarbourView.ts)
BUILDING_IDS = ("tavern", "market", "workshop", "shipyard", "arsenal", "guild", "auction")


def buildings():
    H = P.H
    spots = {}
    for name, share in (("tavern", 0.37), ("workshop", 0.63)):
        p, _ = P.along_line(H["quay"], H["quay_inland"], share, P.FIRST_ROW - 0.5)
        spots[name] = (p[0], p[1], float(P.ground_z(p[0], p[1])[0]) + 12)
    spots["market"] = (P.SQUARE["u"], P.SQUARE["v"], float(P.ground_z(P.SQUARE["u"], P.SQUARE["v"])[0]) + 4)
    # The shipyard's slipway on the right beach (build_port.build_shore)
    cu, cv, n = P.coast_point(168, 1)
    mid = np.array([cu, cv]) - np.array([n[0], n[1]]) * 17
    spots["shipyard"] = (mid[0], mid[1], float(P.ground_z(mid[0], mid[1])[0]) + 5)
    # The bastion at the head of the short wall, with its cannons
    fx, fy = H["walls"][1]["line"][-1]
    spots["arsenal"] = (fx, fy, P.WALL_HEIGHT + 9)
    # The castle's keep
    spots["guild"] = (P.CASTLE["u"] + 6, P.CASTLE["v"] + 10, P.CASTLE_Z + 32)
    # A big house towards the left end of the second row
    p, _ = P.along_line(H["bay"], H["inland"], float(os.environ.get("HARBOUR_AUCTION") or 0.72), P.FIRST_ROW + P.ROW_STEP)
    spots["auction"] = (p[0], p[1], float(P.ground_z(p[0], p[1])[0]) + 10)
    return {k: tuple(float(c) for c in v) for k, v in spots.items()}


# What stands on each building's medallion: Poly Haven props, each turned (degrees about x, y, z) to show its shape
# A flat prop (face=True: a saw, a shield) is first turned to show its face, whatever way the model lies; `place` then
# moves it (x across, z up) and turns it in the medallion's plane (degrees), `size` scales it before the group is fitted
MEDALLIONS = {
    "tavern": [dict(asset="brass_goblets", rot=(8, 0, 20))],
    "market": [dict(asset="wooden_crate_01", rot=(10, 0, 30), place=(-0.22, 0.1, 0), size=0.9),
               dict(asset="wine_barrel_01", rot=(10, 0, -20), place=(0.32, -0.12, 0), size=0.72)],
    "workshop": [dict(asset="handsaw_wood", face=True, rot=(0, 0, 0), place=(0.14, -0.06, 40)),
                 dict(asset="wooden_hammer_01", face=True, rot=(0, 0, 0), place=(-0.2, 0.1, -45), size=0.85)],
    "shipyard": [dict(asset="dutch_ship_medium", res="2k", rot=(6, 0, -28))],
    "arsenal": [dict(asset="cannon_01", rot=(10, 0, -55))],
    "guild": [dict(asset="wooden_handle_saber", face=True, rot=(0, 0, 0), place=(0, 0.05, 45), size=1.1),
              dict(asset="kite_shield", face=True, rot=(0, 0, 0), place=(0, -0.05, 0), size=0.75)],
    "auction": [dict(asset="treasure_chest", rot=(12, 0, 30))],
}
GOLD = (1.0, 0.56, 0.16)
ENAMEL = (0.012, 0.03, 0.07)


def log(*args):
    print(*args, flush=True)


# ---------------------------------------------------------------------------
# Poly Haven
# ---------------------------------------------------------------------------


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "blender-assets"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def model_path(asset, res="1k"):
    """A Poly Haven model's glTF with its textures, downloaded into models/polyhaven/<asset>/<res>/ once"""
    folder = os.path.join(MODELS_DIR, asset, res)
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if name.endswith(".gltf"):
                return os.path.join(folder, name)
    entry = json.loads(fetch(f"https://api.polyhaven.com/files/{asset}"))["gltf"][res]["gltf"]
    os.makedirs(folder, exist_ok=True)
    for rel, inc in entry.get("include", {}).items():
        path = os.path.join(folder, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(fetch(inc["url"]))
    main = os.path.join(folder, os.path.basename(entry["url"]))
    with open(main, "wb") as fh:
        fh.write(fetch(entry["url"]))
    log("downloaded", asset, res)
    return main


def sky_path():
    path = os.path.join(P.TEX_DIR, f"{SKY}_{SKY_RES}.hdr")
    if not os.path.exists(path):
        url = json.loads(fetch(f"https://api.polyhaven.com/files/{SKY}"))["hdri"][SKY_RES]["hdr"]["url"]
        os.makedirs(P.TEX_DIR, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(fetch(url))
        log("downloaded", os.path.basename(path))
    return path


def import_model(asset, res="1k"):
    """The model's objects, parented to an empty at its origin"""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=model_path(asset, res))
    new = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new(f"{asset}_root", None)
    for o in new:
        for coll in list(o.users_collection):
            coll.objects.unlink(o)
        if o.parent is None:
            o.parent = root
    return root, new


def descendants(root):
    out = []
    stack = [root]
    while stack:
        o = stack.pop()
        out.append(o)
        stack.extend(o.children)
    return out


def link_tree(collection, root):
    for o in descendants(root):
        if o.name not in collection.objects:
            collection.objects.link(o)


# ---------------------------------------------------------------------------
# The scene: the port's own, seen in perspective, with a sky and a sea
# ---------------------------------------------------------------------------


def world_point(u, v, z):
    return P.TURN @ Vector((u, v, z))


def bearing(u, v):
    """A direction of the harbour's frame (u, v) as an angle in Blender's world, from +x towards +y"""
    d = P.TURN @ Vector((u, v, 0))
    return math.atan2(d.y, d.x)


def sun_in_sky(image):
    """Where the HDRI's sun is: its azimuth (from +x towards +y) and elevation, radians, as Cycles maps it"""
    w, h = image.size
    px = np.empty(w * h * 4, np.float32)
    image.pixels.foreach_get(px)
    lum = px.reshape(h, w, 4)[..., :3].sum(axis=2)
    row, col = np.unravel_index(int(np.argmax(lum)), lum.shape)
    u, v = (col + 0.5) / w, (row + 0.5) / h  # rows from the bottom
    return (0.5 - u) * 2 * math.pi, (v - 0.5) * math.pi


def setup_sky(scene, view_bearing):
    image = bpy.data.images.load(sky_path(), check_existing=True)
    sun_az, sun_el = sun_in_sky(image)
    want = view_bearing + math.radians(SUN_FROM)
    world = bpy.data.worlds.get("HarbourWorld") or bpy.data.worlds.new("HarbourWorld")
    world.use_nodes = True
    scene.world = world
    t = world.node_tree
    t.nodes.clear()
    coord = t.nodes.new("ShaderNodeTexCoord")
    mapping = t.nodes.new("ShaderNodeMapping")
    mapping.vector_type = "POINT"
    # The sky is looked up along the turned direction: turned by the sun's bearing in the picture less the bearing wanted
    mapping.inputs["Rotation"].default_value = (0, 0, sun_az - want)
    env = t.nodes.new("ShaderNodeTexEnvironment")
    env.image = image
    bg = t.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = SKY_STRENGTH
    out = t.nodes.new("ShaderNodeOutputWorld")
    t.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    t.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    t.links.new(env.outputs["Color"], bg.inputs["Color"])
    t.links.new(bg.outputs["Background"], out.inputs["Surface"])
    # The sun lamp along the sky's sun (higher), for its sharp shadows
    sun = scene.objects.get("PortSun")
    el = math.radians(SUN_ELEVATION)
    toward = Vector((math.cos(el) * math.cos(want), math.cos(el) * math.sin(want), math.sin(el)))
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = toward.to_track_quat("Z", "Y")
    sun.data.energy = SUN_STRENGTH
    sun.data.color = SUN_COLOR
    sun.data.angle = math.radians(1.0)
    log(f"sky's sun at {math.degrees(sun_az):.0f} deg, {math.degrees(sun_el):.1f} deg up")


def plane(name, size, z, material):
    mesh = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    mesh.clear_geometry()
    h = size / 2
    mesh.from_pydata([(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z)], [], [(0, 1, 2, 3)])
    mesh.materials.clear()
    mesh.materials.append(material)
    obj = bpy.data.objects.get(name) or bpy.data.objects.new(name, mesh)
    return obj


def sea_material():
    mat, n = P.new_material("harbour_sea")
    geo = n.add("ShaderNodeNewGeometry")
    # Small waves: stretched noise in two sizes, as bumps (the water stays flat: the ships and walls stand in it)
    scale = n.add("ShaderNodeVectorMath", Vector=geo.outputs["Position"])
    scale.operation = "MULTIPLY"
    scale.inputs[1].default_value = (1.0, 2.6, 1.0)
    big = n.add("ShaderNodeTexNoise", Vector=scale.outputs[0])
    big.inputs["Scale"].default_value = 0.09
    big.inputs["Detail"].default_value = 6
    small = n.add("ShaderNodeTexNoise", Vector=geo.outputs["Position"])
    small.inputs["Scale"].default_value = 0.6
    small.inputs["Detail"].default_value = 4
    height = n.math("ADD", big.outputs["Fac"], n.math("MULTIPLY", small.outputs["Fac"], 0.35))
    bump = n.add("ShaderNodeBump", Height=height)
    bump.inputs["Strength"].default_value = 0.22
    bump.inputs["Distance"].default_value = 0.4
    bsdf = n.add("ShaderNodeBsdfPrincipled", **{"Base Color": SEA_COLOR, "Normal": bump.outputs["Normal"]})
    bsdf.inputs["Roughness"].default_value = 0.03
    bsdf.inputs["IOR"].default_value = 1.333
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    out = n.add("ShaderNodeOutputMaterial")
    n.link(bsdf.outputs[0], out.inputs["Surface"])
    return mat


def setup_sea(scene):
    old = scene.objects.get("PortWater")
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    sea = plane("HarbourSea", 60000, 0.0, sea_material())
    # Light passes it as if it weren't there: the sea floor under it is lit by the sun (no caustics to bring it)
    sea.visible_shadow = False
    P.link(scene, sea)
    floor = plane("HarbourSeaFloor", 60000, DEEP, deep_material())
    P.link(scene, floor)


def deep_material():
    """The deep sea's floor: its colour, unlit, as the terrain's floor where it is deep"""
    mat, n = P.new_material("harbour_deep")
    glow = n.add("ShaderNodeEmission", Color=DEEP_COLOR)
    out = n.add("ShaderNodeOutputMaterial")
    n.link(glow.outputs[0], out.inputs["Surface"])
    return mat


def seabed_lit():
    """The terrain's sea floor was painted for the game's picture, fading out into the game's sea; here a real sea lies
    over it, so the terrain is solid. The floor stays unlit: lit, the walls' and ships' shadows would lie on it through
    the clear water as hard dark bands"""
    mat = bpy.data.materials["port_terrain"]
    t = mat.node_tree
    out = next(nd for nd in t.nodes if nd.type == "OUTPUT_MATERIAL")
    final = out.inputs["Surface"].links[0].from_node  # the mix with the transparent shader
    surface = final.inputs[2].links[0].from_socket
    t.links.new(surface, out.inputs["Surface"])
    for nd in list(t.nodes):
        # The floor fades into the murk by a couple of world units down: seen across the bay, the basin's deeper and
        # shallower parts would draw dark shapes through the water
        if nd.type == "MAP_RANGE" and abs(nd.inputs["From Max"].default_value - P.DEPTH * 0.8) < 1e-3:
            nd.inputs["From Max"].default_value = MURK_DEPTH
        # The murk the floor fades into with depth: the deep floor's colour, so the two meet without a seam
        if nd.type == "MIX" and getattr(nd, "data_type", "") == "RGBA" and not nd.inputs[7].is_linked:
            if abs(nd.inputs[7].default_value[2] - 0.24) < 1e-3:
                nd.inputs[7].default_value = (*DEEP_COLOR, 1)
        if nd.type == "EMISSION" and not nd.inputs["Color"].is_linked:
            nd.inputs["Strength"].default_value = 0.35  # the surf


def lit_windows():
    """About a third of the windows lit warm, picked at random by where they are"""
    mat = bpy.data.materials["port_window"]
    t = mat.node_tree
    bsdf = next(nd for nd in t.nodes if nd.type == "BSDF_PRINCIPLED")
    geo = t.nodes.new("ShaderNodeNewGeometry")
    snap = t.nodes.new("ShaderNodeVectorMath")
    snap.operation = "SNAP"
    snap.inputs[1].default_value = (2.5, 2.5, 2.5)
    t.links.new(geo.outputs["Position"], snap.inputs[0])
    noise = t.nodes.new("ShaderNodeTexWhiteNoise")
    noise.noise_dimensions = "3D"
    t.links.new(snap.outputs[0], noise.inputs["Vector"])
    on = t.nodes.new("ShaderNodeMath")
    on.operation = "GREATER_THAN"
    on.inputs[1].default_value = 0.66
    t.links.new(noise.outputs["Value"], on.inputs[0])
    strength = t.nodes.new("ShaderNodeMath")
    strength.operation = "MULTIPLY"
    strength.inputs[1].default_value = 7.0
    t.links.new(on.outputs[0], strength.inputs[0])
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.55, 0.2, 1)
    t.links.new(strength.outputs[0], bsdf.inputs["Emission Strength"])


def flag(scene, name, u, v, z, fly):
    """A red flag at the top of a flagstaff, waving, flying `fly` radians in Blender's world"""
    mesh = bpy.data.meshes.new(name)
    cols, rows, length, height = 14, 6, 9.0, 5.5
    verts, faces = [], []
    for i in range(cols + 1):
        a = i / cols
        for j in range(rows + 1):
            b = j / rows
            wave = math.sin(a * 5.2 + 0.6) * 0.7 * a
            verts.append((a * length, wave, -b * height + math.sin(a * 3.0) * 0.25 * a))
    for i in range(cols):
        for j in range(rows):
            k = i * (rows + 1) + j
            faces.append((k, k + rows + 1, k + rows + 2, k + 1))
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(P.flat("harbour_flag", (0.62, 0.035, 0.02), rough=0.85))
    for p in mesh.polygons:
        p.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    obj.location = world_point(u, v, z)
    obj.rotation_euler = (0, 0, fly)
    P.link(scene, obj)


def gulls(scene, cam):
    """A few gulls over the bay: two bent wings each, white, scattered in front of the camera"""
    mesh = bpy.data.meshes.new("HarbourGull")
    verts = [(0, 0, 0), (-0.9, 0.35, 0.35), (-1.9, 0.1, 0.05), (0.9, 0.35, 0.35), (1.9, 0.1, 0.05), (0, -0.5, 0.05),
             (0, 0.45, 0.08)]
    faces = [(0, 6, 1), (1, 6, 2), (0, 3, 6), (3, 4, 6), (0, 5, 6)]
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(P.flat("harbour_gull", (0.85, 0.85, 0.82), rough=0.7))
    rng = np.random.default_rng(11)
    m = cam.matrix_world
    for k in range(9):
        # In the camera's frame: across, up, how far
        x, y, d = rng.uniform(-0.55, 0.55), rng.uniform(0.12, 0.38), rng.uniform(120, 330)
        p = m @ Vector((x * d * 0.62, y * d * 0.42, -d))
        obj = bpy.data.objects.new(f"HarbourGull_{k}", mesh)
        obj.location = p
        obj.rotation_euler = (rng.uniform(-0.3, 0.3), rng.uniform(-0.4, 0.4), rng.uniform(0, 2 * math.pi))
        obj.scale = (1.2,) * 3
        P.link(scene, obj)


def place_ships(scene):
    for k, s in enumerate(SHIPS):
        root, _ = import_model(s["asset"], s["res"])
        root.name = f"HarbourShip_{k}"
        # The model's bow along +x (or +y), turned to the heading in Blender's world
        model_turn = 0.0 if s["bow"] == "x" else math.pi / 2
        heading = bearing(math.cos(math.radians(s["heading"])), math.sin(math.radians(s["heading"])))
        root.rotation_euler = (0, 0, heading - model_turn)
        root.location = world_point(s["u"], s["v"], 0.0)
        root.scale = (SHIP_SCALE,) * 3
        P.link(scene, root)
        link_tree(scene.collection, root)


def setup_camera(scene):
    cam = scene.camera
    cam.data.type = "PERSP"
    cam.data.lens = CAMERA["lens"]
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.sensor_width = 36
    cam.data.clip_start = 1
    cam.data.clip_end = 60000
    at, look = world_point(*CAMERA["at"]), world_point(*CAMERA["look"])
    cam.location = at
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = (look - at).to_track_quat("-Z", "Y")
    scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
    du, dv = CAMERA["look"][0] - CAMERA["at"][0], CAMERA["look"][1] - CAMERA["at"][1]
    return cam, bearing(du, dv)


def render_settings(scene, samples):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if P.has_gpu() else "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 8
    scene.cycles.transmission_bounces = 8
    scene.cycles.glossy_bounces = 4
    scene.cycles.transparent_max_bounces = 16
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    scene.cycles.filter_width = 1.5
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = os.environ.get("HARBOUR_VIEW") or "Standard"
    scene.view_settings.look = os.environ.get("HARBOUR_LOOK") or "None"
    scene.view_settings.exposure = EXPOSURE


def spots_on_picture(scene, cam):
    """Each building's spot as shares of the picture (from its top left), and whether something stands in front of it"""
    out = {}
    scene.view_layers[0].update()
    depsgraph = scene.view_layers[0].depsgraph
    for name, (u, v, z) in buildings().items():
        p = world_point(u, v, z)
        co = world_to_camera_view(scene, cam, p)
        ray = p - cam.location
        hit, where, *_ = scene.ray_cast(depsgraph, cam.location, ray.normalized(), distance=ray.length)
        hidden = hit and (where - p).length > 12
        out[name] = dict(at=[round(co.x, 4), round(1 - co.y, 4)], hidden=bool(hidden))
        if hidden or not (0.03 < co.x < 0.97 and 0.03 < co.y < 0.97):
            log(f"warning: {name} is {'hidden' if hidden else 'off the picture'} ({co.x:.2f}, {1 - co.y:.2f})")
    return out


def render_picture():
    scene = bpy.data.scenes["Port"]
    if bpy.context.window:
        bpy.context.window.scene = scene
    seabed_lit()
    lit_windows()
    cam, view = setup_camera(scene)
    setup_sky(scene, view)
    setup_sea(scene)
    place_ships(scene)
    # The flags: on the bastion's flagstaff and the keep's, flying away from the sun
    fly = view + math.radians(SUN_FROM) + math.pi + 0.5
    fx, fy = P.H["walls"][1]["line"][-1]
    flag(scene, "HarbourFlag_bastion", fx, fy, P.WALL_HEIGHT + 23, fly)
    flag(scene, "HarbourFlag_keep", P.CASTLE["u"] + 6, P.CASTLE["v"] + 10, P.CASTLE_Z + 47, fly)
    gulls(scene, cam)
    render_settings(scene, SAMPLES)
    spots = spots_on_picture(scene, cam)
    os.makedirs(FRAMES_DIR, exist_ok=True)
    s = scene.render.image_settings
    s.file_format = "PNG"
    s.color_mode = "RGB"
    s.color_depth = "8"
    path = os.path.join(FRAMES_DIR, f"{os.environ.get('HARBOUR_NAME') or 'preview'}.png" if PREVIEW else "harbour.png")
    scene.render.filepath = path
    t0 = time.time()
    bpy.ops.render.render(write_still=True, scene=scene.name)
    log(f"rendered {os.path.basename(path)} in {time.time() - t0:.0f} s")
    rgba = P.load_rgba(path)
    rgba[..., :3] = grade(rgba[..., :3])
    if PREVIEW:
        P.save_webp(path, rgba)
        mark_spots(path, spots)
    else:
        os.makedirs(SPRITES_DIR, exist_ok=True)
        save_webp(os.path.join(SPRITES_DIR, "harbour.webp"), rgba[..., :3], quality=86)
    return spots


def grade(rgb):
    """rgb: display values 0..1, row 0 at the top. More colour and contrast, and the corners darkened, to the eye"""
    lum = (rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
    rgb = lum + (rgb - lum) * GRADE["saturation"]
    rgb = 0.5 + (rgb - 0.5) * GRADE["contrast"]
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot((xx / w - 0.5) * 2, (yy / h - 0.5) * 2) / math.sqrt(2)
    rgb = rgb * (1 - GRADE["vignette"] * P.smoothstep(0.45, 1.0, r))[..., None]
    return np.clip(rgb, 0, 1).astype(np.float32)


def mark_spots(path, spots):
    """The preview with a ring at each building's spot"""
    rgba = P.load_rgba(path)
    h, w = rgba.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    for name, s in spots.items():
        x, y = s["at"][0] * w, s["at"][1] * h
        r = np.hypot(xx - x, yy - y)
        ring = (r > 7) & (r < 10)
        rgba[ring, :3] = (1.0, 0.1, 0.1) if s["hidden"] else (1.0, 0.85, 0.1)
    P.save_webp(path, rgba)


def save_webp(path, rgb, quality):
    """rgb: float 0..1 (display values), row 0 at the top"""
    h, w, _ = rgb.shape
    img = bpy.data.images.new("harbour_out", w, h, alpha=False)
    pixels = np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels.foreach_set(np.ascontiguousarray(pixels[::-1]).astype(np.float32).ravel())
    scene = bpy.context.scene
    settings = scene.render.image_settings
    old = (settings.file_format, settings.quality, settings.color_mode)
    settings.file_format = "WEBP"
    settings.quality = quality
    settings.color_mode = "RGB"
    old_view = (scene.view_settings.view_transform, scene.view_settings.look, scene.view_settings.exposure)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    img.save_render(path, scene=scene)
    scene.view_settings.view_transform, scene.view_settings.look, scene.view_settings.exposure = old_view
    settings.file_format, settings.quality, settings.color_mode = old
    bpy.data.images.remove(img)


# ---------------------------------------------------------------------------
# The medallions
# ---------------------------------------------------------------------------


def medallion_scene():
    scene = bpy.data.scenes.get("Medallions") or bpy.data.scenes.new("Medallions")
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    if bpy.context.window:
        bpy.context.window.scene = scene
    render_settings(scene, MEDALLION_SAMPLES)
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = MEDALLION
    scene.view_settings.exposure = 0.0
    # The sky's light, for the gold to shine in
    world = bpy.data.worlds.get("MedallionWorld") or bpy.data.worlds.new("MedallionWorld")
    world.use_nodes = True
    t = world.node_tree
    t.nodes.clear()
    env = t.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(sky_path(), check_existing=True)
    bg = t.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = 0.45
    out = t.nodes.new("ShaderNodeOutputWorld")
    t.links.new(env.outputs["Color"], bg.inputs["Color"])
    t.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = world
    cam = bpy.data.objects.new("MedallionCamera", bpy.data.cameras.new("MedallionCamera"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.32
    cam.location = (0, -20, 0)
    cam.rotation_euler = (math.pi / 2, 0, 0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    # A warm key light from the top left, a cool fill from the right, a rim from behind
    for name, loc, energy, color, size in (("Key", (-3, -5, 4), 900, (1.0, 0.86, 0.7), 3),
                                           ("Fill", (4, -4, -1), 250, (0.7, 0.8, 1.0), 4),
                                           ("Rim", (1, 4, 4), 600, (1.0, 0.9, 0.8), 2)):
        light = bpy.data.objects.new(f"Medallion{name}", bpy.data.lights.new(f"Medallion{name}", "AREA"))
        light.data.energy = energy
        light.data.color = color
        light.data.size = size
        light.location = loc
        light.rotation_mode = "QUATERNION"
        light.rotation_quaternion = (-Vector(loc)).to_track_quat("-Z", "Y")
        scene.collection.objects.link(light)
    # The medallion: an enamel disc in a gold rim
    gold = bpy.data.materials.get("medallion_gold") or P.flat("medallion_gold", GOLD, rough=0.3, metallic=1.0)
    enamel, n = P.new_material("medallion_enamel")
    geo = n.add("ShaderNodeTexCoord")
    grad = n.add("ShaderNodeTexGradient", Vector=geo.outputs["Object"])
    grad.gradient_type = "SPHERICAL"
    # Deep blue, a little lighter in the middle behind the prop; matt, so it doesn't mirror the sky
    color = n.mix(n.smooth(grad.outputs["Fac"], 0.0, 0.9), ENAMEL, (0.04, 0.09, 0.17))
    bsdf = n.shade(color, rough=0.55)
    bsdf.inputs["Specular IOR Level"].default_value = 0.15
    disc = cylinder("MedallionDisc", 1.0, 0.08, enamel)
    disc.location = (0, 0.25, 0)
    scene.collection.objects.link(disc)
    for name, major, minor, y in (("MedallionRim", 1.02, 0.085, 0.2), ("MedallionInner", 0.88, 0.022, 0.18)):
        rim = torus(name, major, minor, gold)
        rim.location = (0, y, 0)
        scene.collection.objects.link(rim)
    return scene


def cylinder(name, radius, depth, mat, segments=96):
    mesh = bpy.data.meshes.new(name)
    verts = []
    for k in range(segments):
        a = 2 * math.pi * k / segments
        for y in (-depth / 2, depth / 2):
            verts.append((radius * math.cos(a), y, radius * math.sin(a)))
    faces = [(2 * k, 2 * ((k + 1) % segments), 2 * ((k + 1) % segments) + 1, 2 * k + 1) for k in range(segments)]
    faces.append(tuple(2 * k for k in range(segments)))
    faces.append(tuple(2 * k + 1 for k in reversed(range(segments))))
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(mat)
    return bpy.data.objects.new(name, mesh)


def torus(name, major, minor, mat, segments=128, ring=16):
    mesh = bpy.data.meshes.new(name)
    verts, faces = [], []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        for j in range(ring):
            b = 2 * math.pi * j / ring
            r = major + minor * math.cos(b)
            verts.append((r * math.cos(a), minor * math.sin(b), r * math.sin(a)))
    for i in range(segments):
        for j in range(ring):
            a, b = i * ring + j, i * ring + (j + 1) % ring
            c, d = ((i + 1) % segments) * ring + (j + 1) % ring, ((i + 1) % segments) * ring + j
            faces.append((a, b, c, d))
    mesh.from_pydata(verts, [], faces)
    for p in mesh.polygons:
        p.use_smooth = True
    mesh.materials.append(mat)
    return bpy.data.objects.new(name, mesh)


def fit(scene, root, size):
    """Scales and moves a prop so its bounds, as the camera sees them (x across, z up), fit a circle `size` across"""
    scene.view_layers[0].update()
    pts = []
    for o in descendants(root):
        if o.type == "MESH":
            pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo + hi) / 2
    # The bounds' corners are mostly empty: the circle need not hold all of them
    extent = max(hi.x - lo.x, hi.z - lo.z, 0.82 * math.hypot(hi.x - lo.x, hi.z - lo.z))
    k = size / extent
    root.scale = root.scale * k
    root.location = (root.location - centre) * k


def face_camera(scene, root):
    """The turn that shows a flat prop's face to the medallion's camera (looking along +y): its thinnest side along y"""
    scene.view_layers[0].update()
    pts = [o.matrix_world @ Vector(c) for o in descendants(root) if o.type == "MESH" for c in o.bound_box]
    size = [max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3)]
    thin = size.index(min(size))
    if thin == 0:
        return Matrix.Rotation(-math.pi / 2, 4, "Z")
    if thin == 2:
        return Matrix.Rotation(math.pi / 2, 4, "X")
    return Matrix.Identity(4)


def render_medallions():
    scene = medallion_scene()
    tiles = []
    for index, name in enumerate(BUILDING_IDS):
        group = []
        for prop in MEDALLIONS[name]:
            root, _ = import_model(prop["asset"], prop.get("res", "1k"))
            scene.collection.objects.link(root)
            link_tree(scene.collection, root)
            turn = Euler([math.radians(a) for a in prop["rot"]], "XYZ").to_matrix().to_4x4()
            if prop.get("face"):
                turn = turn @ face_camera(scene, root)
            root.matrix_world = turn
            fit(scene, root, 1.55 * prop.get("size", 1.0))
            if "place" in prop:
                # Moved and turned in the medallion's plane (x across, z up; turned about the camera's view)
                x, z, turn = prop["place"]
                scene.view_layers[0].update()
                root.matrix_world = Matrix.Translation((x, 0, z)) @ Matrix.Rotation(math.radians(turn), 4, "Y") @ \
                    root.matrix_world
            group.append(root)
        if len(group) > 1:
            # Several props together: fitted as one
            holder = bpy.data.objects.new(f"Medallion_{name}", None)
            scene.collection.objects.link(holder)
            scene.view_layers[0].update()
            for g in group:
                world = g.matrix_world.copy()
                g.parent = holder
                g.matrix_world = world
            fit(scene, holder, 1.55)
            group = [holder]
        scene.view_layers[0].update()
        path = os.path.join(FRAMES_DIR, f"medallion_{name}.png")
        s = scene.render.image_settings
        s.file_format, s.color_mode, s.color_depth = "PNG", "RGBA", "8"
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True, scene=scene.name)
        tiles.append(P.load_rgba(path))
        for g in group:
            for o in descendants(g):
                bpy.data.objects.remove(o, do_unlink=True)
        log(f"medallion {name}")
    strip = np.concatenate(tiles, axis=1)
    if PREVIEW:
        P.save_webp(os.path.join(FRAMES_DIR, "medallions.png"), strip)
    else:
        P.save_webp(os.path.join(SPRITES_DIR, "medallions.webp"), strip, quality=90)


def main():
    try:
        t0 = time.time()
        spots = None
        if ONLY != "medallions":
            spots = render_picture()
        if ONLY != "picture":
            render_medallions()
        if not PREVIEW and spots is not None:
            meta = dict(picture=dict(file="harbour.webp", w=WIDTH, h=HEIGHT),
                        medallions=dict(file="medallions.webp", size=MEDALLION),
                        buildings={name: dict(at=spots[name]["at"], medallion=i) for i, name in enumerate(BUILDING_IDS)})
            with open(os.path.join(SPRITES_DIR, "harbour.json"), "w", newline="\n") as fh:
                json.dump(meta, fh, indent=1)
                fh.write("\n")
        if spots:
            log(json.dumps(spots))
        log(f"HARBOUR DONE in {time.time() - t0:.0f} s")
    except Exception:
        log("ERROR\n" + traceback.format_exc())
        if bpy.app.background:
            sys.exit(1)


main()

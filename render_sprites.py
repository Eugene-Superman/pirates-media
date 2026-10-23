"""
Renders the ship in the open .blend from every direction for the game's isometric camera and packs an atlas for Pixi.

Run: open a ship's .blend (ships/<line>/<ship>/), Scripting tab -> Open -> render_sprites.py -> Run Script.
From a terminal: blender ships/starter/sloop/sloop.blend --background --python render_sprites.py
To render every damage stage of the ship, run render_stages.py instead.

Where things go is worked out from where the .blend lies, so a new ship needs no settings:
  ships/starter/sloop/sloop.blend, damage stage "minor" (the scene's custom property "damage" = 1)
  -> atlas  ../canvas/public/sprites/ships/starter/sloop/minor.webp + minor.json
  -> frames frames/starter/sloop/minor/ (untrimmed, kept for inspection)

Camera, light and scale are taken from the game:
  src/client/scene/SceneView.ts, CAMERA: pitch 30, yaw 45, no perspective, zoom 1.4
  src/client/render/Painter3D.ts: LIGHT = (-0.6, 0.1, 0.8), in game coordinates where y points south
"""

import json
import math
import os

import bpy
import numpy as np
from mathutils import Vector

DIRECTIONS = 64
PX_PER_UNIT = 2.8  # game zoom 1.4 x2, so the ship stays sharp on retina screens
CAM_PITCH = 30.0
CAM_YAW = 45.0
LIGHT_GAME = (-0.6, 0.1, 0.8)
SUN_STRENGTH = 2.0
SUN_ANGLE = 1.2  # degrees, shadow softness (less = sharper, more cartoonish)
AMBIENT = 0.72  # sky light strength (more = lighter shadows on the ship)
SHADOW_OPACITY = 0.55  # how strong the baked shadow is (1 = as rendered)
SHADOW_CUTOFF = 0.08  # a shadow weaker than this is treated as noise
SAMPLES = 48
MARGIN = 3  # pixels of spare room around a frame
PADDING = 2  # pixels between frames in the atlas
# Atlas names, by the scene's "damage" property 0..4: DAMAGE_STAGES in the game's src/game/ships/damage.ts
STAGE_NAMES = ("intact", "minor", "heavy", "burning", "sinking")
GAME_DIR = "canvas"  # the game repository, next to blender-assets


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
            raise RuntimeError(f"{ship_dir} is not inside blender-assets/ships/<line>/<ship>/")
        path = parent
    return os.path.dirname(path)


SHIP_DIR = base_dir()
ASSETS_DIR = assets_root(SHIP_DIR)
SHIP_PATH = os.path.relpath(SHIP_DIR, os.path.join(ASSETS_DIR, "ships"))  # e.g. starter/sloop
ATLAS_DIR = os.environ.get("SHIP_ATLAS_DIR") or os.path.normpath(
    os.path.join(ASSETS_DIR, "..", GAME_DIR, "public", "sprites", "ships", SHIP_PATH)
)
NAME = ""
FRAMES_DIR = ""


def set_stage(index):
    """Which damage stage is rendered: picks the atlas name and the frames folder"""
    global NAME, FRAMES_DIR
    NAME = STAGE_NAMES[index]
    FRAMES_DIR = os.path.join(ASSETS_DIR, "frames", SHIP_PATH, NAME)


set_stage(int(bpy.context.scene.get("damage", 0)))


# ---------------------------------------------------------------------------
# Camera and light
# ---------------------------------------------------------------------------


def camera_axes():
    """Camera directions in Blender's world (Blender y = north, i.e. -y of the game)"""
    yaw, pitch = math.radians(CAM_YAW), math.radians(CAM_PITCH)
    fwd = Vector((math.sin(yaw), math.cos(yaw), 0))
    right = Vector((math.cos(yaw), -math.sin(yaw), 0))
    view = (fwd * math.cos(pitch) + Vector((0, 0, -math.sin(pitch)))).normalized()
    up = (fwd * math.sin(pitch) + Vector((0, 0, math.cos(pitch)))).normalized()
    return right, up, view


def light_dir():
    x, y, z = LIGHT_GAME
    return Vector((x, -y, z)).normalized()


def ship_root():
    return bpy.data.objects["Ship"]


def ship_points():
    """All ship vertices in ship coordinates"""
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for obj in bpy.data.collections["Ship"].all_objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(dg)
        mesh = ev.to_mesh()
        co = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        mw = np.array(obj.matrix_world)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        ev.to_mesh_clear()
        pts.append(co)
    return np.concatenate(pts)


def frame_bounds():
    """Screen bounds (in world units) over all directions, shadow included"""
    right, up, _ = camera_axes()
    L = light_dir()
    pts = ship_points()
    above = pts[pts[:, 2] > 0]
    shadow = above - np.outer(above[:, 2] / L.z, np.array(L))
    pts = np.concatenate([pts[pts[:, 2] > -0.5], shadow])
    lo = np.array([np.inf, np.inf])
    hi = -lo
    for i in range(DIRECTIONS):
        a = -2 * math.pi * i / DIRECTIONS
        c, s = math.cos(a), math.sin(a)
        rx = pts[:, 0] * c - pts[:, 1] * s
        ry = pts[:, 0] * s + pts[:, 1] * c
        sx = rx * right.x + ry * right.y + pts[:, 2] * right.z
        sy = rx * up.x + ry * up.y + pts[:, 2] * up.z
        lo = np.minimum(lo, [sx.min(), sy.min()])
        hi = np.maximum(hi, [sx.max(), sy.max()])
    return lo, hi


def setup_scene():
    scene = bpy.context.scene
    right, up, view = camera_axes()

    lo, hi = frame_bounds()
    width = int(math.ceil((hi[0] - lo[0]) * PX_PER_UNIT)) + 2 * MARGIN
    height = int(math.ceil((hi[1] - lo[1]) * PX_PER_UNIT)) + 2 * MARGIN
    anchor_x = -lo[0] * PX_PER_UNIT + MARGIN
    anchor_y = hi[1] * PX_PER_UNIT + MARGIN
    # Frame center relative to the ship's origin, in world units
    cx = (width / 2 - anchor_x) / PX_PER_UNIT
    cy = (anchor_y - height / 2) / PX_PER_UNIT

    cam = bpy.data.objects.get("SpriteCamera")
    if cam is None:
        cam = bpy.data.objects.new("SpriteCamera", bpy.data.cameras.new("SpriteCamera"))
        scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(width, height) / PX_PER_UNIT
    cam.data.sensor_fit = "AUTO"
    cam.data.clip_start = 1
    cam.data.clip_end = 1000
    cam.matrix_world = _matrix_from_axes(right, up, -view, right * cx + up * cy - view * 300)
    scene.camera = cam

    sun = bpy.data.objects.get("Sun")
    if sun is None:
        sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
        scene.collection.objects.link(sun)
    sun.data.energy = SUN_STRENGTH
    sun.data.angle = math.radians(SUN_ANGLE)
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = light_dir().to_track_quat("Z", "Y")
    sun.location = light_dir() * 100

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.82, 0.9, 1.0, 1)
    bg.inputs["Strength"].default_value = AMBIENT

    water = bpy.data.objects.get("ShadowCatcher")
    if water is None:
        mesh = bpy.data.meshes.new("ShadowCatcher")
        s = 400
        mesh.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
        water = bpy.data.objects.new("ShadowCatcher", mesh)
        scene.collection.objects.link(water)
    water.is_shadow_catcher = True

    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if _has_gpu() else "CPU"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.cycles.film_exposure = 1.0
    scene.cycles.filter_width = 1.2
    scene.render.film_transparent = True
    scene.render.use_persistent_data = True  # don't rebuild the scene between frames
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1

    return {"width": width, "height": height, "anchor": (anchor_x, anchor_y)}


def _matrix_from_axes(x, y, z, loc):
    from mathutils import Matrix

    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = loc
    return m


def _has_gpu():
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


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def frame_path(i):
    return os.path.join(FRAMES_DIR, f"ship_{i:02d}.png")


def render_frames(only=None):
    os.makedirs(FRAMES_DIR, exist_ok=True)
    scene = bpy.context.scene
    root = ship_root()
    for i in range(DIRECTIONS):
        if only is not None and i not in only:
            continue
        # Frame i = the ship turned in the game by i * 360 / N.
        # In the game y points south, so in Blender the angle is negated.
        root.rotation_euler = (0, 0, -2 * math.pi * i / DIRECTIONS)
        render_one(i)

        # With persistent data Cycles sometimes loses an image texture partway through a run and keeps
        # rendering it black (seen on the sloop's hull). A fresh session fixes it, so re-render such a frame
        # without persistent data, then carry on with it
        retries = 0
        while frame_looks_broken(frame_path(i)) and retries < 2:
            retries += 1
            print(f"frame {i + 1}: texture went black, re-rendering it in a fresh session", flush=True)
            persistent = scene.render.use_persistent_data
            scene.render.use_persistent_data = False
            render_one(i)
            scene.render.use_persistent_data = persistent
        print(f"frame {i + 1}/{DIRECTIONS}", flush=True)
    root.rotation_euler = (0, 0, 0)


def render_one(i):
    scene = bpy.context.scene
    water = bpy.data.objects["ShadowCatcher"]
    # First the ship alone (no shadow), then together with the shadow.
    # The two renders are combined into a frame where the shadow can be made lighter.
    water.hide_render = True
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.filepath = frame_path(i).replace(".png", "_mask.png")
    bpy.ops.render.render(write_still=True)

    water.hide_render = False
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.filepath = frame_path(i)
    bpy.ops.render.render(write_still=True)

    combine_shadow(frame_path(i), frame_path(i).replace(".png", "_mask.png"))


BROKEN_DARK_SHARE = 0.04  # a sound frame has well under 1% near-black pixels, one with a black texture 10-20%


def frame_looks_broken(path):
    rgba = load_rgba(path)
    solid = rgba[..., 3] > 0.98
    if not solid.any():
        return False
    dark = rgba[..., :3].mean(axis=2)[solid] < 0.1
    return float(dark.mean()) > BROKEN_DARK_SHARE


try:
    # Blender ships OpenImageIO. Reading and writing frames through it keeps bpy.data.images
    # untouched while rendering, so the frame checks don't disturb the scene Cycles keeps between renders
    import OpenImageIO as oiio
except ImportError:
    oiio = None


def load_rgba(path):
    """Straight-alpha RGBA, float 0..1, row 0 at the top"""
    if oiio is not None:
        config = oiio.ImageSpec()
        config.attribute("oiio:UnassociatedAlpha", 1)  # PNG alpha as stored, not premultiplied
        buf = oiio.ImageBuf(path, 0, 0, config)
        px = buf.get_pixels(oiio.FLOAT)
        if px is None or buf.has_error:
            raise RuntimeError(f"can't read {path}: {buf.geterror()}")
        if px.shape[2] == 3:
            px = np.concatenate([px, np.ones(px.shape[:2] + (1,), dtype=px.dtype)], axis=2)
        return np.ascontiguousarray(px, dtype=np.float32)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1].copy()


def save_rgba(path, rgba, fmt="PNG", quality=90):
    h, w, _ = rgba.shape
    if fmt == "PNG" and oiio is not None:
        spec = oiio.ImageSpec(w, h, 4, oiio.UINT8)
        spec.attribute("oiio:UnassociatedAlpha", 1)  # the pixels are straight alpha already
        out = oiio.ImageOutput.create(path)
        if out is None or not out.open(path, spec):
            raise RuntimeError(f"can't write {path}: {oiio.geterror()}")
        out.write_image(np.ascontiguousarray(np.clip(rgba, 0, 1), dtype=np.float32))
        out.close()
        return
    img = bpy.data.images.new("tmp_save", w, h, alpha=True)
    img.alpha_mode = "STRAIGHT"
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = fmt
    if fmt == "WEBP":
        scene = bpy.context.scene
        settings = scene.render.image_settings
        old = (settings.file_format, settings.quality, settings.color_mode)
        settings.file_format = "WEBP"
        settings.quality = quality
        settings.color_mode = "RGBA"
        img.save_render(path, scene=scene)
        settings.file_format, settings.quality, settings.color_mode = old
    else:
        img.save()
    bpy.data.images.remove(img)


def combine_shadow(full_path, mask_path):
    """The ship from the full render + its shadow weakened to SHADOW_OPACITY"""
    full = load_rgba(full_path)
    ship_a = load_rgba(mask_path)[..., 3:4]
    total_a = full[..., 3:4]
    # The shadow is where the full render is opaque but the ship isn't
    shadow_a = np.clip((total_a - ship_a) / np.maximum(1 - ship_a, 1e-4), 0, 1)
    # Render noise leaves a barely visible "shadow" over the whole frame: cut it off, otherwise the frame won't trim
    shadow_a = np.clip((shadow_a - SHADOW_CUTOFF) / (1 - SHADOW_CUTOFF), 0, 1) * SHADOW_OPACITY
    out_a = ship_a + (1 - ship_a) * shadow_a
    # Ship color: in the full render it is blended with the black shadow under it, so restore it
    rgb_premul = full[..., :3] * total_a
    out_rgb = np.where(out_a > 1e-4, rgb_premul / np.maximum(out_a, 1e-4), 0)
    out = np.concatenate([np.clip(out_rgb, 0, 1), out_a], axis=2)
    save_rgba(full_path, out)
    os.remove(mask_path)


# ---------------------------------------------------------------------------
# Atlas
# ---------------------------------------------------------------------------


def trim(rgba):
    alpha = rgba[..., 3] > 2 / 255
    ys = np.where(alpha.any(axis=1))[0]
    xs = np.where(alpha.any(axis=0))[0]
    if len(xs) == 0:
        return 0, 0, 1, 1
    return int(xs[0]), int(ys[0]), int(xs[-1] + 1), int(ys[-1] + 1)


def pack(sizes, width):
    """Shelves: frames sorted by height go in rows"""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    x = y = shelf = 0
    pos = [None] * len(sizes)
    for i in order:
        w, h = sizes[i]
        if x + w > width:
            x = 0
            y += shelf + PADDING
            shelf = 0
        pos[i] = (x, y)
        x += w + PADDING
        shelf = max(shelf, h)
    return pos, y + shelf


def build_atlas(info):
    frames = [load_rgba(frame_path(i)) for i in range(DIRECTIONS)]
    boxes = [trim(f) for f in frames]
    sizes = [(x1 - x0, y1 - y0) for x0, y0, x1, y1 in boxes]

    # WebGL2 and WebGPU don't require power-of-two sizes, so the height isn't rounded up to 4096
    best = None
    for width in (1024, 2048, 4096):
        pos, used_h = pack(sizes, width)
        height = (used_h + 3) // 4 * 4
        if height <= 4096 and (best is None or width * height < best[0] * best[1]):
            best = (width, height, pos)
    width, height, pos = best

    atlas = np.zeros((height, width, 4), dtype=np.float32)
    data = {"frames": {}, "animations": {"ship": []}}
    W, H = info["width"], info["height"]
    ax, ay = info["anchor"]
    for i, (f, (x0, y0, x1, y1), (px, py)) in enumerate(zip(frames, boxes, pos)):
        w, h = x1 - x0, y1 - y0
        atlas[py : py + h, px : px + w] = f[y0:y1, x0:x1]
        name = f"ship_{i:02d}"
        data["frames"][name] = {
            "frame": {"x": px, "y": py, "w": w, "h": h},
            "rotated": False,
            "trimmed": True,
            "spriteSourceSize": {"x": x0, "y": y0, "w": w, "h": h},
            "sourceSize": {"w": W, "h": H},
            "anchor": {"x": round(ax / W, 5), "y": round(ay / H, 5)},
        }
        data["animations"]["ship"].append(name)

    os.makedirs(ATLAS_DIR, exist_ok=True)
    image_name = NAME + ".webp"
    save_rgba(os.path.join(ATLAS_DIR, image_name), atlas, fmt="WEBP", quality=92)
    data["meta"] = {
        "app": "render_sprites.py",
        "image": image_name,
        "format": "RGBA8888",
        "size": {"w": width, "h": height},
        "scale": "1",
        "ship": {
            "directions": DIRECTIONS,
            "pxPerUnit": PX_PER_UNIT,
            "pitch": CAM_PITCH,
            "yaw": CAM_YAW,
        },
    }
    with open(os.path.join(ATLAS_DIR, NAME + ".json"), "w") as fh:
        json.dump(data, fh, indent=1)
    print("atlas", width, "x", height, "->", ATLAS_DIR)
    return atlas


if __name__ == "__main__":
    info = setup_scene()
    render_frames()
    build_atlas(info)

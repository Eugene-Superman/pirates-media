"""
Fog of war textures for the game, made in Blender.

Run: open blender-assets/effects/fog/fog.blend, Scripting tab -> Open -> build_fog.py -> Run Script.
It rebuilds the scene of the open file (so use it only in fog.blend) and writes into the game,
canvas/public/sprites/fog/:
  puffs.webp + puffs.json  cloud puffs rendered as volumes in Cycles, a Pixi spritesheet (frames puff_0 ...);
                           lit by the game's sun and seen from the game camera's pitch, like the ships
  wisps.webp               a seamless tile of thin mist, made from periodic noise (no Blender rendering needed)
Frames stay in frames/ next to the .blend for inspection.
"""

import json
import math
import os

import bpy
import numpy as np
from mathutils import Euler, Vector

try:
    import OpenImageIO as oiio
except ImportError:  # older Blender builds: fall back to bpy images
    oiio = None

# Camera and light follow the game (see render_sprites.py)
CAM_PITCH = 30.0
LIGHT_GAME = (-0.6, 0.1, 0.8)  # game coordinates, y to the south

PUFF_W, PUFF_H = 384, 320  # pixels per puff
ORTHO_SCALE = 3.2  # world units across a puff's frame
COLUMNS = 3
SAMPLES = 48
# One entry per puff: noise seed (W), shape (x, y, z scale of the cloud), turn around z (radians)
PUFFS = [
    (2.1, (1.30, 1.15, 0.55), 0.0),
    (5.3, (1.45, 1.20, 0.50), 0.8),
    (8.8, (1.25, 1.10, 0.60), 1.6),
    (12.4, (1.50, 1.30, 0.48), 2.4),
    (15.9, (1.20, 1.05, 0.55), 3.1),
    (19.6, (1.40, 1.25, 0.50), 4.0),
]
# Shape of the volume: noise lumps inside a soft sphere
NOISE_SCALE = 1.6
NOISE_DETAIL = 10
NOISE_ROUGHNESS = 0.55
NOISE_DISTORTION = 0.3
DENSITY_FROM = (0.30, 0.55)  # noise × falloff below this is clear air, above it full density
DENSITY = 22
FALLOFF_POWER = 0.6
SUN_STRENGTH = 5.0
SKY_STRENGTH = 0.75
SKY_COLOR = (0.55, 0.66, 0.78)  # bluish, so shaded sides of the fog look cool

WISPS_SIZE = 512  # pixels, a power of two for the FFT and for tiling
WISPS_SEED = 7
WISPS_COLOR = (0.93, 0.96, 0.98)


def fog_dir():
    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    return os.environ.get("FOG_OUT") or os.getcwd()


FOG_DIR = fog_dir()  # blender-assets/effects/fog
FRAMES_DIR = os.path.join(FOG_DIR, "frames")
OUT_DIR = os.environ.get("FOG_SPRITES") or os.path.normpath(
    os.path.join(FOG_DIR, "..", "..", "..", "canvas", "public", "sprites", "fog")
)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


def setup_scene():
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    scene.render.engine = "CYCLES"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.cycles.volume_bounces = 2
    prefs = bpy.context.preferences.addons.get("cycles")
    scene.cycles.device = "GPU" if prefs and prefs.preferences.compute_device_type != "NONE" else "CPU"
    scene.render.film_transparent = True
    scene.render.resolution_x = PUFF_W
    scene.render.resolution_y = PUFF_H
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    world = bpy.data.worlds.get("FogWorld") or bpy.data.worlds.new("FogWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*SKY_COLOR, 1)
    bg.inputs["Strength"].default_value = SKY_STRENGTH
    scene.world = world

    sun_data = bpy.data.lights.get("FogSun") or bpy.data.lights.new("FogSun", "SUN")
    sun_data.energy = SUN_STRENGTH
    sun_data.angle = math.radians(3)
    sun_data.color = (1.0, 0.96, 0.9)
    sun = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun)
    x, y, z = LIGHT_GAME
    sun.rotation_euler = Vector((x, -y, z)).normalized().to_track_quat("Z", "Y").to_euler()

    cam_data = bpy.data.cameras.get("FogCam") or bpy.data.cameras.new("FogCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ORTHO_SCALE
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    pitch = math.radians(CAM_PITCH)
    cam.location = (0, -20 * math.cos(pitch), 20 * math.sin(pitch))
    cam.rotation_euler = Euler((math.radians(90) - pitch, 0, 0))

    mesh = bpy.data.meshes.new("PuffDomain")
    puff = bpy.data.objects.new("Puff", mesh)
    scene.collection.objects.link(puff)
    verts = [(sx, sy, sz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(puff_material())
    return scene, puff


def puff_material():
    mat = bpy.data.materials.get("PuffVolume") or bpy.data.materials.new("PuffVolume")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.95, 0.97, 1.0, 1)
    vol.inputs["Anisotropy"].default_value = 0.2
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.name = "Lumps"
    noise.noise_dimensions = "4D"
    noise.inputs["Scale"].default_value = NOISE_SCALE
    noise.inputs["Detail"].default_value = NOISE_DETAIL
    noise.inputs["Roughness"].default_value = NOISE_ROUGHNESS
    noise.inputs["Distortion"].default_value = NOISE_DISTORTION
    sphere = nt.nodes.new("ShaderNodeTexGradient")
    sphere.gradient_type = "SPHERICAL"
    falloff = nt.nodes.new("ShaderNodeMath")
    falloff.operation = "POWER"
    falloff.inputs[1].default_value = FALLOFF_POWER
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    density = nt.nodes.new("ShaderNodeMapRange")
    density.inputs["From Min"].default_value = DENSITY_FROM[0]
    density.inputs["From Max"].default_value = DENSITY_FROM[1]
    density.inputs["To Max"].default_value = DENSITY
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(coord.outputs["Object"], sphere.inputs["Vector"])
    nt.links.new(sphere.outputs["Fac"], falloff.inputs[0])
    nt.links.new(falloff.outputs[0], mul.inputs[0])
    nt.links.new(noise.outputs["Fac"], mul.inputs[1])
    nt.links.new(mul.outputs[0], density.inputs["Value"])
    nt.links.new(density.outputs["Result"], vol.inputs["Density"])
    nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
    return mat


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


def load_rgba(path):
    """Straight-alpha RGBA, float 0..1, row 0 at the top (as in render_sprites.py)"""
    if oiio is not None:
        config = oiio.ImageSpec()
        config.attribute("oiio:UnassociatedAlpha", 1)  # PNG alpha as stored, not premultiplied
        buf = oiio.ImageBuf(path, 0, 0, config)
        px = buf.get_pixels(oiio.FLOAT)
        if px is None or buf.has_error:
            raise RuntimeError(f"can't read {path}: {buf.geterror()}")
        return np.ascontiguousarray(px, dtype=np.float32)
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1].copy()


def save_webp(path, rgba, quality=90):
    """rgba: straight alpha, float 0..1, row 0 at the top. Written through Blender, as render_sprites.py does"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h, w, _ = rgba.shape
    img = bpy.data.images.new("fog_out", w, h, alpha=True)
    img.alpha_mode = "STRAIGHT"
    img.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "WEBP"
    settings = bpy.context.scene.render.image_settings
    old = (settings.file_format, settings.quality, settings.color_mode)
    settings.file_format = "WEBP"
    settings.quality = quality
    settings.color_mode = "RGBA"
    img.save_render(path, scene=bpy.context.scene)
    settings.file_format, settings.quality, settings.color_mode = old
    bpy.data.images.remove(img)


# ---------------------------------------------------------------------------
# Puffs
# ---------------------------------------------------------------------------


def render_puffs(scene, puff):
    noise = puff.data.materials[0].node_tree.nodes["Lumps"]
    paths = []
    for i, (seed, shape, turn) in enumerate(PUFFS):
        noise.inputs["W"].default_value = seed
        puff.scale = shape
        puff.rotation_euler = (0, 0, turn)
        path = os.path.join(FRAMES_DIR, f"puff_{i}.png")
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        paths.append(path)
        print("puff", i, "rendered", flush=True)
    return paths


def alpha_box(rgba, threshold=2 / 255, pad=1):
    """Bounding box (x0, y0, x1, y1) of the pixels that aren't fully clear"""
    ys, xs = np.nonzero(rgba[..., 3] > threshold)
    h, w = rgba.shape[:2]
    if len(xs) == 0:
        return 0, 0, w, h
    box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + 1 + pad, w), min(ys.max() + 1 + pad, h))
    return tuple(int(v) for v in box)  # plain ints: numpy's don't go into JSON


def build_puff_atlas(paths):
    rows = math.ceil(len(paths) / COLUMNS)
    atlas = np.zeros((rows * PUFF_H, COLUMNS * PUFF_W, 4), dtype=np.float32)
    frames = {}
    for i, path in enumerate(paths):
        x, y = (i % COLUMNS) * PUFF_W, (i // COLUMNS) * PUFF_H
        rgba = load_rgba(path)
        atlas[y : y + PUFF_H, x : x + PUFF_W] = rgba
        # Only the cloud and a pixel of air around it is drawn: the clear margins would cost fill rate for nothing
        x0, y0, x1, y1 = alpha_box(rgba)
        frames[f"puff_{i}"] = {
            "frame": {"x": x + x0, "y": y + y0, "w": x1 - x0, "h": y1 - y0},
            "rotated": False,
            "trimmed": True,
            "spriteSourceSize": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
            "sourceSize": {"w": PUFF_W, "h": PUFF_H},
        }
    save_webp(os.path.join(OUT_DIR, "puffs.webp"), atlas)
    data = {
        "frames": frames,
        "animations": {"puff": list(frames)},
        "meta": {
            "app": "build_fog.py",
            "image": "puffs.webp",
            "format": "RGBA8888",
            "size": {"w": atlas.shape[1], "h": atlas.shape[0]},
            "scale": "1",
            # A puff's frame is this many of its own widths wide: the game sizes puffs by this
            "fog": {"frameWidth": ORTHO_SCALE, "pitch": CAM_PITCH},
        },
    }
    with open(os.path.join(OUT_DIR, "puffs.json"), "w") as fh:
        json.dump(data, fh, indent=1)


# ---------------------------------------------------------------------------
# Wisps: periodic noise, so the tile repeats without seams
# ---------------------------------------------------------------------------


def periodic_noise(n, beta, rng, stretch=1.0, lowest=2):
    """
    Smooth noise 0..1 that tiles: random phases with a 1/f^beta spectrum. stretch > 1 draws streaks along x.
    lowest: the fewest waves across the tile kept, so no single blob fills it and the repeat shows less
    """
    # Faster falloff across x than y: the noise changes slowly along x, so its features are long along x
    fx = np.fft.fftfreq(n)[None, :] * stretch
    fy = np.fft.fftfreq(n)[:, None]
    f = np.hypot(fx, fy)
    f[0, 0] = 1
    amp = f**-beta
    amp[f < lowest / n] = 0
    amp *= np.exp(-((f / 0.12) ** 2))  # no pixel-sized grain
    field = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * amp))
    return (field - field.min()) / (field.max() - field.min())


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def build_wisps():
    rng = np.random.default_rng(WISPS_SEED)
    n = WISPS_SIZE
    base = periodic_noise(n, 1.5, rng, stretch=2.5, lowest=3)
    # Domain warp with two more periodic fields: curls the streaks without breaking the tiling
    warp_x = periodic_noise(n, 2.0, rng) - 0.5
    warp_y = periodic_noise(n, 2.0, rng) - 0.5
    ys, xs = np.mgrid[0:n, 0:n]
    sx = (xs + warp_x * n * 0.15).astype(int) % n
    sy = (ys + warp_y * n * 0.15).astype(int) % n
    v = base[sy, sx]
    detail = periodic_noise(n, 1.1, rng, lowest=8)
    v = v * 0.75 + detail * 0.25
    alpha = smoothstep(0.38, 0.8, v) ** 1.2 * 0.9
    rgba = np.empty((n, n, 4), dtype=np.float32)
    rgba[..., :3] = WISPS_COLOR
    rgba[..., 3] = alpha
    save_webp(os.path.join(OUT_DIR, "wisps.webp"), rgba)


def main():
    scene, puff = setup_scene()
    build_puff_atlas(render_puffs(scene, puff))
    build_wisps()
    print("fog textures ->", OUT_DIR, flush=True)


if __name__ == "__main__":
    main()

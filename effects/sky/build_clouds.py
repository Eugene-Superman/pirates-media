"""
Clouds for the game's sky: a few small, soft cumulus clouds seen from the game camera high over the sea, written as a
Pixi spritesheet to canvas/public/sprites/sky/ (clouds.webp + clouds.json, frames cloud_0 ...).

Run it in Blender (Scripting -> Open -> Run Script; it needs only the numpy that comes with Blender) or with any Python
that has numpy and Pillow: python build_clouds.py. It takes a few seconds and doesn't touch the open scene.

Each cloud is a cluster of round cells (gaussian blobs) roughened by noise, seen from above: its thickness is lit by the
game's sun as the game camera sees it (pitch 30, yaw 45: the sun is to the left and towards the camera, so a cloud's
lower left is lit and its upper right in its own shade), with a cool shade in the thick parts and thin, frayed edges,
then squashed to the camera's pitch. The game (canvas/src/client/scene/effects/SkyClouds.ts) draws them see-through,
and their shadows on the sea from the same frames, darkened.
"""

import json
import math
import os

import numpy as np

# Camera and light follow the game (see render_sprites.py)
CAM_PITCH = 30.0
CAM_YAW = 45.0
LIGHT_GAME = (-0.6, 0.1, 0.8)  # towards the sun, game coordinates: x east, y south, z up

FIELD = 768  # pixels per side of a cloud seen straight from above
PX = FIELD / 512  # the sizes in pixels below are for a field of 512
FRAME_W = FIELD
FRAME_H = round(FIELD * math.sin(math.radians(CAM_PITCH)))  # squashed to the camera's pitch
COLUMNS = 3
RELIEF = 110.0  # pixels: how thick the thickest part of a cloud is, for its lighting
LIT = (1.0, 1.0, 1.0)
SHADE = (0.68, 0.75, 0.84)  # the cloud's shaded parts: bluish, lit by the sky
# One entry per cloud: seed, how many cells, its size (share of the field) along the screen's x and y
CLOUDS = [
    (3, 16, (0.24, 0.17)),
    (8, 12, (0.20, 0.16)),
    (14, 20, (0.28, 0.20)),
    (21, 10, (0.17, 0.14)),
    (27, 18, (0.27, 0.15)),
    (35, 14, (0.21, 0.19)),
]
CELL_SIZE = (0.05, 0.13)  # a dome's radius, share of the field: the smallest (at the cloud's edge), the biggest

try:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # pasted into Blender's console
    _SCRIPT_DIR = os.getcwd()


def _blender_script_dir():
    try:
        import bpy

        for text in bpy.data.texts:
            if text.filepath and os.path.basename(text.filepath) == "build_clouds.py":
                return os.path.dirname(bpy.path.abspath(text.filepath))
    except ImportError:
        pass
    return None


SKY_DIR = _blender_script_dir() or _SCRIPT_DIR
OUT_DIR = os.environ.get("SKY_SPRITES") or os.path.normpath(
    os.path.join(SKY_DIR, "..", "..", "..", "canvas", "public", "sprites", "sky")
)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def screen_light():
    """The sun's direction in the frame of the picture: x right, y up the screen on the water, z up"""
    lx, ly, lz = np.array(LIGHT_GAME) / np.linalg.norm(LIGHT_GAME)
    yaw = math.radians(CAM_YAW)
    right = (math.cos(yaw), math.sin(yaw))
    up = (math.sin(yaw), -math.cos(yaw))
    return np.array([lx * right[0] + ly * right[1], lx * up[0] + ly * up[1], lz])


def noise(rng, n, smallest, biggest):
    """Smooth noise of features between `smallest` and `biggest` pixels, spread to mean 0 and deviation 1"""
    f = np.hypot(*np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n)))
    f[0, 0] = 1
    gain = f**-1.0 * np.exp(-((f * smallest) ** 2)) * (1 - np.exp(-((f * biggest) ** 2)))
    gain[0, 0] = 0
    field = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * gain))
    return (field - field.mean()) / field.std()


def blur(field, radius):
    """Gaussian blur of `radius` pixels (the field's edges are clear, so wrapping round them changes nothing)"""
    f = np.hypot(*np.meshgrid(np.fft.fftfreq(field.shape[1]), np.fft.fftfreq(field.shape[0])))
    return np.real(np.fft.ifft2(np.fft.fft2(field) * np.exp(-2 * (np.pi * f * radius) ** 2)))


def cloud(seed, cells, size):
    """One cloud seen from straight above: straight-alpha RGBA, rows from the top of the screen down"""
    rng = np.random.default_rng(seed)
    n = FIELD
    ys, xs = (np.mgrid[0:n, 0:n] + 0.5) / n - 0.5  # shares of the field from its middle; y down the picture
    # The cloud's top: a heap of domes, the biggest and highest in the middle, smaller ones round them as its lobes.
    # Where two meet there is a crease, which the light and the shade pick out
    top = np.zeros((n, n))
    for _ in range(cells):
        angle = rng.uniform(0, 2 * np.pi)
        reach = rng.uniform(0, 1) ** 0.7
        cx = math.cos(angle) * reach * size[0]
        cy = math.sin(angle) * reach * size[1]
        radius = CELL_SIZE[1] - (CELL_SIZE[1] - CELL_SIZE[0]) * reach * rng.uniform(0.7, 1.0)
        dome = radius * np.sqrt(np.clip(1 - ((xs - cx) ** 2 + (ys - cy) ** 2) / radius**2, 0, None))
        lift = (1 - reach) * CELL_SIZE[0]
        top = np.maximum(top, np.where(dome > 0, dome + lift, 0))
    top /= top.max()
    # Small billows on the domes, and a soft, frayed rim
    top += 0.025 * noise(rng, n, 10 * PX, 50 * PX) * smoothstep(0.0, 0.2, top)
    top = np.clip(blur(top, 3 * PX), 0, None)
    fray = noise(rng, n, 5 * PX, 30 * PX)
    cover = np.clip(blur(top, 7 * PX), 0, None) * (1 + 0.5 * fray * (1 - smoothstep(0.05, 0.3, top)))

    height = top * RELIEF * PX
    gy, gx = np.gradient(height)
    normal = np.stack([-gx, gy, np.ones_like(height)], axis=-1)  # picture rows run down: up the screen is -y
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    lambert = np.clip(normal @ screen_light(), 0, 1)
    # Creases between the lobes get less of the sky: darker than the domes round them
    crease = np.clip((blur(top, 14 * PX) - top) * 6, 0, 1)
    tone = np.clip(0.1 + 0.9 * lambert - 0.5 * crease + 0.1 * top, 0, 1)
    rgb = np.array(SHADE) + (np.array(LIT) - np.array(SHADE)) * tone[..., None]
    # Thin at the rim, where a dome's edge meets the air
    alpha = smoothstep(0.0, 0.3, cover) ** 1.2

    rgba = np.concatenate([rgb, alpha[..., None]], axis=-1)
    return squash(rgba)


def squash(rgba):
    """From straight above to the camera's pitch: rows squeezed together, colors averaged by their alpha"""
    n = rgba.shape[0]
    rows = np.linspace(0, n, FRAME_H + 1)
    out = np.zeros((FRAME_H, rgba.shape[1], 4))
    for i in range(FRAME_H):
        part = rgba[int(rows[i]) : max(int(rows[i + 1]), int(rows[i]) + 1)]
        weight = part[..., 3:].sum(axis=0)
        out[i, :, 3] = part[..., 3].mean(axis=0)
        out[i, :, :3] = (part[..., :3] * part[..., 3:]).sum(axis=0) / np.maximum(weight, 1e-6)
    return out


def alpha_box(rgba, threshold=2 / 255, pad=1):
    """Bounding box (x0, y0, x1, y1) of the pixels that aren't fully clear"""
    ys, xs = np.nonzero(rgba[..., 3] > threshold)
    h, w = rgba.shape[:2]
    if len(xs) == 0:
        return 0, 0, w, h
    box = (max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + 1 + pad, w), min(ys.max() + 1 + pad, h))
    return tuple(int(v) for v in box)  # plain ints: numpy's don't go into JSON


def save_webp(path, rgba, quality=90):
    """rgba: straight alpha, float 0..1, row 0 at the top. Pillow if there is one, otherwise Blender's own writer"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = np.round(np.clip(rgba, 0, 1) * 255).astype(np.uint8)
    try:
        from PIL import Image

        Image.fromarray(data, "RGBA").save(path, "WEBP", quality=quality, method=6)
        return
    except ImportError:
        pass
    import bpy

    h, w, _ = rgba.shape
    img = bpy.data.images.new("clouds_out", w, h, alpha=True)
    img.alpha_mode = "STRAIGHT"
    img.colorspace_settings.name = "Non-Color"  # stored exactly as given
    img.pixels.foreach_set((data[::-1] / 255.0).astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "WEBP"
    img.save(quality=quality)
    bpy.data.images.remove(img)


def main():
    rows = math.ceil(len(CLOUDS) / COLUMNS)
    atlas = np.zeros((rows * FRAME_H, COLUMNS * FRAME_W, 4))
    frames = {}
    for i, params in enumerate(CLOUDS):
        rgba = cloud(*params)
        x, y = (i % COLUMNS) * FRAME_W, (i // COLUMNS) * FRAME_H
        atlas[y : y + FRAME_H, x : x + FRAME_W] = rgba
        # Only the cloud and a pixel of air round it is drawn: the clear margins would cost fill rate for nothing
        x0, y0, x1, y1 = alpha_box(rgba)
        frames[f"cloud_{i}"] = {
            "frame": {"x": x + x0, "y": y + y0, "w": x1 - x0, "h": y1 - y0},
            "rotated": False,
            "trimmed": True,
            "spriteSourceSize": {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
            "sourceSize": {"w": FRAME_W, "h": FRAME_H},
        }
        print("cloud", i, flush=True)
    save_webp(os.path.join(OUT_DIR, "clouds.webp"), atlas)
    data = {
        "frames": frames,
        "animations": {"cloud": list(frames)},
        "meta": {
            "app": "build_clouds.py",
            "image": "clouds.webp",
            "format": "RGBA8888",
            "size": {"w": atlas.shape[1], "h": atlas.shape[0]},
            "scale": "1",
            "sky": {"pitch": CAM_PITCH, "yaw": CAM_YAW},
        },
    }
    with open(os.path.join(OUT_DIR, "clouds.json"), "w") as fh:
        json.dump(data, fh, indent=1)
    print("sky clouds ->", OUT_DIR, flush=True)


main()

"""
Foam textures for the game's wakes and sinking ships: one seamless tile written to
canvas/public/sprites/foam/foam.webp.

Run it in Blender (Scripting -> Open -> Run Script; it needs only the numpy that comes with Blender) or with any Python
that has numpy and Pillow: python build_foam.py. It takes about half a minute and doesn't touch the open scene.

Every pattern is periodic over the tile, so it repeats without a seam:
  R  "lace": sea foam seen from above, a network of bubble walls (the edges of a few sizes of Voronoi cells) with
     clusters of small bubbles; high where there is foam
  G  "patches": soft blotches a few to the tile (fractal noise), for foam that thins out unevenly
  B  "streaks": noise stretched along x, for foam drawn out in lines along a wake
The shaders (canvas/src/client/scene/effects/Wake.ts, Sinking.ts) dissolve foam by raising a threshold over these values,
so what matters is how the values are spread, not their exact look.
"""

import os

import numpy as np

SIZE = 512  # pixels per side
SEED = 7
# Bubble sizes: Voronoi cells across the tile, and how much each size adds to the lace
BUBBLES = ((9, 1.0), (18, 0.7), (40, 0.35))
PATCH_SCALE = 4.0  # blotches across the tile
STREAK_SCALE = 10.0  # streaks across the tile
STREAK_STRETCH = 8.0  # streaks are this many times longer along x than across

try:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # pasted into Blender's console
    _SCRIPT_DIR = os.getcwd()


def _blender_script_dir():
    try:
        import bpy

        for text in bpy.data.texts:
            if text.filepath and os.path.basename(text.filepath) == "build_foam.py":
                return os.path.dirname(bpy.path.abspath(text.filepath))
    except ImportError:
        pass
    return None


FOAM_DIR = _blender_script_dir() or _SCRIPT_DIR
OUT_DIR = os.environ.get("FOAM_SPRITES") or os.path.normpath(
    os.path.join(FOAM_DIR, "..", "..", "..", "canvas", "public", "sprites", "foam")
)


def normalize(field):
    """To 0..1 by rank: every value equally common, so a threshold t keeps exactly 1 - t of the tile"""
    order = np.argsort(field, axis=None)
    ranks = np.empty(field.size)
    ranks[order] = np.arange(field.size)
    return (ranks / (field.size - 1)).reshape(field.shape)


def fractal(rng, scale, stretch=1.0, falloff=1.6):
    """Periodic fractal noise from a random spectrum: features about SIZE / scale across, stretch times longer
    along x"""
    n = SIZE
    k = np.fft.fftfreq(n) * n  # whole waves per tile: every component repeats over the tile
    kx, ky = np.meshgrid(k, k)
    radius = np.hypot(kx * stretch, ky)
    amplitude = np.where(radius > 0, (np.maximum(radius, scale) / scale) ** -falloff, 0.0)
    amplitude *= np.exp(-((radius / (scale * 24)) ** 2))  # nothing finer than a pixel or two
    phase = rng.uniform(0, 2 * np.pi, (n, n))
    field = np.real(np.fft.ifft2(amplitude * np.exp(1j * phase)))
    return field


def voronoi_edges(rng, cells):
    """Distance from each pixel to the nearest border between periodic Voronoi cells, in cells (0 on a border)"""
    n = SIZE
    points = rng.uniform(0.1, 0.9, (cells, cells, 2))  # one jittered point per grid cell, in cell units
    ys, xs = (np.mgrid[0:n, 0:n] + 0.5) * cells / n
    cx = np.floor(xs).astype(int)
    cy = np.floor(ys).astype(int)
    first = np.full((n, n), 9.0)
    second = np.full((n, n), 9.0)
    for ox in (-2, -1, 0, 1, 2):
        for oy in (-2, -1, 0, 1, 2):
            gx = cx + ox
            gy = cy + oy
            p = points[gy % cells, gx % cells]
            d = np.hypot(xs - (gx + p[..., 0]), ys - (gy + p[..., 1]))
            second = np.where(d < first, first, np.minimum(second, d))
            first = np.minimum(first, d)
    return second - first


def lace(rng):
    total = np.zeros((SIZE, SIZE))
    for cells, weight in BUBBLES:
        edge = voronoi_edges(rng, cells)
        # Walls of uneven thickness: thicker where the noise says, so the net has strands and threads
        thickness = 0.06 + 0.1 * normalize(fractal(rng, cells / 2))
        total += weight * np.exp(-((edge / thickness) ** 2))
    # Clusters: the bubbles crowd together in some places and thin out in others
    crowd = fractal(rng, 5)
    crowd = (crowd - crowd.mean()) / crowd.std()
    return normalize(total + 0.25 * crowd)


def save_webp(path, rgb, quality=94):
    """rgb: float 0..1, row 0 at the top. Pillow if there is one, otherwise Blender's own writer"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    try:
        from PIL import Image

        Image.fromarray(data, "RGB").save(path, "WEBP", quality=quality, method=6)
        return
    except ImportError:
        pass
    import bpy

    h, w, _ = rgb.shape
    img = bpy.data.images.new("foam_out", w, h, alpha=False)
    img.colorspace_settings.name = "Non-Color"  # data, not colors: stored exactly as given
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = data[::-1] / 255.0
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "WEBP"
    img.save(quality=quality)
    bpy.data.images.remove(img)


def main():
    rng = np.random.default_rng(SEED)
    r = lace(rng)
    g = normalize(fractal(rng, PATCH_SCALE))
    b = normalize(fractal(rng, STREAK_SCALE, stretch=STREAK_STRETCH, falloff=1.4))
    save_webp(os.path.join(OUT_DIR, "foam.webp"), np.stack([r, g, b], -1))
    print("foam texture ->", OUT_DIR, flush=True)


main()

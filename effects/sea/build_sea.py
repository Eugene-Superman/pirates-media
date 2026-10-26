"""
Textures for the sea's surface in the game: seamless tiles of ocean waves, caustics and broad patches, written to
canvas/public/sprites/sea/.

Run it in Blender (Scripting -> Open -> Run Script; it needs only the numpy that comes with Blender) or with any Python
that has numpy and Pillow: python build_sea.py. It takes a few seconds and doesn't touch the open scene.

The waves are a sum of thousands of wave trains drawn from an ocean wave spectrum (Phillips, as in Tessendorf's
"Simulating Ocean Water"), made with an FFT. Every wave fits the tile a whole number of times, so the tile repeats
without a seam. Sharp crests come from the same "choppy" horizontal displacement the film ocean uses.

Each wave map stores, per pixel:
  R, G  the slope of the water along x and y (0.5 = flat; SLOPE_RANGE is the steepest slope stored)
  B     "crest": 0.5 is the mean water level, darker towards the troughs, near 1 where crests are sharp enough to
        break (where the surface would fold over: the Jacobian of the displacement falls below zero)
The game's sea shader (canvas/src/client/scene/effects/seaSurface.ts) reads them like that.

patches.webp is three fields of broad, soft blobs, stretched over thousands of world units by the game:
  R     depth: darker, deeper water where it is low, lighter, shallower water where it is high
  G     cloud shadows drifting over the sea with the wind
  B     gusts: where it is high the wind blows harder, and the sea is rougher, with chop and whitecaps
Each is spread evenly over 0..1 (as many pixels at every value), so a threshold covers that share of the sea.
"""

import os

import numpy as np

SIZE = 512  # pixels per side
SLOPE_RANGE = 1.0  # slope stored at 0 and 1 in R and G

# name: (seed, peak wavelength as a share of the tile, shortest waves as a share of the peak wavelength,
#        wind direction in degrees, directional spread exponent (higher = longer crests),
#        how much of the waves moving against the wind is kept (0..1), rms slope, choppiness,
#        how much of "crest" comes from height rather than crest sharpness)
WAVES = {
    # Long, regular swell from far away: smooth, long crests, almost no breaking
    "swell": (11, 0.25, 0.3, 20, 10, 0.1, 0.10, 0.6, 0.85),
    # The usual wind sea: shorter, crossing waves with some whitecaps
    "wind": (23, 0.14, 0.22, 35, 3, 0.25, 0.16, 1.0, 0.55),
    # Steep chop of a strong wind: many sharp crests that break
    "chop": (37, 0.08, 0.2, 50, 2, 0.35, 0.22, 1.35, 0.4),
    # Small ripples to lay over the others, no direction
    "ripples": (41, 0.04, 0.3, 0, 0, 1.0, 0.12, 0.3, 0.9),
}
CAUSTICS_CELLS = 9  # light network of the caustics: cells across the tile
CAUSTICS_SEED = 5
PATCHES_SIZE = 256  # pixels per side: the fields are smooth
# Per channel: seed, the biggest blobs' size as a share of the tile, the smallest ones'
PATCHES = {"depth": (61, 0.5, 0.08), "clouds": (73, 0.35, 0.05), "gusts": (89, 0.3, 0.06)}

try:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # pasted into Blender's console
    _SCRIPT_DIR = os.getcwd()


def _blender_script_dir():
    try:
        import bpy

        for text in bpy.data.texts:
            if text.filepath and os.path.basename(text.filepath) == "build_sea.py":
                return os.path.dirname(bpy.path.abspath(text.filepath))
    except ImportError:
        pass
    return None


SEA_DIR = _blender_script_dir() or _SCRIPT_DIR
OUT_DIR = os.environ.get("SEA_SPRITES") or os.path.normpath(
    os.path.join(SEA_DIR, "..", "..", "..", "canvas", "public", "sprites", "sea")
)


def wrap_sample(field, x, y):
    """Bilinear sample of a periodic field at fractional pixel positions"""
    n = field.shape[0]
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx = x - x0
    fy = y - y0
    x0 %= n
    y0 %= n
    x1 = (x0 + 1) % n
    y1 = (y0 + 1) % n
    top = field[y0, x0] * (1 - fx) + field[y0, x1] * fx
    bottom = field[y1, x0] * (1 - fx) + field[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def ocean(seed, peak, shortest, wind_deg, spread, against, slope, choppy, height_share):
    rng = np.random.default_rng(seed)
    n = SIZE
    m = np.fft.fftfreq(n, 1.0 / n)  # whole waves per tile
    kx, ky = np.meshgrid(2 * np.pi * m, 2 * np.pi * m)  # rows are y
    k = np.hypot(kx, ky)
    k[0, 0] = 1.0

    # Phillips spectrum: a peak at the given wavelength, falling off steeply for longer waves and as k^-4 for
    # shorter ones. Waves shorter than `shortest` are damped: seen from the game's height they would only be noise
    big = peak / (2 * np.pi * np.sqrt(2))
    spectrum = np.exp(-1.0 / (k * big) ** 2) / k**4
    spectrum *= np.exp(-((k * peak * shortest / (2 * np.pi)) ** 2))
    if spread > 0:
        wx, wy = np.cos(np.radians(wind_deg)), np.sin(np.radians(wind_deg))
        along = (kx * wx + ky * wy) / k
        spectrum *= np.where(along > 0, 1.0, against) * np.abs(along) ** spread
    spectrum[0, 0] = 0

    amplitude = (rng.standard_normal((n, n)) + 1j * rng.standard_normal((n, n))) * np.sqrt(spectrum)

    def field(factor):
        return np.real(np.fft.ifft2(amplitude * factor))

    h = field(1.0)
    scale = 1.0 / h.std()
    h *= scale
    # Horizontal displacement towards the crests (in pixels) and its derivatives
    disp_x = field(-1j * kx / k) * scale
    disp_y = field(-1j * ky / k) * scale
    dxx = field(kx * kx / k) * scale
    dyy = field(ky * ky / k) * scale
    dxy = field(kx * ky / k) * scale
    # Choppiness is set so the strongest crests just fold over; `choppy` scales that. Negative: points move
    # towards the crests, which sharpens them and widens the troughs, as in real waves
    curvature = np.max(np.abs(dxx + dyy))
    lam = -choppy / curvature
    jacobian = (1 + lam * dxx) * (1 + lam * dyy) - (lam * dxy) ** 2

    # The displaced surface, sampled back onto the pixel grid: find for every pixel the point that moved there
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float64)
    dpx = disp_x * lam * n / (2 * np.pi)
    dpy = disp_y * lam * n / (2 * np.pi)
    sx, sy = xs.copy(), ys.copy()
    for _ in range(6):
        sx = xs - wrap_sample(dpx, sx, sy)
        sy = ys - wrap_sample(dpy, sx, sy)
    height = wrap_sample(h, sx, sy)
    fold = wrap_sample(jacobian, sx, sy)

    # Slopes of the displaced surface
    gx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) / 2
    gy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) / 2
    rms = np.sqrt((gx**2 + gy**2).mean() / 2)
    gx *= slope / rms
    gy *= slope / rms

    # Crest: a mix of height and how close the surface is to folding over (sharp, breaking crests)
    sharp = (1 - fold) / max((1 - fold).std(), 1e-6)
    crest = height_share * (height / height.std()) + (1 - height_share) * sharp
    crest = 0.5 + 0.5 * np.tanh(crest / 2.2)
    breaking = np.clip(-fold / 0.4, 0, 1)
    crest = np.where(fold < 0, np.maximum(crest, 0.85 + 0.15 * breaking), crest)

    rgb = np.stack(
        [
            np.clip(0.5 + 0.5 * gx / SLOPE_RANGE, 0, 1),
            np.clip(0.5 + 0.5 * gy / SLOPE_RANGE, 0, 1),
            np.clip(crest, 0, 1),
        ],
        axis=-1,
    )
    return rgb


def caustics():
    """Bright network of light like sunlight focused by ripples onto a shallow sea floor: the edges of a periodic
    Voronoi diagram, softened"""
    rng = np.random.default_rng(CAUSTICS_SEED)
    n = SIZE
    cells = CAUSTICS_CELLS
    grid = np.stack(np.meshgrid(np.arange(cells), np.arange(cells)), -1).reshape(-1, 2)
    points = (grid + rng.uniform(0.15, 0.85, grid.shape)) / cells  # one jittered point per cell
    ys, xs = (np.mgrid[0:n, 0:n] + 0.5) / n
    first = np.full((n, n), 9.0)
    second = np.full((n, n), 9.0)
    for px, py in points:
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                d = np.hypot(xs - (px + ox), ys - (py + oy))
                second = np.where(d < first, first, np.minimum(second, d))
                first = np.minimum(first, d)
    edge = (second - first) * cells  # 0 on the cell borders
    light = np.exp(-((edge / 0.09) ** 2)) + 0.35 * np.exp(-((edge / 0.3) ** 2))
    light = np.clip(light / light.max(), 0, 1)
    return np.repeat(light[..., None], 3, axis=-1)


def blobs(seed, biggest, smallest):
    """Soft blobs of every size between `biggest` and `smallest` (shares of the tile), seamless: white noise filtered
    in the frequency domain, then spread evenly over 0..1"""
    rng = np.random.default_rng(seed)
    n = PATCHES_SIZE
    m = np.fft.fftfreq(n, 1.0 / n)  # whole waves per tile
    k = np.hypot(*np.meshgrid(m, m))
    k[0, 0] = 1.0
    gain = k**-1.5 * np.exp(-((k * smallest) ** 2)) * (1 - np.exp(-((k * biggest) ** 2)))
    gain[0, 0] = 0
    field = np.real(np.fft.ifft2(np.fft.fft2(rng.standard_normal((n, n))) * gain))
    ranks = field.ravel().argsort().argsort()
    return (ranks / (ranks.size - 1)).reshape(n, n)


def patches():
    depth = blobs(*PATCHES["depth"])
    clouds = blobs(*PATCHES["clouds"])
    gusts = blobs(*PATCHES["gusts"])
    return np.stack([depth, clouds, gusts], axis=-1)


def save_webp(path, rgb, quality=92):
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
    img = bpy.data.images.new("sea_out", w, h, alpha=False)
    img.colorspace_settings.name = "Non-Color"  # data, not colors: stored exactly as given
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :3] = data[::-1] / 255.0
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = "WEBP"
    img.save(quality=quality)
    bpy.data.images.remove(img)


def main():
    for name, params in WAVES.items():
        save_webp(os.path.join(OUT_DIR, f"{name}.webp"), ocean(*params))
        print("sea:", name, flush=True)
    save_webp(os.path.join(OUT_DIR, "caustics.webp"), caustics())
    save_webp(os.path.join(OUT_DIR, "patches.webp"), patches())
    print("sea textures ->", OUT_DIR, flush=True)


main()

"""
What the scripts that cut pictures out of painted sheets share (icons/build_gun_icons.py, icons/build_ammo_icons.py,
icons/build_outfit_icons.py, port/build_harbour_art.py, port/build_port_art.py): pictures in and out with Blender's
Python or with Pillow, the sheet's background as a smooth field, cutting a picture out of it, shrinking it, and packing
icons into an atlas.

A sheet is painted on a dark gradient. A picture on it is what differs from that gradient, reached from its middle,
less the soft shadow under it and the edges of its neighbours. A round one (a cannonball, a medallion) is also given
its circle, so that its dark parts, close to the background's colour, aren't taken for it.
"""

import json
import os

import numpy as np

try:
    import bpy
except ImportError:
    bpy = None

BLOCK = 32  # pixels: the background is sampled in blocks this big
LIKE = 0.09  # how far from the background (summed over red, green, blue, 0..1) a pixel may be and still be it
SHADOW = 0.17  # how much darker than the background the shadow under a picture may be
MARGIN = 10  # pixels of the sheet round a picture's box, taken with it
STANDS_OUT = 0.05  # how far what stands out of a round picture may reach past its circle, in its radius
POCKET_LIKE = 0.06  # how close to the background a pocket a picture encloses must be to be taken for the background
POCKET = 2  # pixels: a pocket that thin (a shadow along a rope) stays the picture's


# ---------------------------------------------------------------------------
# Pictures in and out: Blender's, or Pillow's
# ---------------------------------------------------------------------------


def load_rgba(path):
    """Float 0..1, straight alpha, row 0 at the top"""
    if bpy:
        image = bpy.data.images.load(path)
        image.alpha_mode = "STRAIGHT"
        w, h = image.size
        px = np.empty(w * h * 4, np.float32)
        image.pixels.foreach_get(px)
        bpy.data.images.remove(image)
        return px.reshape(h, w, 4)[::-1].copy()
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255


def load_rgb(path):
    """Float 0..1, row 0 at the top"""
    return load_rgba(path)[..., :3].copy()


def save_webp(path, rgba, quality):
    """rgba: float 0..1, straight alpha (or rgb, opaque), row 0 at the top"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if rgba.shape[2] == 3:
        rgba = np.concatenate([rgba, np.ones(rgba.shape[:2] + (1,), rgba.dtype)], axis=2)
    if bpy:
        h, w, _ = rgba.shape
        image = bpy.data.images.new("cutout", w, h, alpha=True)
        image.alpha_mode = "STRAIGHT"
        image.pixels.foreach_set(np.ascontiguousarray(rgba[::-1]).astype(np.float32).ravel())
        image.filepath_raw = path
        image.file_format = "WEBP"
        image.save(filepath=path, quality=quality)
        bpy.data.images.remove(image)
        return
    from PIL import Image

    pixels = (np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8)
    if (pixels[..., 3] == 255).all():
        Image.fromarray(pixels[..., :3], "RGB").save(path, quality=quality, method=6)
    else:
        Image.fromarray(pixels, "RGBA").save(path, quality=quality, method=6)


def save_json(path, data):
    with open(path, "w", newline="\n") as fh:
        json.dump(data, fh, indent=1)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Cutting a picture out
# ---------------------------------------------------------------------------


def background(sheet):
    """The sheet's background as a smooth field: blocks that are flat, dark and colourless give their median, the
    others take their neighbours', and the blocks are eased into each other"""
    h, w, _ = sheet.shape
    lum = sheet.mean(axis=2)
    flat = np.zeros_like(lum)
    flat[1:-1, 1:-1] = (np.abs(lum[1:-1, 1:-1] - lum[:-2, 1:-1]) + np.abs(lum[1:-1, 1:-1] - lum[2:, 1:-1]) +
                        np.abs(lum[1:-1, 1:-1] - lum[1:-1, :-2]) + np.abs(lum[1:-1, 1:-1] - lum[1:-1, 2:]))
    plain = (flat < 0.02) & (sheet.max(axis=2) - sheet.min(axis=2) < 0.06) & (lum < 0.22)
    gy, gx = h // BLOCK, w // BLOCK
    grid = np.full((gy, gx, 3), np.nan, np.float32)
    for j in range(gy):
        for i in range(gx):
            block = (slice(j * BLOCK, (j + 1) * BLOCK), slice(i * BLOCK, (i + 1) * BLOCK))
            if plain[block].mean() > 0.6:
                grid[j, i] = np.median(sheet[block][plain[block]], axis=0)
    while np.isnan(grid[..., 0]).any():
        known = np.isfinite(grid[..., :1])
        total = np.zeros_like(grid)
        count = np.zeros((gy, gx, 1))
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                shifted = np.roll(np.roll(np.where(known, grid, 0), dy, 0), dx, 1)
                total += shifted
                count += np.roll(np.roll(known, dy, 0), dx, 1)
        grid = np.where(~known & (count > 0), total / np.maximum(count, 1), grid)
    # Bilinear between the blocks' middles
    ys = np.clip((np.arange(h) + 0.5) / BLOCK - 0.5, 0, gy - 1)
    xs = np.clip((np.arange(w) + 0.5) / BLOCK - 0.5, 0, gx - 1)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, gy - 1), np.minimum(x0 + 1, gx - 1)
    ty, tx = (ys - y0)[:, None, None], (xs - x0)[None, :, None]
    top = grid[y0][:, x0] * (1 - tx) + grid[y0][:, x1] * tx
    bottom = grid[y1][:, x0] * (1 - tx) + grid[y1][:, x1] * tx
    return top * (1 - ty) + bottom * ty


def grow(seed, allowed):
    """The pixels of `allowed` that `seed` reaches through them (4-connected)"""
    while True:
        more = seed.copy()
        more[1:] |= seed[:-1]
        more[:-1] |= seed[1:]
        more[:, 1:] |= seed[:, :-1]
        more[:, :-1] |= seed[:, 1:]
        more &= allowed
        if (more == seed).all():
            return seed
        seed = more


def crop(sheet, box, margin=MARGIN):
    """The sheet round a box (left, top, right, bottom), with a margin: (its left, its top, its pixels)"""
    h, w, _ = sheet.shape
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = max(0, x0 - margin), max(0, y0 - margin), min(w, x1 + margin), min(h, y1 + margin)
    return x0, y0, sheet[y0:y1, x0:x1]


def shrink(m, n):
    """A mask n pixels in from its edges (4-connected)"""
    for _ in range(n):
        inner = m.copy()
        inner[1:] &= m[:-1]
        inner[:-1] &= m[1:]
        inner[:, 1:] &= m[:, :-1]
        inner[:, :-1] &= m[:, 1:]
        m = inner
    return m


def spread(m, n):
    """A mask n pixels out past its edges (4-connected)"""
    for _ in range(n):
        outer = m.copy()
        outer[1:] |= m[:-1]
        outer[:-1] |= m[1:]
        outer[:, 1:] |= m[:, :-1]
        outer[:, :-1] |= m[:, 1:]
        m = outer
    return m


def mask(sheet, bg, box, like_bg=LIKE, pockets=False, close=0):
    """What of the sheet round a box is the picture there, as an alpha (the crop's size), and the crop's corner.
    like_bg: how far from the background a pixel may be and still be it (less for a dark picture, whose shadows are
    close to it); pockets: the background a picture encloses (between a sail and its ropes) is let through too;
    close: notches in its edge up to twice this many pixels wide are filled (the dark between plank ends, open to the
    background and as dark as it)"""
    x0, y0, color = crop(sheet, box)
    field = bg[y0:y0 + color.shape[0], x0:x0 + color.shape[1]]
    ch, cw, _ = color.shape
    delta = color - field
    darker = delta.mean(axis=2)
    tint = np.abs(delta - darker[..., None]).sum(axis=2)
    # 1. The background: like it, reached from the crop's edge (what a picture encloses stays its)
    like = np.abs(delta).sum(axis=2) < like_bg
    edge = np.zeros((ch, cw), bool)
    edge[:2] = edge[-2:] = True
    edge[:, :2] = edge[:, -2:] = True
    back = grow(edge & like, like)
    # 2. The shadow under it: a little darker than the background, colourless, smooth, in the lower part
    lum = color.mean(axis=2)
    smooth = np.zeros((ch, cw), bool)
    smooth[1:-1, 1:-1] = (np.abs(lum[1:-1, 2:] - lum[1:-1, :-2]) + np.abs(lum[2:, 1:-1] - lum[:-2, 1:-1])) < 0.03
    low = (np.arange(ch) > ch * 0.55)[:, None]
    shadow = (darker < 0) & (darker > -SHADOW) & (tint < 0.05) & smooth & low
    back = grow(back, back | shadow)
    # 3. The picture: what is left, joined to the crop's middle (not a neighbour's edge); if the middle is a gap in it,
    # its pixel nearest the middle
    seed = np.zeros((ch, cw), bool)
    seed[ch // 2 - 8:ch // 2 + 8, cw // 2 - 8:cw // 2 + 8] = True
    seed &= ~back
    if not seed.any():
        ys, xs = np.nonzero(~back)
        k = int(np.argmin((ys - ch / 2) ** 2 + (xs - cw / 2) ** 2))
        seed[ys[k], xs[k]] = True
    mine = grow(seed, ~back)
    if pockets:
        # The background showing through it: very like it, flat, and wider than a shadow along a rope
        pocket = mine & (np.abs(delta).sum(axis=2) < POCKET_LIKE) & smooth
        mine &= ~grow(shrink(pocket, POCKET), pocket)
    if close:
        mine = shrink(spread(mine, close), close)
    alpha = mine.astype(np.float32)
    near = alpha.copy()
    near[1:] += alpha[:-1]
    near[:-1] += alpha[1:]
    near[:, 1:] += alpha[:, :-1]
    near[:, :-1] += alpha[:, 1:]
    return x0, y0, color, np.where(mine, np.clip(near / 5 * 1.25, 0, 1), 0)  # the edge softened a pixel


def disc(x0, y0, h, w, circle):
    """A circle (its middle's x and y on the sheet, its radius) as an alpha over a crop at (x0, y0), its edge smooth"""
    cx, cy, r = circle
    ys = np.arange(h)[:, None] + y0 + 0.5
    xs = np.arange(w)[None, :] + x0 + 0.5
    return np.clip(r - np.hypot(xs - cx, ys - cy) + 0.5, 0, 1).astype(np.float32)


def trim(color, alpha):
    """The picture with its alpha, cropped to what shows"""
    rows, cols = np.nonzero(alpha > 0)
    t, b, l, r = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    return np.concatenate([color, alpha[..., None]], axis=2)[t:b, l:r]


def cut(sheet, bg, place, pockets=False):
    """A picture with its alpha. place: its box on the sheet (left, top, right, bottom), or its circle (x, y, radius):
    then the round body is all its, and what stands out of it (studs, a band) is cut out as a box's would be, close
    round it (a glow round it, or its light on the floor, is left behind); or a dict: its box, and like_bg and close
    for mask. pockets: see mask"""
    if isinstance(place, dict):
        _, _, color, alpha = mask(sheet, bg, place["box"], place.get("like_bg", LIKE), pockets, place.get("close", 0))
        return trim(color, alpha)
    if len(place) == 4:
        _, _, color, alpha = mask(sheet, bg, place, LIKE, pockets)
        return trim(color, alpha)
    cx, cy, r = place
    x0, y0, color, alpha = mask(sheet, bg, (cx - r, cy - r, cx + r, cy + r))
    h, w = alpha.shape
    near = disc(x0, y0, h, w, (cx, cy, r * (1 + STANDS_OUT)))
    return trim(color, np.maximum(alpha * near, disc(x0, y0, h, w, place)))


def resize(rgba, scale):
    """Shrinks a picture by `scale` (premultiplied, box-filtered along each axis, so edges don't darken)"""
    h, w, _ = rgba.shape
    nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
    pre = np.concatenate([rgba[..., :3] * rgba[..., 3:], rgba[..., 3:]], axis=2)

    def along(a, n, axis):
        size = a.shape[axis]
        edges = np.linspace(0, size, n + 1)
        out = []
        for i in range(n):
            lo, hi = edges[i], edges[i + 1]
            k0, k1 = int(np.floor(lo)), int(np.ceil(hi))
            weights = np.minimum(np.arange(k0, k1) + 1, hi) - np.maximum(np.arange(k0, k1), lo)
            part = np.take(a, np.arange(k0, k1), axis=axis)
            shape = [1] * a.ndim
            shape[axis] = len(weights)
            out.append((part * weights.reshape(shape)).sum(axis=axis) / weights.sum())
        return np.stack(out, axis=axis)

    small = along(along(pre, nh, 0), nw, 1)
    a = small[..., 3:]
    return np.concatenate([np.where(a > 0, small[..., :3] / np.maximum(a, 1e-6), 0), a], axis=2)


# ---------------------------------------------------------------------------
# Icons in an atlas
# ---------------------------------------------------------------------------


def build_atlas(source_dir, sheets, out_dir, name, tile, pad, columns, quality, pockets=(), stand=True):
    """Cuts every picture of the sheets out (sheets: a sheet's file in source_dir → {id: its box or circle}), scales
    each sheet's alike (its biggest picture fills its tile, less `pad` round it), stands them on their tiles' floors in
    a grid of `columns` (or, without `stand`, in their tiles' middles: a wide picture, a ship), and writes <name>.webp
    and <name>.json (the tile's size and each id's column and row). pockets: the pictures (ids) the background they
    enclose is cut out of too (see mask)"""
    icons = {}
    for sheet_name, places in sheets.items():
        sheet = load_rgb(os.path.join(source_dir, sheet_name))
        bg = background(sheet)
        cut_out = {key: cut(sheet, bg, place, key in pockets) for key, place in places.items()}
        scale = (tile - pad * 2) / max(max(icon.shape[:2]) for icon in cut_out.values())
        icons.update({key: resize(icon, scale) for key, icon in cut_out.items()})
        print(f"{sheet_name}: {len(cut_out)} pictures, scale {scale:.3f}", flush=True)
    rows = (len(icons) + columns - 1) // columns
    atlas = np.zeros((rows * tile, columns * tile, 4), np.float32)
    tiles = {}
    for k, (key, small) in enumerate(icons.items()):
        h, w, _ = small.shape
        col, row = k % columns, k // columns
        # Centred across, standing on the tile's floor or in its middle
        x = col * tile + (tile - w) // 2
        y = row * tile + (tile - pad - h if stand else (tile - h) // 2)
        atlas[y:y + h, x:x + w] = small
        tiles[key] = [col, row]
    save_webp(os.path.join(out_dir, f"{name}.webp"), atlas, quality)
    save_json(os.path.join(out_dir, f"{name}.json"), dict(file=f"{name}.webp", tile=tile, icons=tiles))
    print(f"{name}: {len(tiles)} icons in {columns}x{rows} tiles of {tile} px", flush=True)

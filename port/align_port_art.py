"""
Fits the painting of the port (port/source/island.webp) onto the render it was painted over (port/source/render/),
for build_port_art.py: the painting is a little smaller than the render, and its harbour walls lie a little inside
the render's, so it is moved onto it, its coast onto the render's coast and its walls onto the render's walls, which
are where the game's ships bump into them.

Needs a Python 3 with numpy, scipy, OpenCV and Pillow (not Blender's):
    pip install numpy scipy opencv-python pillow
    python port/align_port_art.py
Run it once after the painting or the render changes, then build_port_art.py. It writes port/source/island_warp.json:
for the render's frame (as build_port_art.py lays it out), every STEP pixels, where in the painting that pixel is.

How: first one affine for the whole painting (ECC on the two outlines, blurred), then a smooth bend. The render's
outline is matched to the painting's nearest outline facing the same way, within REACH pixels (the painting's water
doesn't count as land); those shifts, smoothed over SMOOTH pixels, bend the painting; again, ROUNDS times. The bend
fades out away from any outline, so the town and the hill keep their shapes.
"""

import json
import os
import sys

import cv2
import numpy as np
from scipy import ndimage

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import build_port_art as B  # noqa: E402 (the render's frame, laid out as the build lays it)

STEP = 16  # pixels between two points of the grid written
REACH = 35  # pixels: the farthest a render's outline is matched to the painting's
SMOOTH = 35  # pixels: how widely a shift is spread
ROUNDS = 6


def outline_land(picture):
    """What of a picture is land or wall: opaque, and not water (blue over red)"""
    r, b, a = picture[..., 0], picture[..., 2], picture[..., 3]
    land = (a > 0.5) & ~((b - r > 0.08) & (b > 0.25))
    return cv2.morphologyEx(land.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool)


def signed_distance(mask):
    return ndimage.distance_transform_edt(~mask) - ndimage.distance_transform_edt(mask)


def main():
    art, (width, height), anchor, labels, _ = B.render_frame()
    land = labels > 0
    land = cv2.morphologyEx(land.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool)
    paint = B.cutout.load_rgba(os.path.join(B.SOURCE_DIR, "island.webp"))
    ph, pw, _ = paint.shape

    # 1. One affine, from the painting laid over the render's raised part, its top left corner on the part's
    rows, cols = np.nonzero(land)
    guess = np.array([[1, 0, -cols.min()], [0, 1, -rows.min()]], np.float32)  # the frame's pixel → the painting's
    template = cv2.GaussianBlur(land.astype(np.float32), (0, 0), 6)
    big = np.zeros((max(height, ph), max(width, pw)), np.float32)
    big[:ph, :pw] = outline_land(paint)
    big = cv2.GaussianBlur(big, (0, 0), 6)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-7)
    _, affine = cv2.findTransformECC(template, big, guess, cv2.MOTION_AFFINE, criteria, None, 1)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    map_x = affine[0, 0] * xx + affine[0, 1] * yy + affine[0, 2]
    map_y = affine[1, 0] * xx + affine[1, 1] * yy + affine[1, 2]

    # 2. The bend: the render's outline, every third pixel, and which way it faces
    sr = ndimage.gaussian_filter(signed_distance(land), 2)
    gy_r, gx_r = np.gradient(sr)
    ry, rx = np.nonzero(land & ~ndimage.binary_erosion(land))
    ry, rx = ry[::3], rx[::3]
    facing = np.stack([gx_r[ry, rx], gy_r[ry, rx]], 1)
    facing /= np.linalg.norm(facing, axis=1, keepdims=True) + 1e-9

    def overlap(m):
        return (land & m).sum() / (land | m).sum()

    for round_ in range(ROUNDS + 1):
        laid = cv2.remap(paint, map_x, map_y, cv2.INTER_LINEAR, borderValue=0)
        painted = outline_land(laid)
        print(f"round {round_}: the outlines overlap {overlap(painted):.3f}", flush=True)
        if round_ == ROUNDS:
            break
        edge = painted & ~ndimage.binary_erosion(painted)
        distance, (iy, ix) = ndimage.distance_transform_edt(~edge, return_indices=True)
        sp = ndimage.gaussian_filter(signed_distance(painted), 2)
        gy_p, gx_p = np.gradient(sp)
        ty, tx = iy[ry, rx], ix[ry, rx]
        theirs = np.stack([gx_p[ty, tx], gy_p[ty, tx]], 1)
        theirs /= np.linalg.norm(theirs, axis=1, keepdims=True) + 1e-9
        ok = (distance[ry, rx] < REACH) & ((facing * theirs).sum(1) > 0.6)
        shift_x, shift_y, weight = (np.zeros((height, width), np.float32) for _ in range(3))
        np.add.at(shift_x, (ry[ok], rx[ok]), (tx - rx)[ok])
        np.add.at(shift_y, (ry[ok], rx[ok]), (ty - ry)[ok])
        np.add.at(weight, (ry[ok], rx[ok]), 1)
        shift_x, shift_y, weight = (cv2.GaussianBlur(m, (0, 0), SMOOTH) for m in (shift_x, shift_y, weight))
        # Away from any outline the bend fades to nothing
        weight += weight.max() * 0.02
        ux, uy = shift_x / weight, shift_y / weight
        map_x, map_y = (cv2.remap(m, xx + ux, yy + uy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                        for m in (map_x, map_y))

    # The grid's last row and column at or past the frame's edge (taken at the edge: the bend is nothing there)
    rows = np.minimum(np.arange(int(np.ceil((height - 1) / STEP)) + 1) * STEP, height - 1)
    cols = np.minimum(np.arange(int(np.ceil((width - 1) / STEP)) + 1) * STEP, width - 1)
    grid = np.ix_(rows, cols)
    with open(os.path.join(B.SOURCE_DIR, "island_warp.json"), "w", newline="\n") as fh:
        json.dump(dict(size=[width, height], step=STEP,
                       x=np.round(map_x[grid], 1).tolist(), y=np.round(map_y[grid], 1).tolist()), fh,
                  separators=(",", ":"))
        fh.write("\n")
    print("wrote port/source/island_warp.json", flush=True)


if __name__ == "__main__":
    main()

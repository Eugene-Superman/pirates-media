"""One-off: where the port's buildings are, and the Poly Haven models' sizes (for build_harbour.py)"""
import json
import math
import os
import sys
import traceback
import urllib.request

import bpy
from mathutils import Vector

ASSETS = r"C:\Users\bessu\Desktop\blender-assets"
PORT = os.path.join(ASSETS, "port")
OUT = os.path.join(ASSETS, "frames", "harbour", "inspect.json")
MODELS = os.path.join(ASSETS, "models", "polyhaven")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "blender-assets"})
    return urllib.request.urlopen(req, timeout=120).read()


def model(asset, res):
    folder = os.path.join(MODELS, asset, res)
    files = json.loads(get(f"https://api.polyhaven.com/files/{asset}"))
    entry = files["gltf"][res]["gltf"]
    main = os.path.join(folder, os.path.basename(entry["url"]))
    if not os.path.exists(main):
        os.makedirs(folder, exist_ok=True)
        for rel, inc in entry.get("include", {}).items():
            path = os.path.join(folder, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(get(inc["url"]))
        with open(main, "wb") as fh:
            fh.write(get(entry["url"]))
        print("downloaded", asset, flush=True)
    return main


try:
    bpy.ops.wm.open_mainfile(filepath=os.path.join(PORT, "port.blend"))
    sys.path.insert(0, PORT)
    src = open(os.path.join(PORT, "build_port.py"), encoding="utf-8").read()
    src = src.replace("\nmain()\n", "\n")
    ns = {"__file__": os.path.join(PORT, "build_port.py"), "__name__": "build_port"}
    exec(compile(src, "build_port.py", "exec"), ns)
    P = type("P", (), ns)
    H = P.H
    out = {}
    def world(u, v, z):
        p = P.TURN @ Vector((u, v, z))
        return [round(p.x, 2), round(p.y, 2), round(p.z, 2)]
    spots = {}
    for name, share in (("tavern", 0.37), ("workshop", 0.63)):
        p, angle = P.along_line(H["quay"], H["quay_inland"], share, P.FIRST_ROW - 0.5)
        spots[name] = dict(uv=[float(p[0]), float(p[1])], z=float(P.ground_z(p[0], p[1])[0]), angle=angle)
    spots["market"] = dict(uv=[P.SQUARE["u"], P.SQUARE["v"]], z=float(P.ground_z(P.SQUARE["u"], P.SQUARE["v"])[0]))
    cu, cv, n = P.coast_point(168, 1)
    import numpy as np
    down = np.array([n[0], n[1]])
    start = np.array([cu, cv]) - down * 30
    mid = start + down * 13
    spots["shipyard"] = dict(uv=[float(mid[0]), float(mid[1])], z=float(P.ground_z(mid[0], mid[1])[0]))
    fx, fy = H["walls"][1]["line"][-1]
    spots["arsenal"] = dict(uv=[float(fx), float(fy)], z=P.WALL_HEIGHT + 7)
    lx, ly = H["walls"][0]["line"][-1]
    spots["lighthouse"] = dict(uv=[float(lx), float(ly)], z=P.WALL_HEIGHT + 29)
    spots["keep"] = dict(uv=[P.CASTLE["u"] + 6, P.CASTLE["v"] + 10], z=P.CASTLE_Z + 28)
    for share in (0.2, 0.3, 0.42, 0.58, 0.7, 0.8):
        p, _ = P.along_line(H["bay"], H["inland"], share, P.FIRST_ROW + P.ROW_STEP)
        spots[f"row2_{share}"] = dict(uv=[float(p[0]), float(p[1])], z=float(P.ground_z(p[0], p[1])[0]))
    p, _ = P.along_line(H["bay"], H["inland"], 0.7, P.FIRST_ROW + 2 * P.ROW_STEP + 4)
    spots["church"] = dict(uv=[float(p[0]), float(p[1])], z=float(P.ground_z(p[0], p[1])[0]))
    for k, v in spots.items():
        v["world"] = world(v["uv"][0], v["uv"][1], v["z"])
    out["spots"] = spots
    out["walls"] = [[[round(float(a), 1) for a in q] for q in w["line"][::3]] for w in H["walls"]]
    out["quay"] = [[round(float(a), 1) for a in q] for q in H["quay"][::4]]
    out["bay"] = [[round(float(a), 1) for a in q] for q in H["bay"][::4]]
    out["mooring"] = [float(a) for a in H["mooring"]]
    objs = {}
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.startswith("PortRubble") or o.name.startswith("PortPlant"):
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        objs[o.name] = [[round(min(p[i] for p in pts), 1) for i in range(3)], [round(max(p[i] for p in pts), 1) for i in range(3)]]
    out["objects"] = objs
    out["object_count"] = len(bpy.data.objects)
    out["scenes"] = [s.name for s in bpy.data.scenes]
    # The models
    sizes = {}
    for asset, res in (("dutch_ship_large_01", "2k"), ("dutch_ship_large_02", "2k"), ("dutch_ship_medium", "2k"),
                       ("ship_pinnace", "1k")):
        path = model(asset, res)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=path)
        new = [o for o in bpy.data.objects if o not in before]
        pts = []
        for o in new:
            if o.type == "MESH":
                pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
        sizes[asset] = dict(objects=len(new), names=[o.name for o in new][:12],
                            lo=[round(min(p[i] for p in pts), 2) for i in range(3)],
                            hi=[round(max(p[i] for p in pts), 2) for i in range(3)])
    out["models"] = sizes
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    print("INSPECT DONE", flush=True)
except Exception:
    print("ERROR\n" + traceback.format_exc(), flush=True)

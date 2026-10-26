"""Renders some damage stages of the ship in the open .blend in a background Blender, with no timers and no save:
blender --background <ship>.blend --python render_job.py, with SHIP_STAGES="3,4" (and SHIP_VARIANTS="nets,pots" for a
ship with looks: every look by default). A scratch helper, run from frames/"""

import importlib.util
import os
import sys
import time
import traceback

import bpy

A = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # blender-assets
sys.path.insert(0, A)
import render_sprites as rs  # noqa: E402

stages = [int(s) for s in os.environ["SHIP_STAGES"].split(",")]
spec = importlib.util.spec_from_file_location("ship_build", os.path.join(rs.SHIP_DIR, "build.py"))
ship_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ship_build)
looks = list(getattr(ship_build, "VARIANT_NAMES", ()))
if looks and os.environ.get("SHIP_VARIANTS"):
    looks = os.environ["SHIP_VARIANTS"].split(",")
tag = "_".join(map(str, stages)) + ("_" + "_".join(looks) if os.environ.get("SHIP_VARIANTS") else "")
log = os.path.join(A, "frames", f"render_job_{tag}.log")
rs.SHADOW = getattr(ship_build, "SHADOW", True)
try:
    for variant, stage in [(v, s) for v in looks or [None] for s in stages]:
        start = time.time()
        if variant:
            ship_build.build(stage, variant)
        else:
            ship_build.build(stage)
        rs.set_stage(stage, variant)
        rs.ANIMATIONS = ship_build.animations(stage) if hasattr(ship_build, "animations") else None
        info = rs.setup_scene()
        rs.render_frames()
        rs.build_atlas(info)
        with open(log, "a") as fh:
            fh.write(f"{variant + '/' if variant else ''}{rs.NAME} done in {time.time() - start:.0f}s\n")
    with open(log, "a") as fh:
        fh.write("ALL DONE\n")
except Exception:
    with open(log, "a") as fh:
        fh.write("ERROR\n" + traceback.format_exc())
bpy.ops.wm.quit_blender()

"""Renders a few frames of a ship's stage in a background Blender, to look at before a whole render: blender --background
<ship>.blend --python preview_job.py, with SHIP_STAGES="0" and PREVIEW_DIRS="8,40" (directions). Every animation
frame from those directions goes to the stage's frames folder; no atlas. A scratch helper, run from frames/"""

import importlib.util
import os
import sys
import traceback

import bpy

A = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # blender-assets
sys.path.insert(0, A)
import render_sprites as rs  # noqa: E402

stage = int(os.environ["SHIP_STAGES"].split(",")[0])
dirs = {int(d) for d in os.environ.get("PREVIEW_DIRS", "8").split(",")}
log = os.path.join(A, "frames", "preview_job.log")
spec = importlib.util.spec_from_file_location("ship_build", os.path.join(rs.SHIP_DIR, "build.py"))
ship_build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ship_build)
rs.SHADOW = getattr(ship_build, "SHADOW", True)
try:
    ship_build.build(stage)
    rs.set_stage(stage)
    rs.ANIMATIONS = ship_build.animations(stage) if hasattr(ship_build, "animations") else None
    rs.setup_scene()
    only = {i for i, (_, direction, _) in enumerate(rs.frame_jobs()) if direction in dirs}
    rs.render_frames(only)
    with open(log, "a") as fh:
        fh.write(f"{rs.NAME} preview done: {len(only)} frames in {rs.FRAMES_DIR}\n")
except Exception:
    with open(log, "a") as fh:
        fh.write("ERROR\n" + traceback.format_exc())
bpy.ops.wm.quit_blender()

"""
Renders the sprite atlases of every damage stage of the ship in the open .blend, one after another.

Run in Blender with a ship's .blend open (ships/<line>/<ship>/<ship>.blend):
Scripting tab -> Open -> render_stages.py (from the blender-assets root) -> Run Script.
Blender stays usable between frames; progress is printed to the system console.

The ship's folder must have a build.py with build(stage) and DAMAGE_STAGES (see ships/starter/sloop/build.py);
a ship without damage stages gets the intact atlas only. Atlases go where render_sprites.py puts them:
canvas/public/sprites/ships/<line>/<ship>/intact, minor, heavy, burning, sinking (.webp + .json).
A ship with several looks (VARIANT_NAMES in its build.py, build(stage, variant)) gets every stage of every look, each
look in a folder of its own: canvas/public/sprites/ships/<line>/<ship>/<look>/intact, ...
The environment variables SHIP_STAGES ("0,4") and SHIP_VARIANTS ("nets") render only some of them.
An animated ship (animations(stage) or ANIMATIONS in its build.py, see ships/monsters/seaTurtle/build.py) gets every
frame of its animations from every direction in each stage's atlas.
At the end the first look's intact ship is rebuilt and the file is saved.
"""

import importlib
import importlib.util
import os
import sys
import time
import traceback

import bpy

SHIP_DIR = os.path.dirname(bpy.data.filepath)


def assets_root(ship_dir):
    """blender-assets itself: the parent of the "ships" (or "loot") folder this model lives in"""
    path = os.path.abspath(ship_dir)
    while os.path.basename(path) not in ("ships", "loot"):
        parent = os.path.dirname(path)
        if parent == path:
            raise RuntimeError(f"{ship_dir} is not inside blender-assets/ships/<line>/<ship>/ (or loot/<thing>/)")
        path = parent
    return os.path.dirname(path)


ASSETS_DIR = assets_root(SHIP_DIR)
if ASSETS_DIR not in sys.path:
    sys.path.insert(0, ASSETS_DIR)

import render_sprites  # noqa: E402

importlib.reload(render_sprites)
rs = render_sprites

# Every ship's script is called build.py, so it is loaded by path under its own module name
_spec = importlib.util.spec_from_file_location("ship_build", os.path.join(SHIP_DIR, "build.py"))
ship_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ship_build)

rs.SHADOW = getattr(ship_build, "SHADOW", True)
STAGE_COUNT = len(getattr(ship_build, "DAMAGE_STAGES", [None]))
STAGES = [int(s) for s in os.environ.get("SHIP_STAGES", ",".join(map(str, range(STAGE_COUNT)))).split(",")]
ALL_VARIANTS = list(getattr(ship_build, "VARIANT_NAMES", ()))
VARIANTS = os.environ["SHIP_VARIANTS"].split(",") if ALL_VARIANTS and os.environ.get("SHIP_VARIANTS") else ALL_VARIANTS
JOBS = [(variant, stage) for variant in VARIANTS or [None] for stage in STAGES]

# The viewport shares the GPU with the render, so it shows plain Solid shading meanwhile
shading = {}
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            shading[area.as_pointer()] = area.spaces.active.shading.type
            area.spaces.active.shading.type = "SOLID"


def restore_shading():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D" and area.as_pointer() in shading:
                area.spaces.active.shading.type = shading[area.as_pointer()]


def build(stage, variant):
    if variant:
        ship_build.build(stage, variant)
    elif STAGE_COUNT > 1:
        ship_build.build(stage)
    else:
        ship_build.build()


# Progress is kept where other scripts (and the MCP bridge) can read it
state = {"jobs": JOBS, "job_pos": 0, "frame": 0, "done": False, "error": None, "started": time.time(), "log": []}
bpy.app.driver_namespace["ship_stages_state"] = state
info = {}


def animations(stage):
    if hasattr(ship_build, "animations"):
        return ship_build.animations(stage)
    return getattr(ship_build, "ANIMATIONS", None)


def start_stage():
    variant, stage = JOBS[state["job_pos"]]
    build(stage, variant)
    rs.set_stage(stage, variant)
    rs.ANIMATIONS = animations(stage)
    info.clear()
    info.update(rs.setup_scene())
    state["frame"] = 0


def step():
    try:
        with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
            if state["frame"] == 0 and not info:
                start_stage()
            if state["frame"] < len(rs.frame_jobs()):
                rs.render_frames(only=[state["frame"]])
                state["frame"] += 1
                return 0.05
            rs.build_atlas(info)
            broken = [i for i in range(len(rs.frame_jobs())) if rs.frame_looks_broken(rs.frame_path(i))]
            variant = JOBS[state["job_pos"]][0]
            atlas = f"{variant}/{rs.NAME}" if variant else rs.NAME
            state["log"].append({"atlas": atlas, "broken": broken, "t": round(time.time() - state["started"], 1)})
            print(f"{atlas}: done, broken frames: {broken}", flush=True)
            state["job_pos"] += 1
            info.clear()
            if state["job_pos"] < len(JOBS):
                start_stage()
                return 0.05
            # Leave the file with the intact ship
            first = VARIANTS[0] if VARIANTS else None
            build(0, first)
            rs.set_stage(0, first)
            rs.ANIMATIONS = animations(0)
            rs.setup_scene()
            bpy.ops.wm.save_mainfile()
            state["done"] = True
            restore_shading()
            return None
    except Exception:
        state["error"] = traceback.format_exc()
        print(state["error"], flush=True)
        restore_shading()
        return None


bpy.app.timers.register(step, first_interval=0.5)

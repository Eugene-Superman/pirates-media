"""
Renders the sprite atlases of every damage stage of the ship in the open .blend, one after another.

Run in Blender with a ship's .blend open (ships/<line>/<ship>/<ship>.blend):
Scripting tab -> Open -> render_stages.py (from the blender-assets root) -> Run Script.
Blender stays usable between frames; progress is printed to the system console.

The ship's folder must have a build.py with build(stage) and DAMAGE_STAGES (see ships/starter/sloop/build.py);
a ship without damage stages gets the intact atlas only. Atlases go where render_sprites.py puts them:
canvas/public/sprites/ships/<line>/<ship>/intact, minor, heavy, burning, sinking (.webp + .json).
At the end the intact ship is rebuilt and the file is saved.
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
    """blender-assets itself: the parent of the "ships" folder this ship lives in"""
    path = os.path.abspath(ship_dir)
    while os.path.basename(path) != "ships":
        parent = os.path.dirname(path)
        if parent == path:
            raise RuntimeError(f"{ship_dir} is not inside blender-assets/ships/<line>/<ship>/")
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

STAGE_COUNT = len(getattr(ship_build, "DAMAGE_STAGES", [None]))
STAGES = [int(s) for s in os.environ.get("SHIP_STAGES", ",".join(map(str, range(STAGE_COUNT)))).split(",")]

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


def build(stage):
    if STAGE_COUNT > 1:
        ship_build.build(stage)
    else:
        ship_build.build()


# Progress is kept where other scripts (and the MCP bridge) can read it
state = {"stage_list": STAGES, "stage_pos": 0, "frame": 0, "done": False, "error": None, "started": time.time(), "log": []}
bpy.app.driver_namespace["ship_stages_state"] = state
info = {}


def start_stage():
    stage = STAGES[state["stage_pos"]]
    build(stage)
    rs.set_stage(stage)
    info.clear()
    info.update(rs.setup_scene())
    state["frame"] = 0


def step():
    try:
        with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
            if state["frame"] == 0 and not info:
                start_stage()
            if state["frame"] < rs.DIRECTIONS:
                rs.render_frames(only=[state["frame"]])
                state["frame"] += 1
                return 0.05
            rs.build_atlas(info)
            broken = [i for i in range(rs.DIRECTIONS) if rs.frame_looks_broken(rs.frame_path(i))]
            state["log"].append({"atlas": rs.NAME, "broken": broken, "t": round(time.time() - state["started"], 1)})
            print(f"{rs.NAME}: done, broken frames: {broken}", flush=True)
            state["stage_pos"] += 1
            info.clear()
            if state["stage_pos"] < len(STAGES):
                start_stage()
                return 0.05
            # Leave the file with the intact ship
            build(0)
            rs.set_stage(0)
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

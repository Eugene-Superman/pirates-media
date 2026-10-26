"""
The Smuggler Baron's ship (line "bots", game class "baronBrig"): the starting waters' boss. The smuggler sloop
(../smugglerSloop/build.py) made bigger, to the boss's hull (src/game/ships/shipClasses.ts, baronBrig: bow 22, stern
-20.5, half-beam 7.6), with blood-red sails, the Baron's red flag with a gold skull, a cannon at each of his two gun
slots on both sides, and his mortar on the foredeck.

Everything else is the smuggler's: a change to it shows here too. Built by ../bot_sloop.py (open baronBrig.blend, run
this file); render_stages.py renders every stage.
"""

import importlib.util
import os

import bpy


def _smuggler():
    here = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
    path = os.path.join(os.path.dirname(here), "smugglerSloop", "build.py")
    spec = importlib.util.spec_from_file_location("smuggler_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smuggler = _smuggler()
bot_sloop = smuggler.bot_sloop

# How much bigger than the smuggler, along x (to the bow), y (across) and z (up): its hull to the boss's
SCALE = (22 / 15.5, 7.6 / 5.8, 1.35)
SPEC = dict(
    smuggler.SPEC,
    name="baronBrig",
    scale=SCALE,
    # The class's two cannon slots (x -3 and 6), before the stretch
    gun_x=(-3 / SCALE[0], 6 / SCALE[0]),
    mortar=(7.2, 0.0),
)
# prettier-ignore
LOOKS = {
    "baron": dict(smuggler.LOOKS["smuggler"], sail=0x8E2320, flag=dict(kind="skull", field=0x8A1A12, mark=0xF2D24B),
                  cargo="hold"),
}
DAMAGE_STAGES = bot_sloop.DAMAGE_STAGES


def build(damage=None):
    return bot_sloop.build(SPEC, LOOKS, damage)


if __name__ == "__main__":
    build()

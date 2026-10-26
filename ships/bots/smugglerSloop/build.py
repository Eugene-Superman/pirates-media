"""
Smuggler sloop (line "bots", game class "smugglerSloop"): the aggressive bots of the starting waters and the Smuggler
Baron's escort. Long, low and black with a red stripe, a raked mast with dark sails (a gaff mainsail, a gaff topsail,
a jib and a flying jib on a long bowsprit), a cannon a side over the low bulwark, kegs and a tarpaulin over what it
runs, a black flag with a skull, and no lights.

The hull, rig and damage stages are built by ../bot_sloop.py from the SPEC below (open smugglerSloop.blend, run this
file); render_stages.py renders every stage. Its size is the game's (src/game/ships/shipClasses.ts, smugglerSloop:
bow 15.5, stern -14.5, half-beam 5.8; the cannon's slot at x -1).
"""

import importlib
import os
import sys

import bpy


def _bots_dir():
    here = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
    return os.path.dirname(here)


if _bots_dir() not in sys.path:
    sys.path.insert(0, _bots_dir())
import bot_sloop  # noqa: E402

importlib.reload(bot_sloop)

# Lengths in game units; sail corners as (forward of the mast, height)
# prettier-ignore
SPEC = dict(
    name="smugglerSloop", bow=15.5, stern=-14.5, beam=5.8, keel=-1.6, deck=3.3, bulwark=0.95, sheer_bow=0.7,
    sheer_stern=0.35, stem_rake=0.55, transom_rake=0.35,
    mast_x=1.0, rake=0.09, mast_top=24.6,
    main=dict(tack=(-0.3, 4.9), throat=(-0.3, 15.5), peak=(-11.0, 21.0), clew=(-14.0, 5.3)),
    topsail=dict(kind="gaff"),
    jibs=[dict(top=16.0, end=0.75, a=0.1, b=0.92, clew=(4.2, 1.7, 6.6)),
          dict(top=22.5, end=1.0, a=0.18, b=0.95, clew=(7.5, 1.6, 9.0))],
    bowsprit=9.0, hatch_x=3.6, house=None,
    gun="cannon", gun_x=-1.0, gun_z=4.6, flag_at="masthead", pennant=False, lantern=False,
)
# prettier-ignore
LOOKS = {
    "smuggler": dict(hull=("black_painted_planks", None, (0.5, 1.0, 1.2)), stripe=0xB03A2E, sail=0x3A3A40,
                     deck_value=0.95, flag=dict(kind="skull", field=0x141414, mark=0xF2F2F2), cargo="kegs"),
}
DAMAGE_STAGES = bot_sloop.DAMAGE_STAGES


def build(damage=None):
    return bot_sloop.build(SPEC, LOOKS, damage)


if __name__ == "__main__":
    build()

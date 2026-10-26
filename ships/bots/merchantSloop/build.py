"""
Merchant sloop (line "bots", game class "merchantSloop"): the traders of the starting waters, neutral bots with a
swivel gun on each rail. A gaff mainsail with a square topsail over it and a jib, a deckhouse aft, a boat on deck and
its cargo before and abaft the mast. Two looks (VARIANTS): "crates", varnished with a blue stripe, white sails and a
blue ensign, crates and barrels; "bales", grey planks with a red stripe, tanned sails and a green flag, bales and sacks.

The hull, rig and damage stages are built by ../bot_sloop.py from the SPEC below (open merchantSloop.blend, run this
file); render_stages.py renders every look at every stage. Its size is the game's (src/game/ships/shipClasses.ts,
merchantSloop: bow 14.5, stern -13.8, half-beam 5.6; the swivel gun's slot on the rail at x 1).
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
    name="merchantSloop", bow=14.5, stern=-13.8, beam=5.6, keel=-1.5, deck=3.1, bulwark=1.1, sheer_bow=1.0,
    sheer_stern=0.6, stem_rake=0.5, transom_rake=0.3,
    mast_x=1.5, rake=0.02, mast_top=23.5,
    main=dict(tack=(-0.4, 4.9), throat=(-0.4, 14.5), peak=(-9.5, 19.0), clew=(-12.6, 5.2)),
    topsail=dict(kind="square", lo=15.8, hi=22.2, half_lo=4.8, half_hi=3.8),
    jibs=[dict(top=15.5, end=1.0, a=0.12, b=0.92, clew=(4.6, 1.8, 6.4))],
    bowsprit=6.5, hatch_x=-3.6, house=dict(x0=-11.4, x1=-7.8, half=2.4, h=1.8),
    gun="swivel", gun_x=1.0, gun_z=4.2, flag_at="gaff", pennant=True, lantern=True,
)
# hull: (Poly Haven set, paint over it or None, hue/saturation/value)
# prettier-ignore
VARIANTS = {
    "crates": dict(hull=("wood_floor_deck", None, (0.52, 0.85, 0.8)), stripe=0x2E5F8A, sail=0xF2EAD8,
                   flag=dict(kind="cross", field=0x2E6FC0, mark=0xF2EEE4), pennant=0x2E6FC0, cargo="crates", boat=True),
    "bales": dict(hull=("weathered_brown_planks", None, (0.5, 1.0, 0.9)), stripe=0x9E3B2B, sail=0xE3CFA0,
                  sail_band=(0.62, 0.72, 0x9E3B2B), flag=dict(kind="band", field=0x2F7A43, mark=0xF0C649),
                  pennant=0x2F7A43, cargo="bales", boat=False),
}
VARIANT_NAMES = tuple(VARIANTS)
DAMAGE_STAGES = bot_sloop.DAMAGE_STAGES


def build(damage=None, variant=None):
    return bot_sloop.build(SPEC, VARIANTS, damage, variant)


if __name__ == "__main__":
    build()

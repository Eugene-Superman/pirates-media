"""
The game's sounds, made from free recordings (CC0, see CREDITS.md) in sounds/source/, written to canvas/public/sounds/
as mono mp3s. Every sound the game plays is listed in SOUNDS below with what it is made of.

Run it in Blender (Scripting -> Open -> Run Script; Blender reads and writes the audio itself) or with any Python that
has numpy, with ffmpeg on the PATH: python build_sounds.py (ffmpeg is used whenever it is there). It takes a few
seconds and doesn't touch the open scene.

Only edits, nothing synthesised: each sound is cut to start right at its attack (no delay when the game plays it),
layered, played lower or higher (like a tape: slower is lower), filtered, faded out, mixed down to mono and brought to
the same peak level; the game sets how loud each one plays (its `level` in SOUNDS, client/audio/Sounds.ts).
"""

import os

import numpy as np

RATE = 44100
BITRATE = 128000  # bits per second of the mp3s
PEAK = 10 ** (-1 / 20)  # every sound peaks at -1 dBFS; the game sets the loudness of each
ONSET = 0.05  # share of a sound's peak where its attack starts; the cut is a few milliseconds before it
PRE_ROLL = 0.003  # seconds kept before the attack

try:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # pasted into Blender's console
    _SCRIPT_DIR = os.getcwd()


def _blender_script_dir():
    try:
        import bpy

        for text in bpy.data.texts:
            if text.filepath and os.path.basename(text.filepath) == "build_sounds.py":
                return os.path.dirname(bpy.path.abspath(text.filepath))
    except ImportError:
        pass
    return None


SOUNDS_DIR = _blender_script_dir() or _SCRIPT_DIR
SOURCE_DIR = os.environ.get("SOUND_SOURCES") or os.path.join(SOUNDS_DIR, "source")
OUT_DIR = os.environ.get("GAME_SOUNDS") or os.path.normpath(
    os.path.join(SOUNDS_DIR, "..", "..", "canvas", "public", "sounds")
)


def _has_aud():
    """Blender's audio library, unless ffmpeg is on the PATH (it reads and writes more formats)"""
    import shutil

    if shutil.which("ffmpeg"):
        return False
    try:
        import aud  # noqa: F401

        return True
    except ImportError:
        return False


_cache = {}


def load(name):
    """A source file as mono float samples at RATE"""
    if name in _cache:
        return _cache[name].copy()
    path = os.path.join(SOURCE_DIR, name)
    if _has_aud():
        import aud

        data = aud.Sound(path).resample(RATE).data()
        x = np.asarray(data, np.float32).mean(axis=1)
    else:
        import subprocess

        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
            capture_output=True,
            check=True,
        ).stdout
        x = np.frombuffer(raw, np.float32).copy()
    _cache[name] = x
    return x.copy()


def save(name, x, bitrate=BITRATE):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    if _has_aud():
        import aud

        sound = aud.Sound.buffer(x.reshape(-1, 1).astype(np.float32), RATE)
        sound.write(path, rate=RATE, channels=aud.CHANNELS_MONO, container=aud.CONTAINER_MP3, codec=aud.CODEC_MP3, bitrate=bitrate)
        return
    import subprocess

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "-", "-b:a", str(bitrate), path],
        input=x.astype(np.float32).tobytes(),
        check=True,
    )


# ---------------------------------------------------------------------------
# Edits
# ---------------------------------------------------------------------------


def cut(x, start, length=None):
    """The part from `start` seconds, `length` seconds long (to the end without one): one take of a recording of many"""
    a = int(start * RATE)
    return x[a : a + int(length * RATE)] if length else x[a:]


def from_attack(x):
    """Cut so the sound starts right at its attack"""
    start = int(np.argmax(np.abs(x) > np.abs(x).max() * ONSET))
    return x[max(0, start - int(PRE_ROLL * RATE)) :]


def norm(x, level=1.0):
    return x * (level / max(np.abs(x).max(), 1e-9))


def finish(x, length, fade):
    """Cut to length, fade out the last `fade` seconds (a half cosine), bring the peak to PEAK"""
    x = x[: int(length * RATE)].copy()
    n = min(len(x), int(fade * RATE))
    x[len(x) - n :] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, n))
    return norm(x, PEAK)


def speed(x, factor):
    """Played at `factor` of its speed, like a tape: slower is lower"""
    t = np.arange(0, len(x) - 1, factor)
    return np.interp(t, np.arange(len(x)), x).astype(np.float32)


def _filter(x, cutoff, keep_low):
    """A gentle filter in the frequency domain: what is beyond `cutoff` Hz fades out over an octave"""
    n = len(x)
    spectrum = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / RATE)
    octaves = np.log2(np.maximum(f, 1) / cutoff)
    gain = np.clip(0.5 - octaves, 0, 1) if keep_low else np.clip(0.5 + octaves, 0, 1)
    return np.fft.irfft(spectrum * gain, n).astype(np.float32)


def lowpass(x, cutoff):
    return _filter(x, cutoff, True)


def highpass(x, cutoff):
    return _filter(x, cutoff, False)


def mix(*layers):
    """Layers of (sound, level, delay in seconds) laid over each other; each layer's peak brought to its level"""
    length = max(int(delay * RATE) + len(x) for x, _, delay in layers)
    out = np.zeros(length, np.float32)
    for x, level, delay in layers:
        a = int(delay * RATE)
        out[a : a + len(x)] += norm(x, level)
    return out


def take(name, *edits):
    """A source file from its attack, then each edit applied in turn"""
    x = from_attack(load(name))
    for edit in edits:
        x = edit(x)
    return x


# ---------------------------------------------------------------------------
# The game's sounds
# ---------------------------------------------------------------------------

THIMRAS = "oga_thimras_"
INDIE = "oga_independentnu_"
DUCK = "oga_rubberduck_"
KENNEY = "oga_kenney_"


def harpoon():
    """The harpoon gun: a crossbow's snap played lower, a dull thud of wood under it for weight, the bolt's whoosh after"""
    snap = speed(from_attack(cut(load("oga_stillnorth_crossbow_shoot.flac"), 1.40, 0.42)), 0.82)
    thud = lowpass(take(INDIE + "impactwood14.flac"), 220)
    whoosh = speed(from_attack(cut(load("oga_stillnorth_crossbow_bolt_pass.flac"), 0.50, 0.55)), 0.9)
    return finish(mix((snap, 1.0, 0), (thud, 0.55, 0), (whoosh, 0.35, 0.035)), 0.75, 0.3)


def hit_wood_mix():
    """A lighter hit for variety: a plank's crack over a heavy knock"""
    return finish(mix((take(INDIE + "impactwood14.flac"), 1.0, 0), (take(INDIE + "crack10.flac"), 0.7, 0.01)), 0.8, 0.35)


def hit_flesh(splat, cry, cry_speed, cry_level):
    """A harpoon or a ball in a monster: a wet thud and the beast's grunt of pain, low"""
    wet = take(INDIE + splat)
    grunt = speed(take(DUCK + cry), cry_speed)
    return finish(mix((wet, 1.0, 0), (grunt, cry_level, 0.03)), 0.8, 0.3)


def bite():
    """A monster's jaws in a hull: the crunch of planks, a crack, and a deep growl"""
    crunch = take(INDIE + "impactcrunch04.flac")
    growl = speed(take(DUCK + "monster_04.ogg"), 0.85)
    crack = take(INDIE + "crack10.flac")
    return finish(mix((crunch, 1.0, 0), (growl, 0.8, 0), (crack, 0.5, 0.05)), 1.1, 0.4)


def chest_open():
    """A chest hauled aboard and opened: it thumps on the deck, the latch clicks, the coins in it ring"""
    return finish(
        mix(
            (take(KENNEY + "dropLeather.ogg"), 1.0, 0),
            (take(KENNEY + "metalLatch.ogg"), 0.7, 0.08),
            (take(KENNEY + "handleCoins.ogg"), 0.9, 0.15),
        ),
        1.0,
        0.3,
    )


def cargo():
    """Crates of goods hauled aboard: a thump and a creak"""
    return finish(mix((take(KENNEY + "dropLeather.ogg"), 1.0, 0), (take(KENNEY + "creak3.ogg"), 0.6, 0.05)), 0.5, 0.15)


def equip():
    """A gun or a piece of outfit fitted: a heavy latch and a click"""
    return finish(mix((take(KENNEY + "metalLatch.ogg"), 1.0, 0), (take(KENNEY + "metalClick.ogg"), 0.7, 0.05)), 0.45, 0.15)


def gull(n):
    """A gull's cry, its wind rumble filtered out"""
    x = highpass(take(f"oga_rangomango_seagull_ambient_{n}.wav"), 350)
    return finish(x, len(x) / RATE, 0.15)


def sea():
    """The sea round the ship: waves lapping, softened. Played over and over by the game, crossfading into itself"""
    x = load("oga_randommind_vistula_waves_cut.mp3")
    x = lowpass(highpass(x, 120), 2800)
    return finish(x, 40.0, 1.0)


# name -> how it is made; a name ending in a number is one of the variants the game picks from at random
SOUNDS = {
    # Weapons
    "cannon": lambda: finish(take(THIMRAS + "cannon_fire.ogg"), 2.6, 0.9),
    "harpoon": harpoon,
    # What a shot does: a hull hit, a monster hit, the sea
    "hit_wood_1": lambda: finish(take(THIMRAS + "cannon_hit_ship_short.ogg"), 1.0, 0.55),
    "hit_wood_2": lambda: finish(take(THIMRAS + "cannon_hit.ogg"), 1.0, 0.55),
    "hit_wood_3": hit_wood_mix,
    "hit_flesh_1": lambda: hit_flesh("impactsplat04.flac", "grunt_02.ogg", 0.75, 0.5),
    "hit_flesh_2": lambda: hit_flesh("impactsplat03.flac", "monster_06.ogg", 0.8, 0.4),
    "splash": lambda: finish(take(THIMRAS + "cannon_miss.ogg"), 1.3, 0.5),
    # Monsters: a bite, a growl as one goes for the player, its roar as it dies
    "bite": bite,
    "growl": lambda: finish(speed(take(DUCK + "monster_07.ogg"), 0.72), 1.2, 0.4),
    "roar": lambda: finish(take("oga_trazzz123_monster_roar.wav"), 2.8, 1.2),
    # A ship going down
    "sink": lambda: finish(take(THIMRAS + "ship_destroyed_short.ogg"), 4.0, 1.6),
    # Loot
    "chest_drop": lambda: finish(take("oga_ezwa_water_splash_01.flac"), 0.9, 0.4),
    "chest_open": chest_open,
    "cargo": cargo,
    "coins": lambda: finish(take(KENNEY + "handleCoins.ogg"), 0.85, 0.2),
    "coins_small": lambda: finish(take(KENNEY + "handleCoins2.ogg"), 0.34, 0.1),
    # Jingles: a level reached, a bot sunk, a quest turned in, a step of the Captain's path
    "level_up": lambda: finish(take(KENNEY + "jingles_STEEL02.ogg"), 2.0, 0.3),
    "victory": lambda: finish(take(KENNEY + "jingles_STEEL09.ogg"), 1.2, 0.2),
    "quest_done": lambda: finish(take(KENNEY + "jingles_STEEL11.ogg"), 1.2, 0.2),
    "path_step": lambda: finish(take(KENNEY + "jingles_STEEL15.ogg"), 1.2, 0.2),
    # The HUD and the port
    "click": lambda: finish(take(KENNEY + "click3.wav"), 0.09, 0.03),
    "error": lambda: finish(take("oga_lokif_negative_2.wav"), 0.3, 0.1),
    "equip": equip,
    "quest": lambda: finish(take(KENNEY + "bookFlip2.ogg"), 0.43, 0.1),
    "talent": lambda: finish(take("oga_lokif_positive.wav"), 1.2, 0.6),
    "bell": lambda: finish(take("oga_springspring_pleasing_bell.wav"), 0.62, 0.2),
    # The crew at work: a hammer knock a repair step
    "repair": lambda: finish(take(KENNEY + "chop.ogg"), 0.24, 0.08),
    # Round the ship: its timbers creaking, the gulls near the port, the sea
    "creak_1": lambda: finish(take(KENNEY + "creak1.ogg"), 0.66, 0.2),
    "creak_2": lambda: finish(take(KENNEY + "creak2.ogg"), 0.83, 0.2),
    "gull_1": lambda: gull(3),
    "gull_2": lambda: gull(4),
    "gull_3": lambda: gull(5),
    "gull_4": lambda: gull(6),
    "sea": sea,
}
SEA_BITRATE = 96000  # the long loop, quieter than the rest


def main():
    for name, make in SOUNDS.items():
        save(f"{name}.mp3", make(), SEA_BITRATE if name == "sea" else BITRATE)
    print(len(SOUNDS), "sounds ->", OUT_DIR, flush=True)


main()

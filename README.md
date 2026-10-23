# Ship art

Ships in the game are sprite atlases rendered in [Blender](https://www.blender.org/) (made with Blender 5.2).
The game (`canvas`, next to this folder) loads only the atlases; this folder is their source.

```
blender-assets/
  render_sprites.py      renders the ship in the open .blend: one atlas, its current damage stage
  render_stages.py       renders every damage stage of the ship in the open .blend, one after another
  textures/polyhaven/    scanned CC0 wood and metal from Poly Haven (polyhaven.com), shared by all ships
  ships/<line>/<ship>/   one folder per ship: <ship>.blend, build.py, its own textures/
    starter/sloop/       the Starter Sloop every player gets (game class "sloop")
  effects/fog/           fog.blend + build_fog.py: the fog of war's cloud puffs and mist
  effects/sea/           build_sea.py: the sea's wave maps and caustics
  effects/foam/          build_foam.py: foam for ships' wakes and the water round a wreck
  islands/               islands.blend + build_islands.py: the ten island shapes in five looks
  frames/                untrimmed render frames, kept for inspection; safe to delete
```

Lines are families of ships (starter, and later European, Eastern, pirate, northern, legendary): the plan and the
steps to add a ship are in the game repository, `docs/ships.md`. Folder names here are the game's ids:
`ships/starter/sloop/` renders into `canvas/public/sprites/ships/starter/sloop/`.

Scale and axes match the game: 1 Blender unit = 1 game unit, the bow points to +X, the waterline is at Z = 0.

## Damage stages

`build.py` builds one of the game's damage stages, picked by the scene's custom property `damage` (0–4):
`intact`, `minor`, `heavy`, `burning`, `sinking`; the atlases are named after them. For the sloop:
0 clean; 1 soot and a few sail holes; 2 hull holes, broken rail, torn sail; 3 charred hull and burnt sail
(the game adds the fire); 4 the mast down over the bow, listing, low in the water, debris (the game animates the sinking).

## Fog of war

Open `effects/fog/fog.blend`, Scripting → Open → `effects/fog/build_fog.py` → Run Script (about 20 seconds).
It renders six cloud puffs as volumes in Cycles, lit by the game's sun and seen at the game camera's pitch, makes a
seamless tile of thin mist from periodic noise, and writes `canvas/public/sprites/fog/`: `puffs.webp` + `puffs.json`
(a Pixi spritesheet, frames trimmed to the clouds) and `wisps.webp`. Shapes, density, light and the mist's look are
constants at the top of the script. The script rebuilds the scene of the open file, so run it only in `fog.blend`.

## Sea

Scripting → Open → `effects/sea/build_sea.py` → Run Script (a few seconds; any open file will do, the scene isn't
touched). It writes `canvas/public/sprites/sea/`: four seamless wave maps (`swell`, `wind`, `chop`, `ripples`) made from
an ocean wave spectrum with an FFT, and `caustics`. In a map, R and G are the water's slope and B how close it is to a
crest; the game's sea shader lights them. Wave lengths, steepness and choppiness are in `WAVES` at the top of the
script; how the game paints them (colors, tile sizes, foam) is in `canvas/src/client/scene/effects/seaStyles.ts`.
It also runs outside Blender with Python, numpy and Pillow: `python build_sea.py`.

## Foam

Scripting → Open → `effects/foam/build_foam.py` → Run Script (about half a minute; any open file will do). It writes
`canvas/public/sprites/foam/foam.webp`, one seamless tile: R a lace of bubble walls (edges of Voronoi cells of a few
sizes), G soft patches, B streaks drawn out along x. The game's wakes and the water round a sinking ship dissolve foam
by a threshold over these (`canvas/src/client/scene/effects/Wake.ts`, `Sinking.ts`), so thick foam thins out to a lace.
Bubble sizes and the patterns' scales are constants at the top of the script. It also runs outside Blender with
Python, numpy and Pillow: `python build_foam.py`.

## Islands

Open `islands/islands.blend`, Scripting → Open → `islands/build_islands.py` → Run Script. About 10 minutes on a
GTX 1060 for all 100 pictures; Blender stays usable between renders, progress is in the system console. To render a
few, set the environment variable `ISLAND_ONLY=tropical:bean,desert:cay` (look:shape) before starting Blender.

- `SHAPES`: the ten shapes. Each is a height field built from a coastline (radius by angle): sea floor, beach, land
  rising to a plateau with hills and cliffs. `radius` is the size; the game scales islands 0.85–1.15 times it.
- `LOOKS`: the five looks. Textures from Poly Haven (CC0; downloaded into `textures/polyhaven/` on the first run) for
  the sand, the land, patches on the land and the rock, with tile sizes and tints; the shallow water's colour; plant
  colours; and which plants grow where (shore, low land, high land, cliffs): palms, leafy trees, bushes, firs, dry
  scrub, dead trees, rocks — all made by the script.
- Output: `canvas/public/sprites/islands/<look>/<shape>_ground.webp` (the whole terrain with the sea floor, drawn under
  ships) and `_raised.webp` (land above the beach and the plants, drawn over a ship behind the island),
  `islands.json` (where the island's centre is in each picture), and `canvas/src/game/world/islandShapes.json` (the
  coastlines and heights the game logic uses for collisions and routes). Commit them together: a coastline must match
  its picture.
- Camera and sun are the game's, as for the ships: a change of `CAM_PITCH`/`CAM_YAW` needs a re-render here too.

## Changing a ship

1. Open its `.blend`, e.g. `ships/starter/sloop/sloop.blend`.
2. By hand: edit the objects in the `Ship` collection.
   By code: Scripting → Open → the ship's `build.py`, change the parameters, press Run Script
   (the `Ship` collection is rebuilt and manual edits in it are lost).
3. Save the `.blend`.
4. Scripting → Open → `render_stages.py` (from this folder) → Run Script. All five atlases take about 5 minutes
   on a GTX 1060; Blender stays usable, progress is in the system console. `render_sprites.py` renders only the
   current stage, and Blender freezes while it runs.
5. Reload the game page. Commit the new atlases in `canvas`; keep this folder's copy of the `.blend` in sync.

A frame that comes out with a black hull (Cycles sometimes loses a texture with persistent data on) is detected and
rendered again from scratch.

If you change the camera pitch or yaw (`CAMERA` in `canvas/src/client/scene/SceneView.ts`), update `CAM_PITCH` /
`CAM_YAW` in `render_sprites.py` and re-render every ship.

Blender backups (`*.blend1`), `frames/` and `__pycache__/` are not worth keeping if this folder becomes a git repository.
The Python scripts run inside Blender and are not covered by the game's `npm run check`.

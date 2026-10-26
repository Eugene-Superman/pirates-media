# Ship art

Ships in the game are sprite atlases rendered in [Blender](https://www.blender.org/) (made with Blender 5.2).
The game (`canvas`, next to this folder) loads only the atlases; this folder is their source.

```
blender-assets/
  render_sprites.py      renders the ship in the open .blend: one atlas, its current damage stage
  render_stages.py       renders every damage stage (and look) of the ship in the open .blend, one after another
  textures/polyhaven/    scanned CC0 wood and metal from Poly Haven (polyhaven.com), shared by all ships; a script
                         downloads a set it needs here on its first run
  ships/<line>/<ship>/   one folder per ship: <ship>.blend, build.py, its own textures/
    starter/sloop/       the Starter Sloop every player gets (game class "sloop")
    european/coastalBark/ the Coastal Bark, the European line's tier 1 (game class "coastalBark")
    bots/fishingBoat/    the bots' fishing boat, three looks (game class "fishingBoat")
    bots/merchantSloop/  the bots' merchant sloop, two looks (game class "merchantSloop")
    bots/smugglerSloop/  the bots' smuggler sloop (game class "smugglerSloop")
    bots/baronBrig/      the Smuggler Baron, the boss: the smuggler sloop made bigger, red sails (game class "baronBrig")
    bots/bot_sloop.py    what the sloops share: their hull, rig, damage; each build.py gives its SPEC and looks
    monsters/seaTurtle/  the giant turtle, a sea monster, animated: it swims and bites (game class "seaTurtle")
    monsters/seaSerpent/ the sea serpent: parts of it the game lays along its body, the head animated (game class
                         "seaSerpent")
  loot/chest/            chest.blend + build.py: the floating loot (a chest of gold, crates of goods, lost cargo)
  effects/fog/           fog.blend + build_fog.py: the fog of war's cloud puffs and mist
  effects/sea/           build_sea.py: the sea's wave maps, caustics and broad patches
  effects/sky/           build_clouds.py: the light clouds drifting over the sea
  effects/foam/          build_foam.py: foam for ships' wakes, the water round a wreck and the sea's whitecaps
  sounds/                build_sounds.py + source/: the game's sounds, cut from CC0 recordings (CREDITS.md)
  islands/               islands.blend + build_islands.py: the ten island shapes in five looks
  port/                  port.blend + build_port.py: the port (Saltwind Harbour), its island, town, castle and harbour;
                         layout.json (its geometry, from the game) and export_layout.mjs (which writes it);
                         build_port_art.py + align_port_art.py: the painting of it the game shows, laid on the
                         render (source/island.webp, source/render/);
                         build_harbour_art.py + source/: the picture of the harbour the game shows in port, and
                         its medallions, from painted art; build_harbour.py: the same rendered from port.blend
  models/polyhaven/      CC0 models from Poly Haven (ships, props) the harbour picture uses; downloaded on the first run
  icons/                 build_gun_icons.py, build_ammo_icons.py, build_outfit_icons.py, build_ship_icons.py +
                         source/: the arsenal's, the workshop's and the shipyard's icons, cut out of painted pictures
                         by cutout.py (which the port's art scripts use too)
  hud/                   build_minimap_frame.py, build_minimap_buttons.py, build_skill_bar.py,
                         build_skill_icons.py, build_chart_frame.py + source/: the minimap's painted frame and the
                         buttons in its slots, the skill bar's painted frame and its skills (the inside of painted
                         buttons), and the sea chart's painted frame
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
A ship with several looks (`VARIANTS` in its `build.py`: colours, sails, cargo) has a folder of atlases per look,
`canvas/public/sprites/ships/<line>/<ship>/<look>/`, and the scene's custom property `variant` picks the look built;
`render_stages.py` renders every stage of every look (`SHIP_VARIANTS=nets` and `SHIP_STAGES=0,4` limit it).

For the Coastal Bark: 1 soot, shot holes in the hull and every sail (each sail in its own places), a few rail posts and
a gunport lid gone; 2 more holes, torn sails, the balustrades' rails snapped, lids hanging or gone, dark stern windows
and a smashed lantern; 3 charred wood and both courses burnt from the foot; 4 the foremast snapped and lying over the
bow, the main topmast gone overboard, listing to port, low in the water, planks, crates and barrels alongside.
For the bots' ships: 1 soot, shot holes in the hull and the sails, some of the cargo gone; 2 more holes, torn sails, the
gunwale or bulwark broken in places; 3 charred wood and sails burnt from the foot; 4 the mast snapped and over the port
side with its sails on the water, listing, low in the water (the fishing boat with the sea inside it), wreckage and
cargo floating round. The fishing boat's looks: `nets` (blue, a tanned red lug sail, nets and cork floats), `barrels`
(green, a patched sail, barrels and crates, a stern lantern), `pots` (cream and red, an ochre sail and a mizzen, lobster
pots and marker buoys). The merchant's: `crates` (varnished, blue stripe, white sails, crates and a boat on deck) and
`bales` (grey planks, red stripe, tanned sails, bales and sacks). The smuggler: black, dark sails, a skull flag. The
Baron: the smuggler's `build.py` loaded and stretched to the boss's hull (`SCALE`), blood-red sails, a red flag with a
gold skull, a cannon at each of his two gun slots a side and a bronze mortar on the foredeck.

## Animated ships: the turtle

The turtle's head, jaw, neck and each flipper hang on an empty, a joint (`Joint.*` in the outliner), and the joints
are keyframed: open `ships/monsters/seaTurtle/seaTurtle.blend` and press play. Frames 1-12 are the swim (a loop:
frame 13 is frame 1 again), 101-106 the bite, 201 the dead turtle's pose; the timeline has a marker at each. Change the
keys in the Dope Sheet or the Graph Editor, or the numbers in `animate()` and `STROKE` in its `build.py` (a rebuild
makes the keys afresh), then run `render_stages.py`. Keep the flippers' strokes near the surface: what goes under the
water is cut off in the render, and a stroke under it is lost. `ANIMATIONS` in `build.py` says which frames make each of the game's animations
and how fast the game plays them; `animations(stage)` gives the dead stage its one still frame instead.

Every frame of an animation is rendered from every direction, so a stage's atlas holds 64 x 18 frames (`swim_03_17`
is the swim's frame 3 from direction 17) and takes a few minutes in a background Blender (see below); `meta.ship.animations` in its JSON tells
the game each animation's frame count, speed and whether it loops. The game plays the swim all the time, faster the
faster the turtle goes, and the bite when it bites.

## The sea serpent: parts

The serpent bends along the way it swam, so it isn't rendered whole: `ships/monsters/seaSerpent/build.py` makes its
parts, each at the origin and shown only at its own frames (keyed `hide_render`), and the game lays them along its
body (`client/scene/models/SerpentSprite.ts`). Frames 1-4 are the head swimming (the jaw working a little), 101-106 its
bite, 201 a piece of the body, 211 the same with a fin on its back, 221 with a harpoon in it, 231 the tail, 301 the
dead head; the timeline has a marker at each. `ANIMATIONS` names them like the turtle's animations, so a stage's atlas
holds every part from every direction (`segment_00_17`, `bite_03_17`). The parts cast no shadow (`SHADOW = False`):
the game draws the body's water itself. A piece is as thick as the body at its thickest, and the game scales it down
along the body, so a change to `BODY_RADIUS` or `PIECE_LENGTH` there needs the same in the game's `serpent3d.ts` and
`SerpentSprite.ts`. `HEAD_SIZE` sets the head's size against the neck.

## Floating loot

`loot/chest/build.py` builds the game's chests afloat in three looks (`VARIANT_NAMES`): `gold`, a sea chest bound in
brass with its lid thrown open on a heap of coins; `goods`, two crates and a barrel roped together; `lost`, the same
with a pole and an orange flag (a player's own cargo, lost where their ship went down). Open `loot/chest/chest.blend`
and run `render_stages.py` like for a ship: render_sprites.py renders anything under `ships/` or `loot/`, a model under
`loot/<thing>/` into `canvas/public/sprites/loot/<thing>/<look>/intact`. The game bobs and rolls them on the waves
itself, so each look is one pose.

## Rendering in the background

`frames/render_job.py` renders some stages of a ship in a Blender with no window, which is about twice as fast as in
the open Blender, and several can run at once: `blender --background ships/<line>/<ship>/<ship>.blend --python
frames/render_job.py`, with the environment variable `SHIP_STAGES` (`"0,1"`) and, for a ship with looks,
`SHIP_VARIANTS` (every look by default). Each writes its atlases where `render_stages.py` would and logs to
`frames/render_job_<stages>.log`. `frames/preview_job.py` renders only some directions (`PREVIEW_DIRS`, `"8,40"`) of a
stage's frames, to look at before a whole render.

## Fog of war

Open `effects/fog/fog.blend`, Scripting → Open → `effects/fog/build_fog.py` → Run Script (about 20 seconds).
It renders six cloud puffs as volumes in Cycles, lit by the game's sun and seen at the game camera's pitch, makes a
seamless tile of thin mist from periodic noise, and writes `canvas/public/sprites/fog/`: `puffs.webp` + `puffs.json`
(a Pixi spritesheet, frames trimmed to the clouds) and `wisps.webp`. Shapes, density, light and the mist's look are
constants at the top of the script. The script rebuilds the scene of the open file, so run it only in `fog.blend`.

## Sea

Scripting → Open → `effects/sea/build_sea.py` → Run Script (a few seconds; any open file will do, the scene isn't
touched). It writes `canvas/public/sprites/sea/`: four seamless wave maps (`swell`, `wind`, `chop`, `ripples`) made from
an ocean wave spectrum with an FFT, `caustics`, and `patches`: three fields of broad soft blobs (R where the sea is
deeper or shallower, G cloud shadows, B gusts, where the sea is rougher), filtered noise spread evenly over 0..1. In a
wave map, R and G are the water's slope and B how close it is to a crest; the game's sea shader lights them (`wind` is
spare: the game doesn't use it). Wave lengths, steepness and choppiness are in `WAVES`
at the top of the script, the blobs' sizes in `PATCHES`; how the game paints them (colors, tile sizes, how they drift)
is in `canvas/src/client/scene/effects/seaLook.ts`.
It also runs outside Blender with Python, numpy and Pillow: `python build_sea.py`.

## Sky

Scripting → Open → `effects/sky/build_clouds.py` → Run Script (about ten seconds; any open file will do, the scene isn't
touched). It writes `canvas/public/sprites/sky/`: `clouds.webp` + `clouds.json`, a Pixi spritesheet of six small cumulus
clouds (frames trimmed to the clouds), each a heap of domes roughened by noise, lit by the game's sun as the game camera
sees it and squashed to its pitch. The game draws them see-through, drifting with the wind, and their shadows on the sea
from the same frames. Their number, sizes and light are constants at the top of the script. It also runs outside Blender
with Python, numpy and Pillow: `python build_clouds.py`.

## Foam

Scripting → Open → `effects/foam/build_foam.py` → Run Script (about half a minute; any open file will do). It writes
`canvas/public/sprites/foam/foam.webp`, one seamless tile: R a lace of bubble walls (edges of Voronoi cells of a few
sizes), G soft patches, B streaks drawn out along x. The game's wakes and the water round a sinking ship dissolve foam
by a threshold over these (`canvas/src/client/scene/effects/Wake.ts`, `Sinking.ts`), so thick foam thins out to a lace;
the sea's whitecaps are frayed by its lace and patches (`seaSurface.ts`).
Bubble sizes and the patterns' scales are constants at the top of the script. It also runs outside Blender with
Python, numpy and Pillow: `python build_foam.py`.

## Sounds

Scripting → Open → `sounds/build_sounds.py` → Run Script (a few seconds; any open file will do). It writes every sound
of the game to `canvas/public/sounds/` (`SOUNDS` in the script lists them and what each is made of) from the
recordings in `sounds/source/`: each cut to start right at its attack (so the game plays it without delay), layered,
played lower or higher, filtered, faded out and brought to the same peak; the game sets how loud each plays
(each one's `level` in `SOUNDS` in `canvas/src/client/audio/Sounds.ts`). A name ending in `_1`, `_2`… is one of a sound's variants, picked
at random. Nothing is synthesised. Every source is CC0 — where each came
from is in `sounds/CREDITS.md`; add a new one there when you add a sound. Outside Blender it runs with Python, numpy and
ffmpeg: `python build_sounds.py`.

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

## Port

The port in the middle of the map: a green island with a bay, two curved breakwaters round it (a lighthouse on the
long one's head, a brick bastion on the short one's), a town climbing round the bay in rows like the seats of a
theatre, up to a rocky hill with a red brick castle on top; a market square and a church, a shipyard and fishermen's
huts on the beaches, a windmill and fields. Built and rendered by one script, about a minute
on a GTX 1060:

    blender --background --python port/build_port.py

(or Scripting → Open → `port/build_port.py` → Run Script; Blender is busy until it is done). `PORT_PREVIEW=1` in the
environment renders only a small picture into `frames/port/preview.png` and writes nothing into the game.

- `port/layout.json` is the port's geometry from the game (`canvas/src/game/world/port.ts`): the island's coast with
  the walls, the quay, the basin. The picture is built on it, so ships bump into the coast where it is drawn. After a
  change to the port there, export it again and render: `cd canvas && node ../blender-assets/port/export_layout.mjs`
  (it uses the game's own Vite to read `PORT`).
- What is where: the constants in `build_port.py` (the hill, the castle, the rows of houses round the bay and the
  lanes up between them, the fields, the road up the hill) in the harbour's frame: `u` to the right of the screen, `v` up it, round
  the island's centre. Textures from Poly Haven (CC0, downloaded into `textures/polyhaven/` on the first run): stone,
  brick, plaster, roof tiles, thatch, cobbles, planks, and the islands' sand, grass and rock.
- Output: `canvas/public/sprites/port/ground.webp` (everything at the water's level: drawn under the ships),
  `raised_<n>.webp` (the land and all on it, cut into slices 16 units deep along the camera's view, each sorted with
  the ships by its depth: a ship goes behind the hill and the lighthouse, between the walls, in front of the town) and
  `port.json`. The game animates the lighthouse's lamp and the flags; `port.json` says where they are.
- Camera and sun are the game's, as for the ships and the islands.

### The painted port

The game shows a painting of the port now (`port/source/island.webp`), painted over the render above, cut the way the
render is:

    python port/align_port_art.py     (once, after the painting or the render changes)
    blender --background --python port/build_port_art.py

(or `python port/build_port_art.py`, with numpy and Pillow; about half a minute). `align_port_art.py` needs a Python 3
with numpy, scipy, OpenCV and Pillow (`pip install numpy scipy opencv-python pillow`), not Blender's.

- `port/source/render/` is the render the painting was painted over: what `build_port.py` wrote into the game, kept
  here, since `build_port_art.py` writes the same three files and the last of the two run is what the game shows.
- The painting doesn't lie on the render exactly (a little smaller, its walls a little inside). `align_port_art.py`
  fits it, its coast and its walls onto the render's, first with one affine and then with a smooth bend that fades out
  away from the outlines, and writes `port/source/island_warp.json`: where each pixel of the render's frame takes the
  painting from.
- Each painted pixel goes where the render's pixel at its place went, into the ground under the ships or into a slice,
  so the game sorts the painting with the ships as it did the render. What the painting has and the render hadn't (the
  water and the boats in the harbour, a flag) goes into the slice next to it, or the ground.
- The game animates the render's lighthouse lamp and flags; the painting has its own flags and no lighthouse, so its
  `port.json` names none.
- After a change to the port's geometry: export the layout, render the port, copy what it wrote into the game into
  `port/source/render/`, and fit the painting again (or have it painted again over the new render).

### The harbour view

In port the game shows a window with a picture of the harbour, a medallion over each of its buildings (the tavern,
the market, the workshop, the shipyard, the arsenal, the guild hall, the auction house): a click opens that building's
window. The game shows a painted picture now, made from painted art:

    blender --background --python port/build_harbour_art.py

(or `python port/build_harbour_art.py`, with numpy and Pillow; a few seconds). It takes `port/source/harbour.webp`
as it is and cuts each medallion out of `port/source/medallions.webp` round its gold rim (`MEDALLIONS`: each rim's
circle on the sheet); `SPOTS` says where each building stands on the painting, as shares of its width and height. A
new building needs a spot and a medallion there (its id is the game's, `BuildingId` in
`canvas/src/client/hud/HarbourView.ts`).

`build_harbour.py` renders the same three files in Blender from the port's scene instead, so the last of the two run
is what the game shows. Its picture is `port.blend` (so run `build_port.py` first) seen in perspective from over the roadstead, late
in the afternoon, with a sky (Poly Haven's `evening_road_01_puresky` HDRI), a clear sea over the sea floor, Poly
Haven's Dutch ships in the bay, flags and gulls. `build_harbour.py` opens the scene and saves nothing back into it:

    blender --background --python port/build_harbour.py

(about 3 minutes on a GTX 1060). `HARBOUR_PREVIEW=1` renders a small picture with each building's spot ringed
(red: something stands in front of it) into `frames/harbour/preview.png`, and the medallions into
`frames/harbour/medallions.png`; nothing goes into the game. `HARBOUR_ONLY=picture` or `HARBOUR_ONLY=medallions`
makes one of the two. To try a look without editing: `HARBOUR_CAM` (`u,v,z;u,v,z;lens`: where the camera is, what it
looks at, in the harbour's frame), `HARBOUR_SUN` (degrees from the view), `HARBOUR_SUN_EL`, `HARBOUR_SUN_STRENGTH`,
`HARBOUR_SUN_COLOR`, `HARBOUR_SKY`, `HARBOUR_EXPOSURE`, `HARBOUR_GRADE` (`saturation,contrast,vignette`).

- Where each building is: `buildings()` (a point over its roof, from `build_port.py`'s layout); the game puts its
  medallion there. The ids are the game's (`BuildingId` in `canvas/src/client/hud/HarbourView.ts`): a new building
  needs a spot here, a medallion in `MEDALLIONS` and the picture rendered again.
- The medallions: a Poly Haven prop (or two) on a deep blue disc in a gold rim, 256 pixels each.
- Output, in `canvas/public/sprites/port/`: `harbour.webp` (2048 x 1280), `medallions.webp` (the medallions in a row)
  and `harbour.json` (the picture's size; where each building is on it, as shares of its width and height, and which
  medallion is its own).

## Shop icons

The cards of the arsenal, the workshop and the shipyard, and the info window of a gun, an ammo, a piece of outfit or a
ship, show its icon, cut out of sheets of paintings on a dark gradient and packed into one picture for the guns, one
for the ammo, one for the outfit and one for the ships:

    blender --background --python icons/build_gun_icons.py
    blender --background --python icons/build_ammo_icons.py
    blender --background --python icons/build_outfit_icons.py
    blender --background --python icons/build_ship_icons.py

(or `python icons/build_gun_icons.py`, with numpy and Pillow). The sheets are in `icons/source/`, kept as WebP at
quality 95 (a fifth of a PNG's size, no difference to see): `cannons.webp` (7 x 5 cannons), `harpoons.webp` (5 x 4
harpoon guns), `cannonballs.webp` and `harpoon_ammo.webp` (5 x 4 each), and the outfit's, a slot's each:
`outfit_sails.webp`, `outfit_hull.webp`, `outfit_rudder.webp`, `outfit_lookout.webp` (5 x 2 each). `SHEETS` in each
script picks each one's picture (its id is the game's, `canvas/src/game/combat/arsenal.ts` or
`canvas/src/game/ships/outfit.ts`) by its box on its sheet, or for a cannonball by its circle. Cannons: plain wood and iron at tier 1, green bronze at 2, blue steel at 3, purple and silver at 4, red and
gold at 5, all gold at 6. Harpoon guns: plain wood at 1, a green frame and a heavy winch at 2, blue frames at 3, carved
and barbed at 4, a shark's head at 5, a kraken at 6. Cannonballs: rusty iron, banded halves (the chain shot), smooth
iron, the navy's bronze, lava (heated), black glass in a cage (explosive), a sapphire (royal). Harpoons: plain iron,
barbs all along, a leather grip, bronze, violet venom, lava, verdigris tentacles. The outfit: plain canvas and wood at
tier 1, then cotton, tar, copper, iron and brass, and at tier 3 silk, teak, steel and the kraken's pieces; see the
comments in `build_outfit_icons.py`. The sheets' skull-marked ones are left out, and a plain wheel and a telescope
on a dark tripod (the outfit has no piece for them yet).

`icons/cutout.py` does the cutting: a sheet's background is modelled as a smooth field, and a picture is what differs
from it, reached from its middle, less the soft shadow under it and the edges of its neighbours; a round one's circle
is all its (dark iron is close to the background's colour), with what stands out of it close round it. For the outfit
two more: the pockets of background a picture encloses (between a sail and its ropes, a wheel's spokes) are let
through for the pieces in `POCKETS` (not the stacks of planks and plates, whose dark gaps are their own shading), and
a dark piece can be given a closer likeness to the background and its notches filled (`like_bg`, `close`). The
pictures of a sheet are scaled alike, so a heavy gun is drawn bigger than a light one. Output, in
`canvas/public/sprites/icons/`: `guns.webp`, `ammo.webp` and `outfit.webp` (192-pixel tiles, transparent), and their
`.json` (each one's tile). One left out of `SHEETS` shows its tier in the game instead.

The ships are a picture each, `icons/source/ship_<id>.webp` (the id is the game's,
`canvas/src/game/ships/shipLines.ts`): so far the Starter Sloop (`ship_sloop.webp`) and the Coastal Bark
(`ship_coastalBark.webp`). Each fills its tile across, in its middle, with the background its rigging encloses cut out.
Output: `ships.webp` (256-pixel tiles: the info window shows a ship 236 wide) and `ships.json`. A ship without a picture
shows an empty slot. A new one: its picture in `icons/source/`, its line in `SHEETS` of `build_ship_icons.py` (its box
on the picture), and the script run again.

## The minimap's frame

The minimap in the game's bottom right corner sits in a painted frame of dark wood under brass, with rope, studs, four
spikes and four empty slots on top (`hud/source/minimap_frame.png`, already cut out on a transparent background):

    blender --background --python hud/build_minimap_frame.py

(or `python hud/build_minimap_frame.py`, with numpy and Pillow). It shrinks the picture by half into
`canvas/public/sprites/hud/minimap_frame.webp` and prints its size, the oval opening in its middle the map shows
through (its middle and radii), how far the ring reaches round it, and the four slots on top (their middles and
radius): a new picture's figures go into `FRAME` in `canvas/src/client/hud/Minimap.ts`.

The slots are the game's buttons, painted medallions in a row (`hud/source/minimap_buttons.png`, cut out on a
transparent background): a crate of goods and gold (the hold), a cannon (the loadout), a ship under three stars (the
ship's talents) and a captain under three stars (the captain's mastery, the account's tree):

    blender --background --python hud/build_minimap_buttons.py

finds each one by the picture's alpha, left to right, and writes them as 128-pixel tiles in a row to
`canvas/public/sprites/hud/minimap_buttons.webp`, with `minimap_buttons.json` (each one's tile, as the icons' atlases
have them). `BUTTONS` in the script names them, in the game's ids.

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
rendered again from scratch. A ship dark all over (soot, char, a black hull) sets its own bar: a frame is re-rendered
only when it is much darker than the first frame of its stage. What goes under the water (a flipper's stroke, a
wreck's sunk side) is cut out of the frame: the water is a holdout in the render without the shadow.

If you change the camera pitch or yaw (`CAMERA` in `canvas/src/client/scene/SceneView.ts`), update `CAM_PITCH` /
`CAM_YAW` in `render_sprites.py` and re-render every ship.

Blender backups (`*.blend1`), `frames/` and `__pycache__/` are not worth keeping if this folder becomes a git repository.
The Python scripts run inside Blender and are not covered by the game's `npm run check`.

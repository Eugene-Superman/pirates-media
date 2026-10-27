// Writes islands/islands.json: every island of the game's sea but the port's (which has its own art, port/), from the
// game itself (canvas/src/game/world/World.ts), for build_outlines.py and the islands' art to come. Run from the
// game's folder after a change to the islands there:
//   cd canvas && node ../blender-assets/islands/export_islands.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// The game's own Vite, from the folder this is run in: it compiles the game's TypeScript
const viteDir = join(process.cwd(), 'node_modules', 'vite');
const { exports } = JSON.parse(readFileSync(join(viteDir, 'package.json'), 'utf8'));
const entry = typeof exports['.'] === 'string' ? exports['.'] : exports['.'].import;
const { createServer } = await import(pathToFileURL(join(viteDir, entry)).href);

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' });
try {
  const { createWorld, MAP_SQUARE } = await server.ssrLoadModule('/src/game/world/World.ts');
  const round = (v) => Math.round(v * 1000) / 1000;
  const point = (p) => [round(p.x), round(p.y)];
  // A1…H8: columns west to east, rows north to south, as on the game's sea chart
  const square = (x, y) => `${String.fromCharCode(65 + Math.floor(x / MAP_SQUARE))}${Math.floor(y / MAP_SQUARE) + 1}`;
  const { islands } = createWorld();
  const [port] = islands;
  const out = {
    note: 'World units; x east, y south. The port island (the first in the game) is not one of them: it has its own art',
    port: { x: round(port.x), y: round(port.y), coast: port.coast.map(point) },
    islands: islands.slice(1).map((island, i) => ({
      id: `island_${String(i + 1).padStart(2, '0')}`,
      square: square(island.x, island.y),
      x: round(island.x),
      y: round(island.y),
      radius: round(island.radius),
      reach: round(island.reach),
      height: round(island.height),
      hillHeight: round(island.hillHeight),
      coast: island.coast.map(point),
      palms: island.palms.map(point),
    })),
  };
  const file = join(dirname(fileURLToPath(import.meta.url)), 'islands.json');
  writeFileSync(file, JSON.stringify(out, null, 1) + '\n');
  console.log(`${file}: ${out.islands.length} islands`);
} finally {
  await server.close();
}

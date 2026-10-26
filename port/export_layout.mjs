// Writes port/layout.json: the port's geometry from the game (canvas/src/game/world/port.ts), which build_port.py
// builds the port's picture on. Run from the game's folder after a change to the port there:
//   cd canvas && node ../blender-assets/port/export_layout.mjs
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
  const { PORT } = await server.ssrLoadModule('/src/game/world/port.ts');
  const round = (v) => Math.round(v * 1000) / 1000;
  const point = (p) => [round(p.x), round(p.y)];
  const { island } = PORT;
  const layout = {
    name: PORT.name,
    harbour: PORT.harbour,
    island: {
      x: island.x,
      y: island.y,
      radius: island.radius,
      height: island.height,
      hillHeight: island.hillHeight,
      reach: round(island.reach),
      coast: island.coast.map(point),
    },
    shore: PORT.shore.map(point),
    walls: PORT.walls.map((wall) => wall.map(point)),
    quay: PORT.quay.map(point),
    basin: PORT.basin.map(point),
    mooring: point(PORT.mooring),
    roadstead: point(PORT.roadstead),
  };
  const out = join(dirname(fileURLToPath(import.meta.url)), 'layout.json');
  writeFileSync(out, JSON.stringify(layout, null, 1) + '\n');
  console.log(`${out}: ${layout.island.coast.length} coast points`);
} finally {
  await server.close();
}

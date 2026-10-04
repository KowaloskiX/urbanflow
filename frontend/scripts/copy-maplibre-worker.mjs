// MapLibre 6 loads its web worker from a file next to its own module. Once the app
// is bundled that file is gone, so the worker never starts and GeoJSON layers stay
// empty. Ship the worker (and the chunk it imports) as static files instead; the
// app points MapLibre at them with setWorkerUrl. Copied at build time so the
// version always matches node_modules.
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const from = join(root, 'node_modules/maplibre-gl/dist');
const to = join(root, 'public/maplibre');
mkdirSync(to, { recursive: true });
for (const file of ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']) {
  copyFileSync(join(from, file), join(to, file));
}

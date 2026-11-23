// MapLibre GL JS 6 loads its tile-parsing worker from a separate file,
// dist/maplibre-gl-worker.mjs, and derives that URL from import.meta.url.
// Turbopack rewrites import.meta.url, so the derived URL points at nothing
// and the map never finishes loading. Copy the worker next to the static
// assets and point MapLibre at it (PartnerMap calls setWorkerUrl).
import { copyFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const source = require.resolve("maplibre-gl/dist/maplibre-gl-worker.mjs");
const target = new URL("../public/maplibre-gl-worker.mjs", import.meta.url);

await mkdir(new URL("../public/", import.meta.url), { recursive: true });
await copyFile(source, target);
console.log(`copied ${source} -> ${target.pathname}`);

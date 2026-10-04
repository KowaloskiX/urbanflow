/** Loads MapLibre with its worker served from /public (see scripts/copy-maplibre-worker.mjs). */
export async function loadMapLibre() {
  const maplibregl = await import('maplibre-gl');
  maplibregl.setWorkerUrl('/maplibre/maplibre-gl-worker.mjs');
  return maplibregl;
}

'use client';

import { useEffect, useRef } from 'react';
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';

import { loadMapLibre } from '@/lib/maplibre';
import { API_BASE } from '@/lib/api';

type LiveVehicle = {
  vehicleId: string;
  latitude: number;
  longitude: number;
  vehicleMode: 'TRAM' | 'BUS';
  isSimulation: boolean;
  occupancyStatus: string;
};

type Glide = { from: [number, number]; to: [number, number] };

const POLL_MS = 5_000;
const FRAME_MS = 50;
const CROWDED = new Set(['CROWDED', 'OVER_CAPACITY']);

/**
 * Kraków right now, as a backdrop: every tram and bus from the live feed, gliding
 * between polls, with crowded trams pulsing red. Not interactive — it must never
 * capture the page's scroll.
 */
export function LiveCityMap({ onCount }: { onCount?: (trams: number) => void }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let map: MapLibreMap | null = null;
    let disposed = false;
    let pollTimer = 0;
    let frameTimer = 0;
    let pulseFrame = 0;
    const glides = new Map<string, Glide>();
    const meta = new Map<string, { mode: string; crowded: boolean }>();
    let glideStart = performance.now();

    const features = (progress: number) => ({
      type: 'FeatureCollection' as const,
      features: [...glides.entries()].map(([id, glide]) => {
        const info = meta.get(id);
        const t = Math.min(1, progress);
        return {
          type: 'Feature' as const,
          geometry: {
            type: 'Point' as const,
            coordinates: [
              glide.from[0] + (glide.to[0] - glide.from[0]) * t,
              glide.from[1] + (glide.to[1] - glide.from[1]) * t,
            ],
          },
          properties: { mode: info?.mode ?? 'TRAM', crowded: info?.crowded ?? false },
        };
      }),
    });

    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/vehicles`);
        if (!response.ok) return;
        const { vehicles } = (await response.json()) as { vehicles: LiveVehicle[] };
        const now = performance.now();
        const progress = (now - glideStart) / POLL_MS;
        const seen = new Set<string>();
        for (const vehicle of vehicles) {
          if (vehicle.isSimulation) continue;
          seen.add(vehicle.vehicleId);
          const target: [number, number] = [vehicle.longitude, vehicle.latitude];
          const previous = glides.get(vehicle.vehicleId);
          const current: [number, number] = previous
            ? [
                previous.from[0] + (previous.to[0] - previous.from[0]) * Math.min(1, progress),
                previous.from[1] + (previous.to[1] - previous.from[1]) * Math.min(1, progress),
              ]
            : target;
          glides.set(vehicle.vehicleId, { from: current, to: target });
          meta.set(vehicle.vehicleId, {
            mode: vehicle.vehicleMode,
            crowded: CROWDED.has(vehicle.occupancyStatus),
          });
        }
        for (const id of glides.keys()) if (!seen.has(id)) glides.delete(id);
        glideStart = now;
        onCount?.(vehicles.filter((v) => !v.isSimulation && v.vehicleMode === 'TRAM').length);
      } catch {
        // Backend offline: the map simply stays empty.
      }
    };

    void loadMapLibre().then((maplibregl) => {
      if (disposed || !container.current) return;
      map = new maplibregl.Map({
        container: container.current,
        center: [19.945, 50.062],
        zoom: 12.4,
        pitch: 45,
        bearing: -12,
        interactive: false,
        attributionControl: { compact: true },
        style: {
          version: 8,
          sources: {
            osm: {
              type: 'raster',
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              tileSize: 256,
              attribution: '© OpenStreetMap',
            },
          },
          // Night map without a keyed tile service: the same OSM tiles the
          // dashboard uses, desaturated and darkened in the style.
          layers: [
            { id: 'night', type: 'background', paint: { 'background-color': '#081521' } },
            {
              id: 'osm',
              type: 'raster',
              source: 'osm',
              paint: {
                'raster-saturation': -1,
                'raster-brightness-min': 0.98,
                'raster-brightness-max': 0.02,
                'raster-contrast': 0.25,
                'raster-opacity': 0.55,
              },
            },
          ],
        },
      });

      map.on('load', () => {
        if (!map) return;
        map.addSource('live', { type: 'geojson', data: features(1) });
        map.addLayer({
          id: 'live-glow',
          type: 'circle',
          source: 'live',
          paint: {
            'circle-radius': ['case', ['==', ['get', 'mode'], 'TRAM'], 9, 6],
            'circle-color': ['case', ['get', 'crowded'], '#f85c50', '#00b3a4'],
            'circle-opacity': ['case', ['==', ['get', 'mode'], 'TRAM'], 0.22, 0.1],
            'circle-blur': 0.8,
          },
        });
        map.addLayer({
          id: 'live-dot',
          type: 'circle',
          source: 'live',
          paint: {
            'circle-radius': ['case', ['==', ['get', 'mode'], 'TRAM'], 3.2, 2],
            'circle-color': [
              'case',
              ['get', 'crowded'],
              '#f85c50',
              ['==', ['get', 'mode'], 'TRAM'],
              '#5eead4',
              '#6b8796',
            ],
          },
        });
        map.addLayer({
          id: 'live-pulse',
          type: 'circle',
          source: 'live',
          filter: ['get', 'crowded'],
          paint: {
            'circle-radius': 10,
            'circle-color': 'rgba(0,0,0,0)',
            'circle-stroke-color': '#f85c50',
            'circle-stroke-width': 2,
            'circle-stroke-opacity': 0.8,
          },
        });

        void poll();
        pollTimer = window.setInterval(() => void poll(), POLL_MS);
        frameTimer = window.setInterval(() => {
          const source = map?.getSource('live') as GeoJSONSource | undefined;
          void source?.setData(features((performance.now() - glideStart) / POLL_MS));
        }, FRAME_MS);

        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reduce) {
          const pulse = (time: number) => {
            const phase = (time % 1600) / 1600;
            map?.setPaintProperty('live-pulse', 'circle-radius', 6 + phase * 22);
            map?.setPaintProperty('live-pulse', 'circle-stroke-opacity', 0.9 * (1 - phase));
            pulseFrame = window.requestAnimationFrame(pulse);
          };
          pulseFrame = window.requestAnimationFrame(pulse);
        }
      });
    });

    return () => {
      disposed = true;
      window.clearInterval(pollTimer);
      window.clearInterval(frameTimer);
      window.cancelAnimationFrame(pulseFrame);
      map?.remove();
    };
  }, [onCount]);

  return <div ref={container} className="live-city-map" aria-hidden="true" />;
}

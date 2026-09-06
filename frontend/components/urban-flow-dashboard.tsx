'use client';

import Image from 'next/image';
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react';
import type {
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from 'maplibre-gl';
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  BusFront,
  ChevronRight,
  Clock3,
  LocateFixed,
  MapPin,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Radio,
  RefreshCw,
  Route,
  TramFront,
  Users,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

type Freshness = 'LIVE' | 'STALE' | 'OFFLINE' | 'SIMULATION';
type VehicleMode = 'TRAM' | 'BUS';
type Occupancy =
  | 'UNKNOWN'
  | 'LOW'
  | 'MODERATE'
  | 'BUSY'
  | 'CROWDED'
  | 'OVER_CAPACITY';

type Vehicle = {
  vehicleId: string;
  routeId: string;
  routeShortName: string;
  headsign: string;
  directionId: number;
  latitude: number;
  longitude: number;
  bearing: number | null;
  speedMps: number | null;
  nextStopName: string | null;
  delaySeconds: number | null;
  passengerCount: number | null;
  capacity: number | null;
  loadFactor: number | null;
  occupancyStatus: Occupancy;
  positionMeasuredAt: string;
  updatedAt: string;
  freshness: Freshness;
  vehicleMode: VehicleMode;
  isSimulation: boolean;
};

type VehiclesResponse = {
  generatedAt: string;
  vehicles: Vehicle[];
};

type RouteSummary = {
  routeId: string;
  shortName: string;
  longName: string;
  color: string;
  vehicleCount: number;
};

type FeedItem = {
  id: string;
  kind: 'update' | 'warning' | 'system';
  title: string;
  detail: string;
  at: Date;
  delaySeconds?: number | null;
  vehicleMode?: VehicleMode;
  vehicleId?: string;
};

type TrackingState = {
  vehicleId: string | null;
  vehicle: Vehicle | null;
  isFollowing: boolean;
  isTemporarilyMissing: boolean;
};

type CameraMode = 'idle' | 'tracking' | 'cluster';

type TrackingAction =
  | { type: 'select'; vehicle: Vehicle }
  | { type: 'sync'; vehicles: Vehicle[] }
  | { type: 'update'; vehicle: Vehicle }
  | { type: 'remove'; vehicleId: string }
  | { type: 'toggle-following' }
  | { type: 'clear' };

const initialTrackingState: TrackingState = {
  vehicleId: null,
  vehicle: null,
  isFollowing: true,
  isTemporarilyMissing: false,
};

function hasStalePosition(vehicle: Vehicle) {
  return vehicle.freshness === 'STALE' || vehicle.freshness === 'OFFLINE';
}

function trackingReducer(
  state: TrackingState,
  action: TrackingAction,
): TrackingState {
  switch (action.type) {
    case 'select':
      return {
        vehicleId: action.vehicle.vehicleId,
        vehicle: action.vehicle,
        isFollowing: true,
        isTemporarilyMissing: hasStalePosition(action.vehicle),
      };
    case 'sync': {
      if (!state.vehicleId) return state;
      const vehicle = action.vehicles.find(
        (candidate) => candidate.vehicleId === state.vehicleId,
      );
      return vehicle
        ? { ...state, vehicle, isTemporarilyMissing: hasStalePosition(vehicle) }
        : state.vehicle?.isSimulation
          ? state
          : { ...state, isTemporarilyMissing: true };
    }
    case 'update':
      return action.vehicle.vehicleId === state.vehicleId
        ? {
            ...state,
            vehicle: action.vehicle,
            isTemporarilyMissing: hasStalePosition(action.vehicle),
          }
        : state;
    case 'remove':
      return action.vehicleId === state.vehicleId
        ? initialTrackingState
        : state;
    case 'toggle-following':
      return state.vehicle
        ? { ...state, isFollowing: !state.isFollowing }
        : state;
    case 'clear':
      return initialTrackingState;
  }
}

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  'http://localhost:8000/api/v1';
const WS_URL = API_BASE.replace(/^http/, 'ws') + '/live';

const occupancyMeta: Record<
  Occupancy,
  { label: string; color: string; text: string }
> = {
  UNKNOWN: { label: 'Brak danych', color: '#7b8794', text: 'text-slate-500' },
  LOW: { label: 'Niskie', color: '#00a99a', text: 'text-teal-700' },
  MODERATE: { label: 'Umiarkowane', color: '#e4b63a', text: 'text-amber-700' },
  BUSY: { label: 'Wysokie', color: '#ef8d32', text: 'text-orange-700' },
  CROWDED: { label: 'Tłok', color: '#ee5b50', text: 'text-red-700' },
  OVER_CAPACITY: {
    label: 'Przepełnienie',
    color: '#c9303e',
    text: 'text-red-800',
  },
};

function vehicleColor(vehicle: Vehicle) {
  if (hasStalePosition(vehicle)) return '#93a2a9';
  if (vehicle.isSimulation) return '#5267ff';
  return vehicle.vehicleMode === 'BUS' ? '#168d93' : '#14a56c';
}

const createVehicleGeoJson = (
  vehicles: Vehicle[],
  trackedVehicleId: string | null = null,
) => ({
  type: 'FeatureCollection' as const,
  features: vehicles.map((vehicle) => ({
    type: 'Feature' as const,
    id: vehicle.vehicleId,
    geometry: {
      type: 'Point' as const,
      coordinates: [vehicle.longitude, vehicle.latitude],
    },
    properties: {
      vehicleId: vehicle.vehicleId,
      route: vehicle.routeShortName,
      color: vehicleColor(vehicle),
      simulation: vehicle.isSimulation,
      mode: vehicle.vehicleMode,
      selected: vehicle.vehicleId === trackedVehicleId,
    },
  })),
});

function formatTime(date: Date | string) {
  return new Intl.DateTimeFormat('pl-PL', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(typeof date === 'string' ? new Date(date) : date);
}

function relativeDelay(delay: number | null) {
  if (delay === null) return 'brak danych';
  if (Math.abs(delay) < 30) return 'na czas';
  const minutes = Math.max(1, Math.round(Math.abs(delay) / 60));
  return delay > 0 ? `+${minutes} min` : `−${minutes} min`;
}

function delayBadge(delay: number | null | undefined) {
  if (delay === null || delay === undefined) return null;

  const minutes = Math.max(1, Math.round(Math.abs(delay) / 60));
  if (delay <= -30) return { tone: 'early', label: `−${minutes} min` };
  if (delay < 30) return { tone: 'on-time', label: 'na czas' };
  if (delay < 120) return { tone: 'minor', label: `+${minutes} min` };
  if (delay < 300) return { tone: 'moderate', label: `+${minutes} min` };
  if (delay < 600) return { tone: 'severe', label: `+${minutes} min` };
  return { tone: 'critical', label: `+${minutes} min` };
}

function formatPositionAge(positionMeasuredAt: string, now: number) {
  const seconds = Math.max(
    0,
    Math.floor((now - new Date(positionMeasuredAt).getTime()) / 1000),
  );
  if (seconds < 5) return 'przed chwilą';
  if (seconds < 60) return `sprzed ${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `sprzed ${minutes} min`;
}

export function UrbanFlowDashboard() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const trackingCardRef = useRef<HTMLElement>(null);
  const initialFeedSeededRef = useRef(false);
  const lastFocusedVehicleIdRef = useRef<string | null>(null);
  const cameraModeRef = useRef<CameraMode>('idle');
  const cameraActionIdRef = useRef(0);
  const vehiclesByIdRef = useRef<Map<string, Vehicle>>(new Map());
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [routes, setRoutes] = useState<RouteSummary[]>([]);
  const [tracking, dispatchTracking] = useReducer(
    trackingReducer,
    initialTrackingState,
  );
  const [lineFilter, setLineFilter] = useState('all');
  const [connection, setConnection] = useState<
    'connecting' | 'live' | 'offline'
  >('connecting');
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const [mobilePanel, setMobilePanel] = useState(false);
  const [feedVisible, setFeedVisible] = useState(true);
  const [mapReady, setMapReady] = useState(false);
  const [showReal, setShowReal] = useState(true);
  const [showDemo, setShowDemo] = useState(true);
  const [demoDialogOpen, setDemoDialogOpen] = useState(false);
  const [demoRouteId, setDemoRouteId] = useState('');
  const [addingDemo, setAddingDemo] = useState(false);

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const resize = window.setTimeout(() => map.resize(), 220);
    return () => window.clearTimeout(resize);
  }, [feedVisible]);

  const addFeedItem = useCallback((item: Omit<FeedItem, 'id' | 'at'>) => {
    setFeed((current) => [
      { ...item, id: crypto.randomUUID(), at: new Date() },
      ...current,
    ].slice(0, 24));
  }, []);

  const loadVehicles = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [vehicleResponse, routeResponse] = await Promise.all([
        fetch(`${API_BASE}/vehicles`),
        fetch(`${API_BASE}/routes`),
      ]);
      if (!vehicleResponse.ok) {
        throw new Error(`HTTP ${vehicleResponse.status}`);
      }
      const data = (await vehicleResponse.json()) as VehiclesResponse;
      setVehicles(data.vehicles);
      dispatchTracking({ type: 'sync', vehicles: data.vehicles });
      if (routeResponse.ok) {
        setRoutes((await routeResponse.json()) as RouteSummary[]);
      }
      if (!initialFeedSeededRef.current) {
        initialFeedSeededRef.current = true;
        setFeed((current) => [
          ...current,
          ...data.vehicles.map((vehicle) => ({
            id: `snapshot-${vehicle.vehicleId}`,
            kind:
              vehicle.occupancyStatus === 'CROWDED' ||
              vehicle.occupancyStatus === 'OVER_CAPACITY'
                ? ('warning' as const)
                : ('update' as const),
            title: `Linia ${vehicle.routeShortName} · ${vehicle.headsign}`,
            detail: `${
              vehicle.loadFactor === null
                ? 'Zapełnienie nieznane'
                : `${Math.round(vehicle.loadFactor * 100)}% zapełnienia`
            } · ${vehicle.nextStopName ?? 'w trasie'}`,
            at: new Date(vehicle.updatedAt),
            delaySeconds: vehicle.delaySeconds,
            vehicleMode: vehicle.vehicleMode,
            vehicleId: vehicle.vehicleId,
          })),
        ].slice(0, 24));
      }
      setError(null);
    } catch {
      setError('Nie udało się pobrać danych. Zachowujemy ostatni znany stan.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initialRequest = window.setTimeout(() => void loadVehicles(), 0);
    const interval = window.setInterval(() => void loadVehicles(true), 10_000);
    return () => {
      window.clearTimeout(initialRequest);
      window.clearInterval(interval);
    };
  }, [loadVehicles]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let isDisposed = false;

    const connect = () => {
      setConnection('connecting');
      socket = new WebSocket(WS_URL);
      socket.onopen = () => setConnection('live');
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as {
          type: string;
          payload:
            | Vehicle
            | VehiclesResponse
            | { status: string }
            | { vehicleId: string };
        };
        if (message.type === 'connected') {
          addFeedItem({
            kind: 'system',
            title: 'Połączenie live aktywne',
            detail: 'Nasłuchujemy zmian pozycji pojazdów.',
          });
          return;
        }
        if (message.type === 'vehicle.updated') {
          const vehicle = message.payload as Vehicle;
          setVehicles((current) => {
            const exists = current.some(
              (item) => item.vehicleId === vehicle.vehicleId,
            );
            return exists
              ? current.map((item) =>
                  item.vehicleId === vehicle.vehicleId ? vehicle : item,
                )
              : [...current, vehicle];
          });
          dispatchTracking({ type: 'update', vehicle });
          addFeedItem({
            kind:
              vehicle.occupancyStatus === 'CROWDED' ||
              vehicle.occupancyStatus === 'OVER_CAPACITY'
                ? 'warning'
                : 'update',
            title: `Linia ${vehicle.routeShortName} · ${vehicle.headsign}`,
            detail: `${vehicle.isSimulation ? 'Symulacja' : 'Nowa pozycja'} · ${
              vehicle.nextStopName ?? 'w trasie'
            }`,
            delaySeconds: vehicle.delaySeconds,
            vehicleMode: vehicle.vehicleMode,
            vehicleId: vehicle.vehicleId,
          });
        }
        if (message.type === 'vehicles.snapshot') {
          const snapshot = message.payload as VehiclesResponse;
          setVehicles((current) => [
            ...snapshot.vehicles,
            ...current.filter((vehicle) => vehicle.isSimulation),
          ]);
          dispatchTracking({ type: 'sync', vehicles: snapshot.vehicles });
        }
        if (message.type === 'vehicle.removed') {
          const payload = message.payload as { vehicleId: string };
          setVehicles((current) =>
            current.filter((vehicle) => vehicle.vehicleId !== payload.vehicleId),
          );
          dispatchTracking({ type: 'remove', vehicleId: payload.vehicleId });
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setConnection('offline');
        if (!isDisposed) reconnectTimer = window.setTimeout(connect, 4_000);
      };
    };

    connect();
    return () => {
      isDisposed = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [addFeedItem]);

  const filteredVehicles = useMemo(
    () =>
      vehicles.filter(
        (vehicle) =>
          (lineFilter === 'all' || vehicle.routeId === lineFilter) &&
          ((showReal && !vehicle.isSimulation) ||
            (showDemo && vehicle.isSimulation)),
      ),
    [lineFilter, showDemo, showReal, vehicles],
  );

  const selectedVehicle = tracking.vehicle;
  const selectedDelayBadge = selectedVehicle
    ? delayBadge(selectedVehicle.delaySeconds)
    : null;
  const selectedPositionAge = selectedVehicle
    ? formatPositionAge(selectedVehicle.positionMeasuredAt, now)
    : '';
  const trackedRouteId = selectedVehicle?.routeId ?? null;
  const trackedDirectionId = selectedVehicle?.directionId ?? null;
  const trackedLatitude = selectedVehicle?.latitude ?? null;
  const trackedLongitude = selectedVehicle?.longitude ?? null;

  useEffect(() => {
    vehiclesByIdRef.current = new Map(
      vehicles.map((vehicle) => [vehicle.vehicleId, vehicle]),
    );
  }, [vehicles]);

  const selectVehicle = useCallback((vehicle: Vehicle) => {
    cameraModeRef.current = 'tracking';
    cameraActionIdRef.current += 1;
    mapRef.current?.stop();
    dispatchTracking({ type: 'select', vehicle });
  }, []);

  const selectVehicleById = useCallback((vehicleId: string) => {
    const vehicle = vehiclesByIdRef.current.get(vehicleId);
    if (vehicle) selectVehicle(vehicle);
  }, [selectVehicle]);

  const clearSelectedVehicle = useCallback(() => {
    cameraModeRef.current = 'idle';
    cameraActionIdRef.current += 1;
    mapRef.current?.stop();
    dispatchTracking({ type: 'clear' });
  }, []);

  const toggleVehicleFollowing = useCallback(() => {
    cameraModeRef.current = tracking.isFollowing ? 'idle' : 'tracking';
    cameraActionIdRef.current += 1;
    mapRef.current?.stop();
    dispatchTracking({ type: 'toggle-following' });
  }, [tracking.isFollowing]);

  const centerOnKrakow = useCallback(() => {
    cameraModeRef.current = 'idle';
    cameraActionIdRef.current += 1;
    lastFocusedVehicleIdRef.current = null;
    dispatchTracking({ type: 'clear' });
    const map = mapRef.current;
    map?.stop();
    map?.flyTo({ center: [19.9449, 50.0647], zoom: 13.25 });
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') clearSelectedVehicle();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [clearSelectedVehicle]);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    let disposed = false;

    void import('maplibre-gl').then((maplibregl) => {
      if (disposed || !mapContainer.current) return;
      const map = new maplibregl.Map({
        container: mapContainer.current,
        center: [19.9449, 50.0647],
        zoom: 13.25,
        minZoom: 10,
        maxZoom: 18,
        attributionControl: false,
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
          layers: [
            {
              id: 'osm',
              type: 'raster',
              source: 'osm',
              paint: {
                'raster-saturation': -0.78,
                'raster-contrast': 0.08,
                'raster-brightness-max': 0.92,
              },
            },
          ],
        },
      });
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        'bottom-right',
      );
      map.addControl(
        new maplibregl.AttributionControl({ compact: true }),
        'bottom-left',
      );
      map.on('load', () => {
        map.addSource('vehicles', {
          type: 'geojson',
          data: createVehicleGeoJson([]),
          cluster: true,
          // Markers are 26 px across: group only when their visible circles overlap.
          clusterRadius: 26,
          clusterMaxZoom: 15,
        });
        map.addLayer({
          id: 'vehicle-cluster-halo',
          type: 'circle',
          source: 'vehicles',
          filter: ['has', 'point_count'],
          paint: {
            'circle-radius': ['step', ['get', 'point_count'], 24, 10, 29, 30, 34],
            'circle-color': '#6e9fd0',
            'circle-opacity': 0.2,
          },
        });
        map.addLayer({
          id: 'vehicle-cluster',
          type: 'circle',
          source: 'vehicles',
          filter: ['has', 'point_count'],
          paint: {
            'circle-radius': ['step', ['get', 'point_count'], 17, 10, 21, 30, 25],
            'circle-color': '#00375b',
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 3,
          },
        });
        map.addLayer({
          id: 'vehicle-cluster-label',
          type: 'symbol',
          source: 'vehicles',
          filter: ['has', 'point_count'],
          layout: {
            'text-field': ['get', 'point_count_abbreviated'],
            'text-font': ['Open Sans Bold'],
            'text-size': 12,
            // Every cluster needs its count. MapLibre otherwise hides labels
            // that collide with labels of nearby clusters.
            'text-allow-overlap': true,
            'text-ignore-placement': true,
          },
          paint: { 'text-color': '#ffffff' },
        });
        map.addLayer({
          id: 'vehicle-halo',
          type: 'circle',
          source: 'vehicles',
          filter: ['!', ['has', 'point_count']],
          paint: {
            'circle-radius': [
              'case',
              ['boolean', ['get', 'selected'], false],
              27,
              18,
            ],
            'circle-color': ['get', 'color'],
            'circle-opacity': [
              'case',
              ['boolean', ['get', 'selected'], false],
              0.3,
              0.16,
            ],
          },
        });
        map.addLayer({
          id: 'vehicle-marker',
          type: 'circle',
          source: 'vehicles',
          filter: ['!', ['has', 'point_count']],
          paint: {
            'circle-radius': [
              'case',
              ['boolean', ['get', 'selected'], false],
              16,
              13,
            ],
            'circle-color': ['get', 'color'],
            'circle-stroke-color': [
              'case',
              ['boolean', ['get', 'selected'], false],
              '#00375b',
              '#ffffff',
            ],
            'circle-stroke-width': [
              'case',
              ['boolean', ['get', 'selected'], false],
              5,
              3,
            ],
          },
        });
        map.addLayer({
          id: 'vehicle-label',
          type: 'symbol',
          source: 'vehicles',
          filter: ['!', ['has', 'point_count']],
          layout: {
            'icon-image': ['concat', 'route-', ['get', 'route']],
            'icon-allow-overlap': true,
          },
        });
        map.addLayer({
          id: 'vehicle-hit-area',
          type: 'circle',
          source: 'vehicles',
          filter: ['!', ['has', 'point_count']],
          paint: {
            'circle-radius': 24,
            'circle-color': '#000000',
            'circle-opacity': 0.001,
          },
        });
        map.addLayer({
          id: 'vehicle-cluster-hit-area',
          type: 'circle',
          source: 'vehicles',
          filter: ['has', 'point_count'],
          paint: {
            'circle-radius': 34,
            'circle-color': '#000000',
            'circle-opacity': 0.001,
          },
        });
        const selectVehicle = (event: MapLayerMouseEvent) => {
          const id = event.features?.[0]?.properties?.vehicleId as
            | string
            | undefined;
          if (id) selectVehicleById(id);
        };
        const showPointer = () => {
          map.getCanvas().style.cursor = 'pointer';
        };
        const hidePointer = () => {
          map.getCanvas().style.cursor = '';
        };
        const expandCluster = (event: MapLayerMouseEvent) => {
          const feature = event.features?.[0];
          const clusterId = feature?.properties?.cluster_id as string | number | undefined;
          const coordinates = feature?.geometry.coordinates as [number, number] | undefined;
          const source = map.getSource('vehicles') as GeoJSONSource | undefined;
          if (!source || clusterId === undefined || !coordinates) return;

          // Cluster navigation must own the camera exclusively. Previously the
          // live tracking effect kept applying its card offset during this zoom,
          // so two easeTo calls fought and pushed the whole map down.
          cameraModeRef.current = 'cluster';
          const cameraActionId = ++cameraActionIdRef.current;
          lastFocusedVehicleIdRef.current = null;
          map.stop();
          dispatchTracking({ type: 'clear' });

          void source
            .getClusterExpansionZoom(Number(clusterId))
            .then((zoom) => {
              if (
                cameraModeRef.current !== 'cluster' ||
                cameraActionIdRef.current !== cameraActionId
              ) return;
              map.easeTo({
                center: coordinates,
                zoom,
                offset: [0, 0],
                duration: 450,
              });
            })
            .catch(() => undefined);
        };
        map.on('click', 'vehicle-hit-area', selectVehicle);
        map.on('click', 'vehicle-cluster-hit-area', expandCluster);
        map.on('mouseenter', 'vehicle-hit-area', showPointer);
        map.on('mouseenter', 'vehicle-cluster-hit-area', showPointer);
        map.on('mouseleave', 'vehicle-hit-area', hidePointer);
        map.on('mouseleave', 'vehicle-cluster-hit-area', hidePointer);
        setMapReady(true);
      });
      mapRef.current = map;
    });

    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, [selectVehicleById]);

  useEffect(() => {
    const map = mapRef.current;
    const source = map?.getSource('vehicles') as GeoJSONSource | undefined;
    if (!map || !source || !mapReady) return;
    filteredVehicles.forEach((vehicle) => {
      const imageName = `route-${vehicle.routeShortName}`;
      if (map.hasImage(imageName)) return;
      const canvas = document.createElement('canvas');
      canvas.width = 64;
      canvas.height = 64;
      const context = canvas.getContext('2d');
      if (!context) return;
      context.clearRect(0, 0, 64, 64);
      context.fillStyle = '#ffffff';
      context.font = '700 26px Arial';
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(vehicle.routeShortName, 32, 33);
      map.addImage(imageName, context.getImageData(0, 0, 64, 64), {
        pixelRatio: 2,
      });
    });
    void source.setData(
      createVehicleGeoJson(filteredVehicles, tracking.vehicleId),
    );
  }, [filteredVehicles, mapReady, tracking.vehicleId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    if (!trackedRouteId || trackedDirectionId === null) {
      if (map.getLayer('selected-route-line')) map.removeLayer('selected-route-line');
      if (map.getSource('selected-route')) map.removeSource('selected-route');
      return;
    }

    if (map.getLayer('selected-route-line')) map.removeLayer('selected-route-line');
    if (map.getSource('selected-route')) map.removeSource('selected-route');

    const controller = new AbortController();

    void fetch(
      `${API_BASE}/routes/${encodeURIComponent(trackedRouteId)}/shape?directionId=${trackedDirectionId}`,
      { signal: controller.signal },
    )
      .then((response) => (response.ok ? response.json() : null))
      .then((shape) => {
        if (!shape || !mapRef.current) return;
        mapRef.current.addSource('selected-route', {
          type: 'geojson',
          data: shape,
        });
        mapRef.current.addLayer(
          {
            id: 'selected-route-line',
            type: 'line',
            source: 'selected-route',
            paint: {
              'line-color': '#00375b',
              'line-width': 4,
              'line-opacity': 0.72,
            },
          },
          'vehicle-halo',
        );
      })
      .catch(() => undefined);

    return () => controller.abort();
  }, [mapReady, trackedDirectionId, trackedRouteId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!tracking.vehicleId) {
      lastFocusedVehicleIdRef.current = null;
      return;
    }
    if (
      !map ||
      !mapReady ||
      trackedLatitude === null ||
      trackedLongitude === null ||
      !tracking.isFollowing ||
      cameraModeRef.current !== 'tracking'
    ) return;

    const isNewVehicle = lastFocusedVehicleIdRef.current !== tracking.vehicleId;
    lastFocusedVehicleIdRef.current = tracking.vehicleId;
    const mapRect = map.getCanvas().getBoundingClientRect();
    const cardRect = trackingCardRef.current?.getBoundingClientRect();
    const mapCenterY = mapRect.height / 2;
    const cardTopInMap = cardRect ? cardRect.top - mapRect.top : mapRect.height;
    const safeTargetY = Math.min(
      mapCenterY,
      Math.max(110, cardTopInMap - 64),
    );
    const trackingOffset = safeTargetY - mapCenterY;
    map.stop();
    if (isNewVehicle) {
      map.flyTo({
        center: [trackedLongitude, trackedLatitude],
        offset: [0, trackingOffset],
        zoom: Math.max(map.getZoom(), 14.3),
        duration: 650,
      });
      return;
    }
    map.easeTo({
      center: [trackedLongitude, trackedLatitude],
      offset: [0, trackingOffset],
      duration: 500,
    });
  }, [
    mapReady,
    trackedLatitude,
    trackedLongitude,
    tracking.isFollowing,
    tracking.vehicleId,
  ]);

  const lineOptions = useMemo(() => {
    const unique = new Map<string, string>();
    vehicles.forEach((vehicle) =>
      unique.set(vehicle.routeId, vehicle.routeShortName),
    );
    return [...unique.entries()].sort((a, b) =>
      a[1].localeCompare(b[1], 'pl', { numeric: true }),
    );
  }, [vehicles]);

  const demoRouteOptions = useMemo(() => {
    const activeRouteIds = new Set(
      vehicles
        .filter((vehicle) => !vehicle.isSimulation)
        .map((vehicle) => vehicle.routeId),
    );
    return routes
      .filter((route) => activeRouteIds.has(route.routeId))
      .sort((a, b) =>
        a.shortName.localeCompare(b.shortName, 'pl', { numeric: true }),
      );
  }, [routes, vehicles]);

  const selectedDemoRouteId = demoRouteId || demoRouteOptions[0]?.routeId || '';

  const addDemoVehicle = async () => {
    if (!selectedDemoRouteId) return;
    setAddingDemo(true);
    try {
      const response = await fetch(`${API_BASE}/demo/vehicles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          routeId: selectedDemoRouteId,
          capacity: 202,
          simulationSpeed: 5,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const vehicle = (await response.json()) as Vehicle;
      setVehicles((current) => [...current, vehicle]);
      setShowDemo(true);
      selectVehicle(vehicle);
      setDemoDialogOpen(false);
      addFeedItem({
        kind: 'system',
        title: `Dodano demo linii ${vehicle.routeShortName}`,
        detail: 'Wirtualny pojazd jest wyraźnie oznaczony na mapie.',
        vehicleId: vehicle.vehicleId,
        vehicleMode: vehicle.vehicleMode,
      });
    } catch {
      setError('Nie udało się dodać pojazdu demo. Spróbuj ponownie.');
    } finally {
      setAddingDemo(false);
    }
  };

  const removeDemoVehicle = async (vehicleId: string) => {
    const response = await fetch(
      `${API_BASE}/demo/vehicles/${encodeURIComponent(vehicleId)}`,
      { method: 'DELETE' },
    );
    if (response.ok) {
      setVehicles((current) =>
        current.filter((vehicle) => vehicle.vehicleId !== vehicleId),
      );
      dispatchTracking({ type: 'remove', vehicleId });
    }
  };

  const realTramCount = vehicles.filter(
    (vehicle) => !vehicle.isSimulation && vehicle.vehicleMode === 'TRAM',
  ).length;
  const realBusCount = vehicles.filter(
    (vehicle) => !vehicle.isSimulation && vehicle.vehicleMode === 'BUS',
  ).length;
  const demoCount = vehicles.filter((vehicle) => vehicle.isSimulation).length;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand" aria-label="UrbanFlow">
          <Image
            src="/logo.svg"
            alt="UrbanFlow"
            className="brand-logo"
            width={42}
            height={42}
            priority
          />
        </div>
        <div className="topbar-center">
          <span className="city-label"><MapPin /> Kraków</span>
        </div>
        <div className="topbar-actions">
          <Button
            className="add-demo-button"
            onClick={() => setDemoDialogOpen(true)}
          >
            <Plus /> Dodaj demo
          </Button>
          <div className={`connection-pill ${connection}`}>
            <span className="status-dot" />
            {connection === 'live'
              ? 'Dane na żywo'
              : connection === 'connecting'
                ? 'Łączenie…'
                : 'Ponawianie…'}
          </div>
          <Button
            variant="outline"
            size="icon-lg"
            aria-label="Odśwież dane"
            onClick={() => void loadVehicles()}
          >
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </header>

      <section className={`workspace ${feedVisible ? '' : 'feed-hidden'}`}>
        <div className="map-stage">
          <div ref={mapContainer} className="map-canvas" aria-label="Mapa komunikacji miejskiej w Krakowie" />

          <button
            type="button"
            className="locate-button"
            aria-label="Wycentruj mapę na Krakowie"
            onClick={centerOnKrakow}
          >
            <LocateFixed />
          </button>

          {error && (
            <output className="error-toast">
              <WifiOff />
              <span>{error}</span>
              <button type="button" onClick={() => setError(null)} aria-label="Zamknij"><X /></button>
            </output>
          )}

          {selectedVehicle && (
            <article
              ref={trackingCardRef}
              className="vehicle-card"
              aria-label={`Śledzony pojazd linii ${selectedVehicle.routeShortName}`}
              aria-live="polite"
            >
              <div className="vehicle-card-topline">
                <div className="vehicle-route">
                  <span style={{ background: vehicleColor(selectedVehicle) }}>
                    {selectedVehicle.routeShortName}
                  </span>
                  <div>
                    <small>
                      {selectedVehicle.isSimulation
                        ? 'Wirtualny pojazd demo'
                        : selectedVehicle.vehicleMode === 'BUS'
                          ? 'Autobus ZTP'
                          : 'Tramwaj ZTP'}{' '}
                      · {selectedVehicle.vehicleId.split(':').at(-1)}
                    </small>
                    <strong>{selectedVehicle.headsign}</strong>
                  </div>
                </div>
                <button type="button" aria-label="Zamknij szczegóły" onClick={clearSelectedVehicle}><X /></button>
              </div>
              <div
                className={`tracking-strip ${
                  tracking.isTemporarilyMissing
                    ? 'missing'
                    : tracking.isFollowing
                      ? 'active'
                      : 'paused'
                }`}
              >
                <LocateFixed />
                <div>
                  <strong>
                    {tracking.isTemporarilyMissing
                      ? 'Ostatnia znana pozycja'
                      : tracking.isFollowing
                        ? 'Śledzenie aktywne'
                        : 'Śledzenie wstrzymane'}
                  </strong>
                  <small>
                    {tracking.isTemporarilyMissing
                      ? `Ostatnie dane ${selectedPositionAge}`
                      : tracking.isFollowing
                        ? 'Mapa podąża za pojazdem'
                        : 'Pozycja nadal aktualizuje się w tle'}
                  </small>
                </div>
                <Button
                  type="button"
                  size="xs"
                  variant="secondary"
                  onClick={toggleVehicleFollowing}
                >
                  {tracking.isFollowing ? 'Wstrzymaj' : 'Wznów'}
                </Button>
              </div>
              <div className="vehicle-next-stop">
                <Route />
                <div>
                  <small>Następny przystanek</small>
                  <strong>{selectedVehicle.nextStopName ?? 'Brak danych'}</strong>
                </div>
                <ChevronRight />
              </div>
              <div className="vehicle-metrics">
                <div>
                  <span><Users /> Zapełnienie</span>
                  <strong className={occupancyMeta[selectedVehicle.occupancyStatus].text}>
                    {selectedVehicle.loadFactor !== null
                      ? `${Math.round(selectedVehicle.loadFactor * 100)}%`
                      : '—'}
                  </strong>
                  <small>{occupancyMeta[selectedVehicle.occupancyStatus].label}</small>
                </div>
                <div>
                  <span><Clock3 /> Opóźnienie</span>
                  <strong className={`delay-value${selectedDelayBadge ? ` ${selectedDelayBadge.tone}` : ''}`}>
                    {relativeDelay(selectedVehicle.delaySeconds)}
                  </strong>
                  <small>względem rozkładu GTFS</small>
                </div>
              </div>
              <footer>
                <span><span className="status-dot" /> {selectedVehicle.freshness}</span>
                {selectedVehicle.isSimulation ? (
                  <button
                    type="button"
                    className="remove-demo-button"
                    onClick={() => void removeDemoVehicle(selectedVehicle.vehicleId)}
                  >
                    Usuń demo
                  </button>
                ) : (
                  <span>Pozycja {selectedPositionAge}</span>
                )}
              </footer>
            </article>
          )}

          <button type="button" className="mobile-feed-toggle" onClick={() => setMobilePanel(true)}>
            <Radio /> Live feed
            {feed.length > 0 && <span>{feed.length}</span>}
          </button>

          {!feedVisible && (
            <button
              type="button"
              className="feed-restore-button"
              onClick={() => setFeedVisible(true)}
            >
              <PanelRightOpen /> Pokaż live feed
            </button>
          )}
        </div>

        <aside className={`activity-panel ${mobilePanel ? 'mobile-open' : ''}`}>
          <div className="panel-header">
            <div>
              <span className="eyebrow">Aktualizacje</span>
              <h2>Live feed</h2>
            </div>
            <button type="button" className="mobile-close" aria-label="Zamknij panel" onClick={() => setMobilePanel(false)}><X /></button>
            <button
              type="button"
              className="panel-collapse-button"
              aria-label="Ukryj live feed"
              onClick={() => setFeedVisible(false)}
            >
              <PanelRightClose />
            </button>
            <span className="live-wave"><i /><i /><i /></span>
          </div>

          <div className="network-summary">
            <div>
              <span><TramFront /> Tramwaje</span>
              <strong>{realTramCount}</strong>
            </div>
            <div>
              <span><BusFront /> Autobusy</span>
              <strong>{realBusCount}</strong>
            </div>
            <div className="demo-stat">
              <span><Activity /> Demo</span>
              <strong>{demoCount}</strong>
            </div>
          </div>

          <div className="feed-list">
            {feed.length === 0 ? (
              <div className="feed-empty">
                <span><Wifi /></span>
                <strong>Nasłuchujemy sieci</strong>
                <p>Nowe pozycje i alerty pojawią się tutaj automatycznie.</p>
              </div>
            ) : (
              feed.map((item) => {
                const badge = delayBadge(item.delaySeconds);
                const canTrack = Boolean(item.vehicleId);
                const trackVehicle = () => {
                  if (item.vehicleId) selectVehicleById(item.vehicleId);
                };
                return (
                  <button
                    type="button"
                    className={`feed-item ${item.kind}${item.vehicleMode ? ` mode-${item.vehicleMode.toLowerCase()}` : ''}${canTrack ? ' trackable' : ''}`}
                    key={item.id}
                    disabled={!canTrack}
                    title={canTrack ? 'Pokaż i śledź pojazd na mapie' : undefined}
                    onClick={canTrack ? trackVehicle : undefined}
                  >
                    <span className="feed-icon">
                      {item.kind === 'warning' ? <AlertTriangle /> : item.kind === 'system' ? <Wifi /> : <ArrowDownRight />}
                    </span>
                    <div>
                      <time>{formatTime(item.at)}</time>
                      <strong>{item.title}</strong>
                      <p>{item.detail}</p>
                    </div>
                    {badge && (
                      <span className={`feed-delay ${badge.tone}`} aria-label={`Opóźnienie: ${badge.label}`}>
                        {badge.label}
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>

          <section className="panel-map-controls" aria-label="Warstwy i linie mapy">
            <div className="filter-heading">
              <span>Warstwy mapy</span>
              <Badge variant="secondary">{filteredVehicles.length}</Badge>
            </div>
            <div className="source-filters">
              <button
                type="button"
                className={showReal ? 'active' : ''}
                aria-pressed={showReal}
                onClick={() => setShowReal((value) => !value)}
              >
                <Radio /> Realne
              </button>
              <button
                type="button"
                className={showDemo ? 'active demo' : 'demo'}
                aria-pressed={showDemo}
                onClick={() => setShowDemo((value) => !value)}
              >
                <TramFront /> Demo
              </button>
            </div>
            <label className="route-filter-label" htmlFor="route-filter">
              Linia
            </label>
            <select
              id="route-filter"
              className="route-filter-select"
              value={lineFilter}
              onChange={(event) => setLineFilter(event.target.value)}
            >
              <option value="all">Wszystkie linie</option>
              {lineOptions.map(([routeId, shortName]) => (
                <option value={routeId} key={routeId}>{shortName}</option>
              ))}
            </select>
            <div className="legend">
              <span><i className="tram" /> Tramwaj</span>
              <span><i className="bus" /> Autobus</span>
              <span><i className="demo" /> Demo</span>
            </div>
          </section>

          <footer className="panel-footer">
            <span><span className="status-dot" /> WebSocket</span>
            <span>REST co 10 s</span>
          </footer>
        </aside>
      </section>

      {demoDialogOpen && (
        <div className="dialog-backdrop">
          <dialog
            open
            className="demo-dialog"
            aria-modal="true"
            aria-labelledby="demo-dialog-title"
          >
            <div className="dialog-icon"><TramFront /></div>
            <button
              type="button"
              className="dialog-close"
              aria-label="Zamknij"
              onClick={() => setDemoDialogOpen(false)}
            ><X /></button>
            <span className="eyebrow">Warstwa symulacyjna</span>
            <h2 id="demo-dialog-title">Dodaj wirtualny tramwaj</h2>
            <p>
              Pojazd pojedzie po rzeczywistej trasie, ale zawsze będzie oznaczony
              fioletem jako DEMO.
            </p>
            <label htmlFor="demo-route">Linia bazowa</label>
            <select
              id="demo-route"
              value={selectedDemoRouteId}
              onChange={(event) => setDemoRouteId(event.target.value)}
            >
              {demoRouteOptions.map((route) => (
                <option value={route.routeId} key={route.routeId}>
                  {route.shortName} · {route.longName}
                </option>
              ))}
            </select>
            <div className="dialog-actions">
              <Button variant="ghost" onClick={() => setDemoDialogOpen(false)}>
                Anuluj
              </Button>
              <Button
                onClick={() => void addDemoVehicle()}
                disabled={!selectedDemoRouteId || addingDemo}
              >
                {addingDemo ? <RefreshCw className="animate-spin" /> : <Plus />}
                Dodaj na mapę
              </Button>
            </div>
          </dialog>
        </div>
      )}
    </main>
  );
}

'use client';

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
  LayerSpecification,
  Map as MapLibreMap,
  MapLayerMouseEvent,
} from 'maplibre-gl';
import {
  Activity,
  BusFront,
  LocateFixed,
  MapPin,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  Radio,
  RefreshCw,
  Send,
  Accessibility,
  ChevronLeft,
  ChevronRight,
  TramFront,
  Users,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react';

import { AnimatePresence, MotionConfig, motion } from 'motion/react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { BrandWordmark } from '@/components/brand-wordmark';
import { AnimatedNumber, cardMotion, spring } from '@/components/motion-primitives';
import { TramFill } from '@/components/tram-fill';
import { loadMapLibre } from '@/lib/maplibre';
import { API_BASE, WS_URL } from '@/lib/api';

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
  mobilityAids?: MobilityAids | null;
};

type MobilityAids = {
  wheelchairs: number;
  strollers: number;
  bicycles: number;
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
  loadFactor?: number | null;
  occupancy?: Occupancy;
  vehicleMode?: VehicleMode;
  vehicleId?: string;
};

type Recommendation = {
  id: string;
  status: 'OPEN' | 'ACCEPTED' | 'DISMISSED';
  routeId: string;
  routeShortName: string;
  directionId: number;
  reason: {
    loadFactor: number;
    durationSeconds: number;
    nextVehicleHeadwaySeconds: number;
    measurementConfidence: number;
  };
  proposedAction: {
    departureDelaySeconds: number;
    capacity: number;
    startStopId: string;
    endStopId: string;
  };
  expectedImpact: {
    estimatedWaitingPassengersServed: number;
    passengerMinutesSaved: number;
    projectedPeakLoadFactor: number;
  };
  createdAt: string;
};

type Dispatch = {
  dispatchId: string;
  vehicleId: string;
  routeId: string;
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


const occupancyMeta: Record<
  Occupancy,
  { label: string; color: string; text: string }
> = {
  UNKNOWN: { label: 'Brak danych', color: '#7b8794', text: 'text-slate-500' },
  LOW: { label: 'Niskie', color: '#00b3a4', text: 'text-teal-700' },
  MODERATE: { label: 'Umiarkowane', color: '#e4b63a', text: 'text-amber-700' },
  BUSY: { label: 'Wysokie', color: '#ef8d32', text: 'text-orange-700' },
  CROWDED: { label: 'Tłok', color: '#ee5b50', text: 'text-red-700' },
  OVER_CAPACITY: {
    label: 'Przepełnienie',
    color: '#c9303e',
    text: 'text-red-800',
  },
};

// A slow, watchable run for the pitch: the backend drives 900 simulated seconds,
// so speed 5 keeps the reserve on the map for three minutes.
const DISPATCH_SIMULATION_SPEED = 5;
const RECOMMENDATIONS_REFRESH_MS = 5_000;
// Mirrors the decision engine's overload threshold, shown on the capacity bar.
const RESERVE_THRESHOLD = 0.85;
// The feed's "Tłok" filter starts at the BUSY band, a step before the engine acts.
const CROWDING_FEED_THRESHOLD = 0.7;
const FOCUS_LAYER_IDS = [
  'vehicle-halo',
  'vehicle-marker',
  'vehicle-label',
  'vehicle-hit-area',
] as const;

function hasCounterReading(vehicle: Vehicle) {
  return !vehicle.isSimulation && vehicle.loadFactor !== null;
}

function isCrowded(vehicle: Vehicle) {
  return (
    vehicle.occupancyStatus === 'CROWDED' ||
    vehicle.occupancyStatus === 'OVER_CAPACITY'
  );
}

function vehicleColor(vehicle: Vehicle) {
  if (hasStalePosition(vehicle)) return '#93a2a9';
  if (vehicle.isSimulation) return '#5267ff';
  // Vehicles with a door counter wear their occupancy; the rest keep the mode
  // color, so crowding is the thing that stands out on the map.
  if (hasCounterReading(vehicle)) {
    return occupancyMeta[vehicle.occupancyStatus].color;
  }
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
      crowded: hasCounterReading(vehicle) && isCrowded(vehicle),
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

/** Two soft sine notes, synthesised, so the alert needs no audio asset. */
function playChime() {
  try {
    const context = new AudioContext();
    [660, 880].forEach((frequency, index) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const start = context.currentTime + index * 0.14;
      oscillator.type = 'sine';
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.12, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + 0.4);
    });
    window.setTimeout(() => void context.close(), 800);
  } catch {
    // Audio blocked before any user gesture; the visual alert still shows.
  }
}

function plural(count: number, one: string, few: string, many: string) {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return one;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return few;
  return many;
}

/** "1 wózek inwalidzki · 2 rowery", or null when the cabin camera sees none. */
function describeAids(aids: MobilityAids | null | undefined) {
  if (!aids) return null;
  const parts = [
    aids.wheelchairs > 0 &&
      `${aids.wheelchairs} ${plural(aids.wheelchairs, 'wózek inwalidzki', 'wózki inwalidzkie', 'wózków inwalidzkich')}`,
    aids.strollers > 0 &&
      `${aids.strollers} ${plural(aids.strollers, 'wózek dziecięcy', 'wózki dziecięce', 'wózków dziecięcych')}`,
    aids.bicycles > 0 &&
      `${aids.bicycles} ${plural(aids.bicycles, 'rower', 'rowery', 'rowerów')}`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : null;
}

function formatAgo(timestamp: string, now: number) {
  const minutes = Math.floor((now - new Date(timestamp).getTime()) / 60_000);
  if (minutes < 1) return 'przed chwilą';
  if (minutes < 60) return `${minutes} min temu`;
  return `${Math.floor(minutes / 60)} godz. temu`;
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
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [dispatchingId, setDispatchingId] = useState<string | null>(null);
  const [lastDispatch, setLastDispatch] = useState<Dispatch | null>(null);
  const pendingFocusIdRef = useRef<string | null>(null);
  const [stagedIds, setStagedIds] = useState<string[]>([]);
  const [staging, setStaging] = useState(false);
  const [feedFilter, setFeedFilter] = useState<'all' | 'crowding'>('all');
  const [recommendationIndex, setRecommendationIndex] = useState(0);
  const [freshRecommendationId, setFreshRecommendationId] = useState<string | null>(null);
  const seenRecommendationIdsRef = useRef<Set<string> | null>(null);

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
            detail: vehicle.nextStopName ?? 'W trasie',
            at: new Date(vehicle.updatedAt),
            delaySeconds: vehicle.delaySeconds,
            loadFactor: vehicle.loadFactor,
            occupancy: vehicle.occupancyStatus,
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
    return () => window.clearTimeout(initialRequest);
  }, [loadVehicles]);

  // Without the WebSocket, REST is the only source of movement; poll fast enough
  // that a dispatched reserve still glides instead of jumping every ten seconds.
  useEffect(() => {
    const period = connection === 'live' ? 10_000 : 2_000;
    const interval = window.setInterval(() => void loadVehicles(true), period);
    return () => window.clearInterval(interval);
  }, [connection, loadVehicles]);

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
            detail: `${vehicle.isSimulation ? 'Symulacja · ' : ''}${
              vehicle.nextStopName ?? 'W trasie'
            }`,
            delaySeconds: vehicle.delaySeconds,
            loadFactor: vehicle.loadFactor,
            occupancy: vehicle.occupancyStatus,
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
        if (message.type === 'recommendation.created') {
          const recommendation = message.payload as unknown as Recommendation;
          if (recommendation.status !== 'OPEN') return;
          setRecommendations((current) =>
            current.some((item) => item.id === recommendation.id)
              ? current
              : [recommendation, ...current],
          );
          addFeedItem({
            kind: 'warning',
            title: `Linia ${recommendation.routeShortName} przeładowana`,
            detail: `${Math.round(recommendation.reason.loadFactor * 100)}% przez ${Math.round(
              recommendation.reason.durationSeconds / 60,
            )} min · proponujemy rezerwę`,
          });
          return;
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

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [response, staged] = await Promise.all([
          fetch(`${API_BASE}/recommendations?status=OPEN`),
          fetch(`${API_BASE}/demo/overload`),
        ]);
        if (cancelled) return;
        if (response.ok) setRecommendations((await response.json()) as Recommendation[]);
        if (staged.ok) setStagedIds((await staged.json()) as string[]);
      } catch {
        // The vehicle poll already reports a lost backend; stay quiet here.
      }
    };
    void load();
    const interval = window.setInterval(
      () => void load(),
      RECOMMENDATIONS_REFRESH_MS,
    );
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

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

  // A dispatched reserve reaches the map over the WebSocket a moment after the
  // dispatch call returns; follow it as soon as it appears.
  useEffect(() => {
    const pendingId = pendingFocusIdRef.current;
    if (!pendingId) return;
    const vehicle = vehicles.find((item) => item.vehicleId === pendingId);
    if (!vehicle) return;
    pendingFocusIdRef.current = null;
    selectVehicle(vehicle);
  }, [selectVehicle, vehicles]);

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

    void loadMapLibre().then((maplibregl) => {
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
              ['boolean', ['get', 'crowded'], false],
              30,
              18,
            ],
            'circle-color': ['get', 'color'],
            'circle-opacity': [
              'case',
              ['boolean', ['get', 'selected'], false],
              0.3,
              ['boolean', ['get', 'crowded'], false],
              0.28,
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
        // The tracked vehicle and crowded trams never hide inside a cluster: they
        // get their own unclustered source, drawn above everything else.
        map.addSource('vehicles-focus', {
          type: 'geojson',
          data: createVehicleGeoJson([]),
        });
        for (const id of FOCUS_LAYER_IDS) {
          const layer = map.getLayer(id)?.serialize() as LayerSpecification | undefined;
          if (!layer) continue;
          map.addLayer({
            ...layer,
            id: `${id}-focus`,
            source: 'vehicles-focus',
          } as LayerSpecification);
        }
        map.on('click', 'vehicle-hit-area-focus', selectVehicle);
        map.on('mouseenter', 'vehicle-hit-area-focus', showPointer);
        map.on('mouseleave', 'vehicle-hit-area-focus', hidePointer);
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
    const isFocused = (vehicle: Vehicle) =>
      vehicle.vehicleId === tracking.vehicleId ||
      (hasCounterReading(vehicle) && isCrowded(vehicle));
    void source.setData(
      createVehicleGeoJson(
        filteredVehicles.filter((vehicle) => !isFocused(vehicle)),
        tracking.vehicleId,
      ),
    );
    const focusSource = map.getSource('vehicles-focus') as
      | GeoJSONSource
      | undefined;
    void focusSource?.setData(
      createVehicleGeoJson(filteredVehicles.filter(isFocused), tracking.vehicleId),
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

  // The pill reports whether the map is current, not which transport carried it:
  // REST polling every two seconds is still live data.
  const feedStatus: 'live' | 'polling' | 'offline' =
    connection === 'live' ? 'live' : error ? 'offline' : 'polling';

  // "Tłok" is the current state of the network, not feed history: every counted
  // vehicle above the threshold, fullest first.
  const visibleFeed: FeedItem[] =
    feedFilter === 'all'
      ? feed
      : vehicles
          .filter(
            (vehicle) =>
              hasCounterReading(vehicle) &&
              (vehicle.loadFactor ?? 0) >= CROWDING_FEED_THRESHOLD,
          )
          .sort((a, b) => (b.loadFactor ?? 0) - (a.loadFactor ?? 0))
          .map((vehicle) => ({
            id: `crowded-${vehicle.vehicleId}`,
            kind: isCrowded(vehicle) ? 'warning' : 'update',
            title: `Linia ${vehicle.routeShortName} · ${vehicle.headsign}`,
            detail:
              vehicle.passengerCount !== null && vehicle.capacity !== null
                ? `${vehicle.passengerCount} z ${vehicle.capacity} osób · ${vehicle.nextStopName ?? 'w trasie'}`
                : (vehicle.nextStopName ?? 'W trasie'),
            at: new Date(vehicle.updatedAt),
            delaySeconds: vehicle.delaySeconds,
            loadFactor: vehicle.loadFactor,
            occupancy: vehicle.occupancyStatus,
            vehicleMode: vehicle.vehicleMode,
            vehicleId: vehicle.vehicleId,
          }));

  const sortedRecommendations = useMemo(
    () =>
      [...recommendations].sort(
        (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
      ),
    [recommendations],
  );
  const activeRecommendation =
    sortedRecommendations[
      Math.min(recommendationIndex, sortedRecommendations.length - 1)
    ] ?? null;

  // Same direction first; a tram that reached its terminus and turned back is
  // still the one the recommendation is about.
  const crowdedVehicleFor = (recommendation: Recommendation) =>
    vehicles
      .filter(
        (vehicle) =>
          vehicle.routeId === recommendation.routeId &&
          hasCounterReading(vehicle),
      )
      .sort(
        (a, b) =>
          Number(b.directionId === recommendation.directionId) -
            Number(a.directionId === recommendation.directionId) ||
          (b.loadFactor ?? 0) - (a.loadFactor ?? 0),
      )[0];

  const showRecommendedVehicle = (recommendation: Recommendation) => {
    const vehicle = crowdedVehicleFor(recommendation);
    if (vehicle) selectVehicle(vehicle);
  };

  const sendReserve = async (recommendation: Recommendation) => {
    setDispatchingId(recommendation.id);
    try {
      const response = await fetch(`${API_BASE}/mock-dispatch/extra-trams`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          recommendationId: recommendation.id,
          routeId: recommendation.routeId,
          directionId: recommendation.directionId,
          startStopId: recommendation.proposedAction.startStopId,
          endStopId: recommendation.proposedAction.endStopId,
          capacity: recommendation.proposedAction.capacity,
          departureDelaySeconds: 0,
          simulationSpeed: DISPATCH_SIMULATION_SPEED,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const dispatch = (await response.json()) as Dispatch;
      setRecommendations((current) =>
        current.filter((item) => item.id !== recommendation.id),
      );
      setLastDispatch(dispatch);
      setShowDemo(true);
      pendingFocusIdRef.current = dispatch.vehicleId;
      addFeedItem({
        kind: 'system',
        title: `Rezerwa wysłana na linię ${recommendation.routeShortName}`,
        detail: `${dispatch.vehicleId} rusza trasą linii`,
        vehicleId: dispatch.vehicleId,
        vehicleMode: 'TRAM',
      });
    } catch {
      setError('Nie udało się wysłać rezerwy. Spróbuj ponownie.');
    } finally {
      setDispatchingId(null);
    }
  };

  // A recommendation that arrives while the dashboard is open gets announced: the
  // card jumps to it, pulses and chimes. Ones already open at load are not news.
  useEffect(() => {
    const ids = recommendations.map((item) => item.id);
    const seen = seenRecommendationIdsRef.current;
    seenRecommendationIdsRef.current = new Set([...(seen ?? []), ...ids]);
    if (!seen) return;
    const arrived = sortedRecommendations.find((item) => !seen.has(item.id));
    if (!arrived) return;
    setRecommendationIndex(0);
    setFreshRecommendationId(arrived.id);
    playChime();
    const timer = window.setTimeout(() => setFreshRecommendationId(null), 5_000);
    return () => window.clearTimeout(timer);
  }, [recommendations, sortedRecommendations]);

  useEffect(() => {
    document.title =
      recommendations.length > 0
        ? `(${recommendations.length}) UrbanFlow — centrum operacyjne`
        : 'UrbanFlow — centrum operacyjne';
  }, [recommendations.length]);

  const stageOverload = async () => {
    setStaging(true);
    try {
      const response = await fetch(`${API_BASE}/demo/overload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const vehicle = (await response.json()) as Vehicle;
      setStagedIds((current) => [...new Set([...current, vehicle.vehicleId])]);
      setVehicles((current) =>
        current.map((item) => (item.vehicleId === vehicle.vehicleId ? vehicle : item)),
      );
      setShowReal(true);
      selectVehicle(vehicle);
      addFeedItem({
        kind: 'warning',
        title: `Linia ${vehicle.routeShortName} · ${vehicle.headsign}`,
        detail: `${vehicle.passengerCount ?? '—'} z ${vehicle.capacity ?? '—'} osób · rekomendacja za ok. 2 min`,
        loadFactor: vehicle.loadFactor,
        occupancy: vehicle.occupancyStatus,
        vehicleId: vehicle.vehicleId,
        vehicleMode: vehicle.vehicleMode,
      });
    } catch {
      setError('Nie udało się zasymulować tłoku. Czy na mapie są tramwaje?');
    } finally {
      setStaging(false);
    }
  };

  const stopOverload = async (vehicleId: string) => {
    setStagedIds((current) => current.filter((id) => id !== vehicleId));
    await fetch(`${API_BASE}/demo/overload/${encodeURIComponent(vehicleId)}`, {
      method: 'DELETE',
    }).catch(() => undefined);
  };

  const dismissRecommendation = async (recommendation: Recommendation) => {
    setRecommendations((current) =>
      current.filter((item) => item.id !== recommendation.id),
    );
    await fetch(
      `${API_BASE}/recommendations/${encodeURIComponent(recommendation.id)}/dismiss`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Odrzucone przez dyspozytora' }),
      },
    ).catch(() => undefined);
  };

  const realTramCount = vehicles.filter(
    (vehicle) => !vehicle.isSimulation && vehicle.vehicleMode === 'TRAM',
  ).length;
  const realBusCount = vehicles.filter(
    (vehicle) => !vehicle.isSimulation && vehicle.vehicleMode === 'BUS',
  ).length;
  const demoCount = vehicles.filter((vehicle) => vehicle.isSimulation).length;

  return (
    <MotionConfig reducedMotion="user">
    <main className="app-shell">
      <header className="topbar">
        {/* oxlint-disable-next-line no-html-link-for-pages -- vinext client navigation does not run in the production build; a full page load does. */}
        <a href="/" className="brand" aria-label="UrbanFlow — strona główna">
          <BrandWordmark size={26} />
        </a>
        <div className="topbar-center">
          <span className="city-label"><MapPin /> Kraków</span>
        </div>
        <div className="topbar-actions">
          <Button
            className="stage-overload-button"
            disabled={staging}
            onClick={() => void stageOverload()}
          >
            {staging ? <RefreshCw className="animate-spin" /> : <Users />}
            Symuluj tłok
          </Button>
          <Button
            variant="outline"
            className="add-demo-button"
            onClick={() => setDemoDialogOpen(true)}
          >
            <Plus /> Dodaj demo
          </Button>
          <div className={`connection-pill ${feedStatus}`}>
            <span className="status-dot" />
            {feedStatus === 'live'
              ? 'Dane na żywo'
              : feedStatus === 'polling'
                ? 'Dane na żywo · co 2 s'
                : 'Brak połączenia'}
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

          <AnimatePresence>
          {error && (
            <motion.output
              className="error-toast"
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={spring}
            >
              <WifiOff />
              <span>{error}</span>
              <button type="button" onClick={() => setError(null)} aria-label="Zamknij"><X /></button>
            </motion.output>
          )}
          </AnimatePresence>

          <AnimatePresence mode="popLayout">
          {activeRecommendation && (
            <motion.article
              key={activeRecommendation.id}
              {...cardMotion}
              className={`recommendation-card${
                freshRecommendationId === activeRecommendation.id ? ' is-fresh' : ''
              }`}
              aria-live="assertive"
              aria-labelledby="recommendation-title"
            >
              <div className="rec-meta">
                <span className="rec-dot" aria-hidden="true" />
                {freshRecommendationId === activeRecommendation.id ? (
                  <span className="rec-new">Nowa rekomendacja</span>
                ) : (
                  <span>
                    Rekomendacja · {formatAgo(activeRecommendation.createdAt, now)}
                  </span>
                )}
                {sortedRecommendations.length > 1 && (
                  <span className="rec-pager">
                    <button
                      type="button"
                      aria-label="Poprzednia rekomendacja"
                      disabled={recommendationIndex === 0}
                      onClick={() => setRecommendationIndex((index) => index - 1)}
                    >
                      <ChevronLeft />
                    </button>
                    <span>
                      {recommendationIndex + 1} z {sortedRecommendations.length}
                    </span>
                    <button
                      type="button"
                      aria-label="Następna rekomendacja"
                      disabled={recommendationIndex >= sortedRecommendations.length - 1}
                      onClick={() => setRecommendationIndex((index) => index + 1)}
                    >
                      <ChevronRight />
                    </button>
                  </span>
                )}
              </div>
              <strong id="recommendation-title" className="rec-title">
                Linia {activeRecommendation.routeShortName} jest przepełniona
              </strong>
              <p className="rec-facts">
                <span className="rec-load">
                  {Math.round(activeRecommendation.reason.loadFactor * 100)}%
                </span>{' '}
                zapełnienia przez{' '}
                {Math.round(activeRecommendation.reason.durationSeconds / 60)} min ·
                rezerwa na {activeRecommendation.proposedAction.capacity} miejsc
              </p>
              <div className="recommendation-actions">
                <Button
                  size="sm"
                  className="send-reserve-button"
                  disabled={dispatchingId === activeRecommendation.id}
                  onClick={() => void sendReserve(activeRecommendation)}
                >
                  {dispatchingId === activeRecommendation.id && (
                    <RefreshCw className="animate-spin" />
                  )}
                  Wyślij rezerwę
                </Button>
                {crowdedVehicleFor(activeRecommendation) && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => showRecommendedVehicle(activeRecommendation)}
                  >
                    Pokaż tramwaj
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="dismiss-button"
                  onClick={() => void dismissRecommendation(activeRecommendation)}
                >
                  Odrzuć
                </Button>
              </div>
            </motion.article>
          )}
          </AnimatePresence>

          <AnimatePresence>
          {!activeRecommendation && lastDispatch && (
            <motion.output className="dispatch-toast" {...cardMotion}>
              <Send />
              <span>
                <strong>{lastDispatch.vehicleId}</strong> jedzie jako rezerwa
              </span>
              <button
                type="button"
                onClick={() => selectVehicleById(lastDispatch.vehicleId)}
              >
                Śledź
              </button>
              <button
                type="button"
                aria-label="Zamknij"
                onClick={() => setLastDispatch(null)}
              ><X /></button>
            </motion.output>
          )}
          </AnimatePresence>

          <AnimatePresence>
          {selectedVehicle && (
            <motion.article
              ref={trackingCardRef}
              className="vehicle-card"
              initial={{ opacity: 0, y: 16, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 12, scale: 0.98, transition: { duration: 0.15 } }}
              transition={spring}
              aria-label={`Śledzony pojazd linii ${selectedVehicle.routeShortName}`}
              aria-live="polite"
            >
              <header className="vc-head">
                <span className="vc-line" style={{ background: vehicleColor(selectedVehicle) }}>
                  {selectedVehicle.routeShortName}
                </span>
                <div className="vc-title">
                  <strong>{selectedVehicle.headsign}</strong>
                  <span>
                    {selectedVehicle.nextStopName
                      ? `Następny: ${selectedVehicle.nextStopName}`
                      : 'W trasie'}
                    {selectedDelayBadge && (
                      <>
                        {' · '}
                        <span className={`vc-delay ${selectedDelayBadge.tone}`}>
                          {selectedDelayBadge.label}
                        </span>
                      </>
                    )}
                  </span>
                </div>
                <div className="vc-actions">
                  <button
                    type="button"
                    className="vc-icon"
                    aria-pressed={tracking.isFollowing}
                    aria-label={tracking.isFollowing ? 'Wstrzymaj śledzenie' : 'Śledź pojazd'}
                    title={tracking.isFollowing ? 'Wstrzymaj śledzenie' : 'Śledź pojazd'}
                    onClick={toggleVehicleFollowing}
                  >
                    <LocateFixed />
                  </button>
                  <button
                    type="button"
                    className="vc-icon"
                    aria-label="Zamknij szczegóły"
                    onClick={clearSelectedVehicle}
                  >
                    <X />
                  </button>
                </div>
              </header>

              {selectedVehicle.loadFactor !== null ? (
                <section className="vc-load" aria-label="Zapełnienie">
                  <div className="vc-load-row">
                    <strong
                      className="vc-load-value"
                      style={
                        isCrowded(selectedVehicle) ||
                        selectedVehicle.occupancyStatus === 'BUSY'
                          ? { color: occupancyMeta[selectedVehicle.occupancyStatus].color }
                          : undefined
                      }
                    >
                      <AnimatedNumber value={Math.round(selectedVehicle.loadFactor * 100)} />%
                    </strong>
                    <span className="vc-load-label">
                      {occupancyMeta[selectedVehicle.occupancyStatus].label}
                    </span>
                    {selectedVehicle.passengerCount !== null &&
                      selectedVehicle.capacity !== null && (
                        <span className="vc-load-count">
                          {selectedVehicle.passengerCount} / {selectedVehicle.capacity} osób
                        </span>
                      )}
                  </div>
                  {selectedVehicle.passengerCount !== null &&
                  selectedVehicle.capacity !== null ? (
                    <TramFill
                      passengers={selectedVehicle.passengerCount}
                      capacity={selectedVehicle.capacity}
                      color={occupancyMeta[selectedVehicle.occupancyStatus].color}
                    />
                  ) : null}
                  {describeAids(selectedVehicle.mobilityAids) && (
                    <p className="vc-aids">
                      <Accessibility aria-hidden="true" />
                      W środku też: {describeAids(selectedVehicle.mobilityAids)}
                    </p>
                  )}
                  <p className="vc-threshold-note">
                    Rezerwa proponowana od {RESERVE_THRESHOLD * 100}% zapełnienia przez 2 min
                  </p>
                </section>
              ) : (
                <p className="vc-load-empty">
                  Zapełnienie nieznane — ten pojazd nie ma licznika pasażerów.
                </p>
              )}

              <footer className="vc-foot">
                <span>
                  {selectedVehicle.isSimulation
                    ? 'Pojazd demo'
                    : `${selectedVehicle.vehicleMode === 'BUS' ? 'Autobus' : 'Tramwaj'} ${selectedVehicle.vehicleId.split(':').at(-1)}`}
                  {' · '}
                  {tracking.isTemporarilyMissing
                    ? `ostatnia pozycja ${selectedPositionAge}`
                    : `pozycja ${selectedPositionAge}`}
                </span>
                {selectedVehicle.isSimulation ? (
                  <button
                    type="button"
                    className="vc-link"
                    onClick={() => void removeDemoVehicle(selectedVehicle.vehicleId)}
                  >
                    Usuń demo
                  </button>
                ) : (
                  stagedIds.includes(selectedVehicle.vehicleId) && (
                    <button
                      type="button"
                      className="vc-link"
                      onClick={() => void stopOverload(selectedVehicle.vehicleId)}
                    >
                      Zakończ symulację
                    </button>
                  )
                )}
              </footer>
            </motion.article>
          )}
          </AnimatePresence>

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
            <h2>Na żywo</h2>
            <fieldset className="feed-filter" aria-label="Filtr zdarzeń">
              <button
                type="button"
                aria-pressed={feedFilter === 'all'}
                onClick={() => setFeedFilter('all')}
              >
                {feedFilter === 'all' && (
                  <motion.span layoutId="feed-filter-pill" className="feed-filter-pill" transition={spring} />
                )}
                <span>Wszystkie</span>
              </button>
              <button
                type="button"
                aria-pressed={feedFilter === 'crowding'}
                onClick={() => setFeedFilter('crowding')}
              >
                {feedFilter === 'crowding' && (
                  <motion.span layoutId="feed-filter-pill" className="feed-filter-pill" transition={spring} />
                )}
                <span>Tłok</span>
              </button>
            </fieldset>
            <button type="button" className="mobile-close" aria-label="Zamknij panel" onClick={() => setMobilePanel(false)}><X /></button>
            <button
              type="button"
              className="panel-collapse-button"
              aria-label="Ukryj live feed"
              onClick={() => setFeedVisible(false)}
            >
              <PanelRightClose />
            </button>
          </div>

          <div className="network-summary">
            <div>
              <span><TramFront /> Tramwaje</span>
              <strong><AnimatedNumber value={realTramCount} /></strong>
            </div>
            <div>
              <span><BusFront /> Autobusy</span>
              <strong><AnimatedNumber value={realBusCount} /></strong>
            </div>
            <div className="demo-stat">
              <span><Activity /> Demo</span>
              <strong><AnimatedNumber value={demoCount} /></strong>
            </div>
          </div>

          <div className="feed-list">
            {visibleFeed.length === 0 && feedFilter === 'crowding' ? (
              <div className="feed-empty">
                <strong>Żaden pojazd nie jest teraz zatłoczony</strong>
                <p>Tu pojawią się tramwaje z licznikiem powyżej 70% zapełnienia.</p>
              </div>
            ) : feed.length === 0 ? (
              <div className="feed-empty">
                <span><Wifi /></span>
                <strong>Nasłuchujemy sieci</strong>
                <p>Nowe pozycje i alerty pojawią się tutaj automatycznie.</p>
              </div>
            ) : (
              <AnimatePresence initial={false}>
              {visibleFeed.map((item) => {
                const badge = delayBadge(item.delaySeconds);
                const load =
                  item.loadFactor !== null && item.loadFactor !== undefined
                    ? Math.round(item.loadFactor * 100)
                    : null;
                const canTrack = Boolean(item.vehicleId);
                const trackVehicle = () => {
                  if (item.vehicleId) selectVehicleById(item.vehicleId);
                };
                return (
                  <motion.button
                    layout="position"
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, transition: { duration: 0.12 } }}
                    transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
                    type="button"
                    className={`feed-item ${item.kind}${item.vehicleMode ? ` mode-${item.vehicleMode.toLowerCase()}` : ''}${canTrack ? ' trackable' : ''}`}
                    key={item.id}
                    disabled={!canTrack}
                    title={canTrack ? 'Pokaż i śledź pojazd na mapie' : undefined}
                    onClick={canTrack ? trackVehicle : undefined}
                  >
                    <span className="feed-marker" aria-hidden="true" />
                    <div>
                      <time>{formatTime(item.at)}</time>
                      <strong>{item.title}</strong>
                      <p>{item.detail}</p>
                    </div>
                    <span className="feed-values">
                      {load !== null && item.occupancy && (
                        <span
                          className="feed-load"
                          style={{ color: occupancyMeta[item.occupancy].color }}
                          aria-label={`Zapełnienie: ${load}%, ${occupancyMeta[item.occupancy].label}`}
                        >
                          {load}%
                        </span>
                      )}
                      {badge && (
                        <span className={`feed-delay ${badge.tone}`} aria-label={`Opóźnienie: ${badge.label}`}>
                          {badge.label}
                        </span>
                      )}
                    </span>
                  </motion.button>
                );
              })}
              </AnimatePresence>
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
          </section>

          <footer className={`panel-footer ${feedStatus}`}>
            <span>
              <span className="status-dot" />
              {feedStatus === 'live'
                ? 'Aktualizacje przez WebSocket'
                : feedStatus === 'polling'
                  ? 'WebSocket niedostępny, odświeżanie co 2 s'
                  : 'Backend nie odpowiada'}
            </span>
          </footer>
        </aside>
      </section>

      <AnimatePresence>
      {demoDialogOpen && (
        <motion.div
          className="dialog-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.12 } }}
          transition={{ duration: 0.18 }}
        >
          <motion.dialog
            initial={{ opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.12 } }}
            transition={spring}
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
          </motion.dialog>
        </motion.div>
      )}
      </AnimatePresence>
    </main>
    </MotionConfig>
  );
}

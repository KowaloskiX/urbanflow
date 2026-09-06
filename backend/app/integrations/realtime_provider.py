import asyncio
import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from io import BytesIO, TextIOWrapper
from zoneinfo import ZoneInfo
from zipfile import ZipFile

import httpx
from google.transit import gtfs_realtime_pb2

from app.domain.route import RouteSummary
from app.domain.vehicle import Freshness, OccupancyStatus, VehicleMode, VehicleState


@dataclass(frozen=True)
class TripInfo:
    route_id: str
    headsign: str
    direction_id: int
    shape_id: str


@dataclass(frozen=True)
class ScheduledStopTime:
    arrival_seconds: int


@dataclass(frozen=True)
class ObservedPassage:
    trip_id: str
    stop_sequence: int
    delay_seconds: int | None


@dataclass
class TripDelay:
    """GTFS-RT delays are deviations from the matching GTFS timetable."""

    default_seconds: int | None = None
    by_stop_sequence: dict[int, int] = field(default_factory=dict)

    def for_stop_sequence(self, sequence: int | None) -> int | None:
        if sequence is None:
            return self.default_seconds
        if sequence in self.by_stop_sequence:
            return self.by_stop_sequence[sequence]
        future_sequences = sorted(
            candidate
            for candidate in self.by_stop_sequence
            if candidate >= sequence
        )
        if future_sequences:
            return self.by_stop_sequence[future_sequences[0]]
        return self.default_seconds


@dataclass
class StaticFeed:
    mode: VehicleMode
    prefix: str
    routes: dict[str, RouteSummary] = field(default_factory=dict)
    route_ids: dict[str, str] = field(default_factory=dict)
    trips: dict[str, TripInfo] = field(default_factory=dict)
    stop_times: dict[str, dict[int, ScheduledStopTime]] = field(
        default_factory=dict
    )
    stops: dict[str, str] = field(default_factory=dict)
    shapes: dict[tuple[str, int], list[list[float]]] = field(default_factory=dict)


@dataclass
class RealtimeSnapshot:
    vehicles: list[VehicleState]
    routes: dict[str, RouteSummary]
    shapes: dict[tuple[str, int], list[list[float]]]
    modes_online: set[VehicleMode]


class KrakowRealtimeProvider:
    """Official ZTP Kraków GTFS + GTFS-Realtime adapter for buses and trams."""

    FEEDS = {
        VehicleMode.BUS: ("A", "ztp-bus"),
        VehicleMode.TRAM: ("T", "ztp-tram"),
    }

    def __init__(
        self,
        base_url: str,
        live_max_age_seconds: int,
        stale_max_age_seconds: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.live_max_age_seconds = live_max_age_seconds
        self.stale_max_age_seconds = stale_max_age_seconds
        self.static_feeds: dict[VehicleMode, StaticFeed] = {}
        self.observed_passages: dict[str, ObservedPassage] = {}
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(45, connect=10),
            headers={"User-Agent": "UrbanFlow/0.2 (+dispatcher dashboard)"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def initialize(self) -> None:
        missing = [
            (mode, suffix, prefix)
            for mode, (suffix, prefix) in self.FEEDS.items()
            if mode not in self.static_feeds
        ]
        if not missing:
            return
        feeds = await asyncio.gather(
            *(
                self._load_static(mode, suffix, prefix)
                for mode, suffix, prefix in missing
            ),
            return_exceptions=True,
        )
        for (mode, _, _), result in zip(missing, feeds, strict=True):
            if isinstance(result, StaticFeed):
                self.static_feeds[mode] = result

    async def get_snapshot(self) -> RealtimeSnapshot:
        if len(self.static_feeds) < len(self.FEEDS):
            await self.initialize()

        results = await asyncio.gather(
            *(
                self._load_mode_vehicles(mode, suffix)
                for mode, (suffix, _) in self.FEEDS.items()
            ),
            return_exceptions=True,
        )
        vehicles: list[VehicleState] = []
        modes_online: set[VehicleMode] = set()
        for mode, result in zip(self.FEEDS, results, strict=True):
            if isinstance(result, list):
                vehicles.extend(result)
                modes_online.add(mode)

        routes: dict[str, RouteSummary] = {}
        shapes: dict[tuple[str, int], list[list[float]]] = {}
        for feed in self.static_feeds.values():
            routes.update(feed.routes)
            shapes.update(feed.shapes)
        return RealtimeSnapshot(vehicles, routes, shapes, modes_online)

    async def _load_mode_vehicles(
        self, mode: VehicleMode, suffix: str
    ) -> list[VehicleState]:
        static = self.static_feeds.get(mode)
        if static is None:
            raise RuntimeError(f"Static feed unavailable for {mode}")
        positions, trip_delays = await asyncio.gather(
            self._load_positions(mode, suffix),
            self._load_trip_delays(suffix),
            return_exceptions=True,
        )
        if isinstance(positions, Exception):
            raise positions
        delays = trip_delays if isinstance(trip_delays, dict) else {}
        enriched: list[VehicleState] = []
        for vehicle in positions:
            official_delay = delays.get(
                vehicle.trip_id.partition(":")[2], TripDelay()
            ).for_stop_sequence(vehicle.current_stop_sequence)
            observed_delay = self._observe_stop_passage(vehicle, static)
            enriched.append(
                vehicle.model_copy(
                    update={
                        # The operator's GTFS-RT value is authoritative. The
                        # observed passage calculation fills only its gaps.
                        "delay_seconds": (
                            official_delay
                            if official_delay is not None
                            else observed_delay
                        )
                    }
                )
            )
        return enriched

    async def _load_static(
        self, mode: VehicleMode, suffix: str, prefix: str
    ) -> StaticFeed:
        response = await self.client.get(f"{self.base_url}/GTFS_KRK_{suffix}.zip")
        response.raise_for_status()
        return self._parse_static(response.content, mode, prefix)

    def _parse_static(
        self, archive: bytes, mode: VehicleMode, prefix: str
    ) -> StaticFeed:
        result = StaticFeed(mode=mode, prefix=prefix)
        with ZipFile(BytesIO(archive)) as zip_file:
            for row in self._rows(zip_file, "routes.txt"):
                raw_id = row["route_id"]
                route_id = f"{prefix}:{raw_id}"
                color = (row.get("route_color") or "").strip().lstrip("#")
                if len(color) != 6:
                    color = "00A99A" if mode == VehicleMode.TRAM else "315A70"
                result.route_ids[raw_id] = route_id
                result.routes[route_id] = RouteSummary(
                    route_id=route_id,
                    short_name=row.get("route_short_name") or raw_id,
                    long_name=row.get("route_long_name")
                    or row.get("route_short_name")
                    or raw_id,
                    color=color,
                )

            chosen_shapes: dict[tuple[str, int], str] = {}
            for row in self._rows(zip_file, "trips.txt"):
                raw_route_id = row["route_id"]
                route_id = result.route_ids.get(raw_route_id)
                if route_id is None:
                    continue
                direction_id = int(row.get("direction_id") or 0)
                shape_id = row.get("shape_id") or ""
                result.trips[row["trip_id"]] = TripInfo(
                    route_id=route_id,
                    headsign=row.get("trip_headsign") or "Kraków",
                    direction_id=direction_id,
                    shape_id=shape_id,
                )
                if shape_id:
                    chosen_shapes.setdefault((route_id, direction_id), shape_id)

            for row in self._rows(zip_file, "stops.txt"):
                result.stops[row["stop_id"]] = row.get("stop_name") or "Przystanek"

            for row in self._rows(zip_file, "stop_times.txt"):
                arrival_seconds = self._gtfs_time_to_seconds(
                    row.get("arrival_time") or row.get("departure_time")
                )
                if arrival_seconds is None:
                    continue
                result.stop_times.setdefault(row["trip_id"], {})[
                    int(row["stop_sequence"])
                ] = ScheduledStopTime(arrival_seconds=arrival_seconds)

            shape_keys = {shape_id: key for key, shape_id in chosen_shapes.items()}
            unordered: dict[tuple[str, int], list[tuple[int, list[float]]]] = {}
            for row in self._rows(zip_file, "shapes.txt"):
                key = shape_keys.get(row["shape_id"])
                if key is None:
                    continue
                unordered.setdefault(key, []).append(
                    (
                        int(row["shape_pt_sequence"]),
                        [float(row["shape_pt_lon"]), float(row["shape_pt_lat"])],
                    )
                )
            result.shapes = {
                key: [point for _, point in sorted(points)]
                for key, points in unordered.items()
                if len(points) >= 2
            }
        return result

    @staticmethod
    def _gtfs_time_to_seconds(value: str | None) -> int | None:
        if not value:
            return None
        try:
            hours, minutes, seconds = (int(part) for part in value.split(":"))
        except ValueError:
            return None
        return hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _scheduled_arrival_at(
        arrival_seconds: int, observed_at: datetime
    ) -> datetime:
        """Match a GTFS service-day clock (which may exceed 24:00) to an event."""
        krakow = ZoneInfo("Europe/Warsaw")
        local_observed = observed_at.astimezone(krakow)
        candidates = [
            datetime.combine(
                local_observed.date() + timedelta(days=offset),
                datetime.min.time(),
                tzinfo=krakow,
            )
            + timedelta(seconds=arrival_seconds)
            for offset in (-1, 0)
        ]
        return min(candidates, key=lambda candidate: abs(candidate - local_observed))

    def _observe_stop_passage(
        self, vehicle: VehicleState, static: StaticFeed
    ) -> int | None:
        """Estimate delay after an observed move from one stop sequence to the next.

        VehiclePositions can skip a stop update, so this deliberately records the
        last confirmed sequence and uses it only once the sequence advances.
        """
        sequence = vehicle.current_stop_sequence
        if sequence is None:
            return None
        previous = self.observed_passages.get(vehicle.vehicle_id)
        delay_seconds = previous.delay_seconds if previous else None
        if previous and previous.trip_id == vehicle.trip_id and sequence > previous.stop_sequence:
            passed_stop = static.stop_times.get(vehicle.trip_id.partition(":")[2], {}).get(
                previous.stop_sequence
            )
            if passed_stop:
                scheduled_at = self._scheduled_arrival_at(
                    passed_stop.arrival_seconds, vehicle.position_measured_at
                )
                delay_seconds = int(
                    (vehicle.position_measured_at - scheduled_at.astimezone(UTC)).total_seconds()
                )
        self.observed_passages[vehicle.vehicle_id] = ObservedPassage(
            trip_id=vehicle.trip_id,
            stop_sequence=sequence,
            delay_seconds=delay_seconds,
        )
        return delay_seconds

    @staticmethod
    def _rows(zip_file: ZipFile, name: str):
        with zip_file.open(name) as raw_file:
            yield from csv.DictReader(TextIOWrapper(raw_file, encoding="utf-8-sig"))

    async def _load_positions(
        self, mode: VehicleMode, suffix: str
    ) -> list[VehicleState]:
        static = self.static_feeds.get(mode)
        if static is None:
            raise RuntimeError(f"Static feed unavailable for {mode}")
        response = await self.client.get(
            f"{self.base_url}/VehiclePositions_{suffix}.pb"
        )
        response.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        now = datetime.now(UTC)
        vehicles: list[VehicleState] = []

        for entity in feed.entity:
            if not entity.HasField("vehicle"):
                continue
            item = entity.vehicle
            raw_vehicle_id = item.vehicle.id or item.vehicle.label or entity.id
            raw_trip_id = item.trip.trip_id
            trip = static.trips.get(raw_trip_id)
            raw_route_id = item.trip.route_id
            route_id = static.route_ids.get(raw_route_id) if raw_route_id else None
            route_id = route_id or (trip.route_id if trip else None)
            route = static.routes.get(route_id or "")
            if not raw_vehicle_id or route_id is None or route is None:
                continue

            measured_at = (
                datetime.fromtimestamp(item.timestamp, UTC) if item.timestamp else now
            )
            age = max(0, (now - measured_at).total_seconds())
            freshness = (
                Freshness.LIVE
                if age <= self.live_max_age_seconds
                else Freshness.STALE
                if age <= self.stale_max_age_seconds
                else Freshness.OFFLINE
            )
            direction_id = int(item.trip.direction_id)
            if trip and not item.trip.HasField("direction_id"):
                direction_id = trip.direction_id
            stop_id = item.stop_id or None
            vehicles.append(
                VehicleState(
                    vehicle_id=f"{static.prefix}:{raw_vehicle_id}",
                    trip_id=f"{static.prefix}:{raw_trip_id or entity.id}",
                    route_id=route_id,
                    route_short_name=route.short_name,
                    headsign=trip.headsign if trip else route.long_name,
                    direction_id=direction_id,
                    latitude=item.position.latitude,
                    longitude=item.position.longitude,
                    bearing=(
                        item.position.bearing
                        if item.position.HasField("bearing")
                        else None
                    ),
                    speed_mps=(
                        item.position.speed
                        if item.position.HasField("speed")
                        else None
                    ),
                    current_stop_sequence=item.current_stop_sequence or None,
                    next_stop_id=stop_id,
                    next_stop_name=static.stops.get(stop_id or ""),
                    passenger_count=None,
                    capacity=None,
                    load_factor=None,
                    occupancy_status=OccupancyStatus.UNKNOWN,
                    position_measured_at=measured_at,
                    updated_at=now,
                    freshness=freshness,
                    source="GTFS_RT_ZTP_KRAKOW",
                    vehicle_mode=mode,
                    is_simulation=False,
                )
            )
        return vehicles

    async def _load_trip_delays(self, suffix: str) -> dict[str, TripDelay]:
        """Read trip updates; their delay fields compare live travel to GTFS times."""
        response = await self.client.get(f"{self.base_url}/TripUpdates_{suffix}.pb")
        response.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        delays: dict[str, TripDelay] = {}

        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue
            update = entity.trip_update
            trip_id = update.trip.trip_id
            if not trip_id:
                continue
            delay = TripDelay(
                default_seconds=update.delay if update.HasField("delay") else None
            )
            for stop_update in update.stop_time_update:
                seconds = None
                if stop_update.departure.HasField("delay"):
                    seconds = stop_update.departure.delay
                elif stop_update.arrival.HasField("delay"):
                    seconds = stop_update.arrival.delay
                if seconds is not None and stop_update.stop_sequence:
                    delay.by_stop_sequence[stop_update.stop_sequence] = seconds
                    if delay.default_seconds is None:
                        delay.default_seconds = seconds
            delays[trip_id] = delay
        return delays

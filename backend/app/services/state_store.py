from bisect import insort
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import atan2, cos, degrees, radians, sin

from app.config import Settings
from app.domain.common import utc_now
from app.domain.demo_vehicle import CreateDemoVehicleRequest
from app.domain.dispatch import CreateDispatchRequest, Dispatch, DispatchStatus
from app.domain.recommendation import Recommendation, RecommendationStatus
from app.domain.route import RouteShape, RouteSummary
from app.domain.scenario import Scenario, ScenarioActivationResponse
from app.domain.vehicle import (
    Freshness,
    MobilityAids,
    OccupancyStatus,
    VehicleHistoryPoint,
    VehicleMode,
    VehicleState,
)
from app.services.decision_engine import DecisionEngine
from app.services.devices import DeviceRegistry
from app.services.occupancy_tracker import DoorCounterOccupancy

# What the decision engine is told when it runs on live counter data. Both are
# placeholders: the real headway comes from the GTFS timetable for the route, and
# reserve availability from the depot. They match the values the demo scenarios already
# use, so live and scripted runs behave alike. This is the seam where better dispatch
# heuristics plug in.
LIVE_ASSUMED_HEADWAY_SECONDS = 660
LIVE_ASSUMED_RESERVE_AVAILABLE = True

ROUTE_16_COORDINATES = [
    [19.9350, 50.0670],
    [19.9410, 50.0645],
    [19.9480, 50.0615],
    [19.9560, 50.0575],
    [19.9640, 50.0530],
]

ROUTE_4_COORDINATES = [
    [19.9140, 50.0750],
    [19.9250, 50.0710],
    [19.9380, 50.0670],
    [19.9510, 50.0630],
]

DEMO_MAX_SPEED = 5

# A staged overload for presentations: a live tram held full through the same
# counter path a camera uses. Re-anchored well inside the stale window, and
# released after a while so a forgotten demo does not stay red all day.
DEMO_OVERLOAD_LOAD = 0.92
DEMO_OVERLOAD_CAPACITY = 202
DEMO_OVERLOAD_REFRESH = timedelta(seconds=30)
DEMO_OVERLOAD_DURATION = timedelta(minutes=10)
# What a cabin camera would add on a full tram, so the demo tells the whole story.
DEMO_OVERLOAD_AIDS = MobilityAids(wheelchairs=1, strollers=1)
# The pitch shows the city centre; a full tram at a terminus is easy to miss.
KRAKOW_CENTRE = (50.0614, 19.9372)


@dataclass
class DemoRun:
    vehicle_id: str
    route_id: str
    direction_id: int
    capacity: int
    simulation_speed: int
    created_at: datetime


@dataclass
class DemoOverload:
    vehicle_id: str
    occupancy: int
    capacity: int
    started_at: datetime
    refreshed_at: datetime


def occupancy_status(load_factor: float | None) -> OccupancyStatus:
    if load_factor is None:
        return OccupancyStatus.UNKNOWN
    if load_factor < 0.50:
        return OccupancyStatus.LOW
    if load_factor < 0.70:
        return OccupancyStatus.MODERATE
    if load_factor < 0.85:
        return OccupancyStatus.BUSY
    if load_factor < 1:
        return OccupancyStatus.CROWDED
    return OccupancyStatus.OVER_CAPACITY


class StateStore:
    """In-memory MVP store. Its public methods can later be backed by SQLite."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = DecisionEngine()
        self.vehicles: dict[str, VehicleState] = {}
        self.history: dict[str, list[VehicleHistoryPoint]] = defaultdict(list)
        self.recommendations: dict[str, Recommendation] = {}
        self.dispatches: dict[str, Dispatch] = {}
        self.demo_runs: dict[str, DemoRun] = {}
        self.demo_overloads: dict[str, DemoOverload] = {}
        self.routes: dict[str, RouteSummary] = {}
        self.shapes: dict[tuple[str, int], list[list[float]]] = {}
        self.active_scenario_id: str | None = None
        self.occupancy = DoorCounterOccupancy(
            stale_after_seconds=settings.occupancy_stale_seconds,
            confidence=settings.occupancy_confidence,
        )
        self.devices = DeviceRegistry.from_file(settings.ingest_devices_file)
        self.last_realtime_update = utc_now()
        self.source_health = {
            "gtfsStatic": "ok" if settings.seed_fixtures else "stale",
            "gtfsRealtime": "ok" if settings.seed_fixtures else "stale",
            "occupancy": "ok" if settings.seed_fixtures else "offline",
        }
        if settings.seed_fixtures:
            self._seed_demo_data()

    def _seed_demo_data(self) -> None:
        now = utc_now()
        self.routes = {
            "route-16": RouteSummary(
                route_id="route-16",
                short_name="16",
                long_name="Mistrzejowice – Borek Fałęcki",
                color="D42127",
            ),
            "route-4": RouteSummary(
                route_id="route-4",
                short_name="4",
                long_name="Wzgórza Krzesławickie – Bronowice Małe",
                color="005BBB",
            ),
        }
        self.shapes = {
            ("route-16", 1): ROUTE_16_COORDINATES,
            ("route-4", 0): ROUTE_4_COORDINATES,
        }
        self.vehicles = {
            "2184": VehicleState(
                vehicle_id="2184",
                trip_id="demo-trip-16-1320",
                route_id="route-16",
                route_short_name="16",
                headsign="Borek Fałęcki",
                direction_id=1,
                latitude=50.0635,
                longitude=19.9452,
                bearing=142,
                speed_mps=8.3,
                current_stop_sequence=14,
                next_stop_id="stop-3042",
                next_stop_name="Rondo Mogilskie",
                delay_seconds=165,
                position_measured_at=now,
                updated_at=now,
                freshness=Freshness.LIVE,
                source="GTFS_RT_FIXTURE",
            ),
            "2371": VehicleState(
                vehicle_id="2371",
                trip_id="demo-trip-4-1322",
                route_id="route-4",
                route_short_name="4",
                headsign="Bronowice Małe",
                direction_id=0,
                latitude=50.0692,
                longitude=19.9301,
                bearing=260,
                speed_mps=7.2,
                current_stop_sequence=8,
                next_stop_id="stop-2008",
                next_stop_name="Teatr Bagatela",
                delay_seconds=40,
                passenger_count=78,
                capacity=202,
                load_factor=0.39,
                occupancy_confidence=0.92,
                occupancy_status=OccupancyStatus.LOW,
                position_measured_at=now,
                occupancy_measured_at=now,
                updated_at=now,
                freshness=Freshness.LIVE,
                source="GTFS_RT_FIXTURE",
            ),
        }
        for vehicle in self.vehicles.values():
            self.history[vehicle.vehicle_id].append(self._history_point(vehicle, now))

    @staticmethod
    def _history_point(vehicle: VehicleState, measured_at=None) -> VehicleHistoryPoint:
        return VehicleHistoryPoint(
            measured_at=measured_at or utc_now(),
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=vehicle.load_factor,
            delay_seconds=vehicle.delay_seconds,
        )

    def reset_demo(self) -> None:
        self.vehicles = {
            vehicle_id: vehicle
            for vehicle_id, vehicle in self.vehicles.items()
            if not vehicle.is_simulation
        }
        self.history.clear()
        self.recommendations.clear()
        self.dispatches.clear()
        self.demo_runs.clear()
        self.active_scenario_id = None
        self.last_realtime_update = utc_now()
        self.source_health = {
            "gtfsStatic": "ok",
            "gtfsRealtime": "ok",
            "occupancy": "ok",
        }
        if self.settings.seed_fixtures:
            self.vehicles.clear()
            self._seed_demo_data()

    def apply_realtime_snapshot(self, snapshot) -> list[VehicleState]:
        now = utc_now()
        simulations = {
            vehicle_id: vehicle
            for vehicle_id, vehicle in self.vehicles.items()
            if vehicle.is_simulation
        }
        incoming_ids = {vehicle.vehicle_id for vehicle in snapshot.vehicles}
        # A single GTFS-RT batch is not a complete truth set. Keep an omitted
        # vehicle at its last location until it exceeds the configured stale
        # window, so an intermittent feed cannot make it blink off the map.
        recently_missing_vehicles = {
            vehicle_id: vehicle.model_copy(update={"freshness": Freshness.STALE})
            for vehicle_id, vehicle in self.vehicles.items()
            if not vehicle.is_simulation
            and vehicle_id not in incoming_ids
            and (now - vehicle.position_measured_at).total_seconds()
            <= self.settings.stale_max_age_seconds
        }
        # GTFS-RT carries no occupancy, so every snapshot arrives with it empty.
        # Overlaying the counter's measurement here is what stops each 5-second poll
        # from wiping it.
        incoming = [self._with_occupancy(vehicle) for vehicle in snapshot.vehicles]
        self.vehicles = recently_missing_vehicles
        self.vehicles.update({vehicle.vehicle_id: vehicle for vehicle in incoming})
        self.vehicles.update(simulations)
        self.routes.update(snapshot.routes)
        self.shapes.update(snapshot.shapes)
        self.last_realtime_update = utc_now()
        online_count = len(snapshot.modes_online)
        self.source_health["gtfsStatic"] = "ok" if snapshot.routes else "offline"
        self.source_health["gtfsRealtime"] = (
            "ok" if online_count == 2 else "stale" if online_count == 1 else "offline"
        )
        if self.occupancy.has_fresh_data():
            self.source_health["occupancy"] = "ok"
        for vehicle in incoming:
            points = self.history[vehicle.vehicle_id]
            if not points or points[-1].measured_at < vehicle.position_measured_at:
                points.append(
                    self._history_point(vehicle, vehicle.position_measured_at)
                )
                self.history[vehicle.vehicle_id] = points[-360:]
        return incoming

    def _with_occupancy(self, vehicle: VehicleState) -> VehicleState:
        """The vehicle with the counter's measurement overlaid, when one is fresh."""
        measurement = self.occupancy.current(vehicle.vehicle_id)
        if measurement is None:
            return vehicle
        return vehicle.model_copy(
            update={
                "passenger_count": measurement.passenger_count,
                "capacity": measurement.capacity,
                "load_factor": measurement.load_factor,
                "occupancy_confidence": measurement.confidence,
                "occupancy_status": occupancy_status(measurement.load_factor),
                "occupancy_measured_at": measurement.measured_at,
                "mobility_aids": self.occupancy.mobility_aids(vehicle.vehicle_id),
                "updated_at": utc_now(),
            }
        )

    def apply_counter_update(
        self, vehicle_id: str
    ) -> tuple[VehicleState | None, Recommendation | None]:
        """Folds a new counter measurement into the vehicle and asks the engine.

        Returns `(None, None)` when the vehicle is not on the map yet — the count is
        kept and overlaid as soon as GTFS-RT reports the vehicle.
        """
        vehicle = self.vehicles.get(vehicle_id)
        if vehicle is None:
            return None, None
        vehicle = self._with_occupancy(vehicle)
        self.vehicles[vehicle_id] = vehicle
        self.source_health["occupancy"] = "ok"
        if vehicle.occupancy_measured_at is not None:
            # Kept in time order: a batch buffered through a tunnel can land after a
            # newer GTFS point, and the engine walks history backwards from the newest.
            insort(
                self.history[vehicle_id],
                self._history_point(vehicle, vehicle.occupancy_measured_at),
                key=lambda point: point.measured_at,
            )
            self.history[vehicle_id] = self.history[vehicle_id][-360:]
        return vehicle, self.evaluate_live(vehicle)

    def evaluate_counted_vehicles(self) -> list[Recommendation]:
        """Re-evaluates every vehicle that has a fresh counter reading.

        Called on each GTFS poll. Evaluating only when a counter sends something misses
        the case the engine exists for: a tram packed so full that nobody gets on or off
        sends no events at all, so it would never be looked at again.
        """
        created = []
        for vehicle in list(self.vehicles.values()):
            if vehicle.is_simulation:
                continue
            if self.occupancy.current(vehicle.vehicle_id) is None:
                continue
            recommendation = self.evaluate_live(vehicle)
            if recommendation:
                created.append(recommendation)
        return created

    def evaluate_live(self, vehicle: VehicleState) -> Recommendation | None:
        """Runs the decision engine on live data — until now it only ran for scenarios.

        At most one open recommendation per route and direction: a tram that stays full
        for ten minutes is one problem, not one recommendation per counter batch. A
        reserve already on its way answers the problem too, so the line stays quiet
        until that run ends.
        """
        if self._line_handled(vehicle.route_id, vehicle.direction_id):
            return None
        recommendation = self.engine.evaluate(
            vehicle,
            self.history[vehicle.vehicle_id],
            headway_seconds=LIVE_ASSUMED_HEADWAY_SECONDS,
            reserve_available=LIVE_ASSUMED_RESERVE_AVAILABLE,
        )
        if recommendation:
            self.recommendations[recommendation.id] = recommendation
        return recommendation

    def _line_handled(self, route_id: str, direction_id: int) -> bool:
        open_recommendation = any(
            rec.status == RecommendationStatus.OPEN
            and rec.route_id == route_id
            and rec.direction_id == direction_id
            for rec in self.recommendations.values()
        )
        reserve_running = any(
            dispatch.route_id == route_id
            and dispatch.direction_id == direction_id
            and dispatch.status
            not in {DispatchStatus.CANCELLED, DispatchStatus.COMPLETED}
            for dispatch in self.dispatches.values()
        )
        return open_recommendation or reserve_running

    def mark_realtime_failure(self) -> None:
        self.source_health["gtfsRealtime"] = "offline"

    def list_vehicles(self) -> list[VehicleState]:
        self.refresh_simulations()
        self._expire_stale_occupancy()
        return list(self.vehicles.values())

    def get_vehicle(self, vehicle_id: str) -> VehicleState | None:
        self.refresh_simulations()
        self._expire_stale_occupancy()
        return self.vehicles.get(vehicle_id)

    def _expire_stale_occupancy(self) -> None:
        """Clears a counter reading once it goes stale.

        With GTFS-RT on, every poll replaces the vehicle and a stale count is simply
        not overlaid again. Without a feed — demo mode — nothing replaces it, so a count
        from an hour ago would sit on the map looking current. Only counter readings
        are cleared: a scripted scenario's occupancy is left alone.
        """
        for vehicle_id, vehicle in self.vehicles.items():
            expired = self.occupancy.expired_at(vehicle_id)
            if expired is None or vehicle.occupancy_measured_at != expired:
                continue
            self.vehicles[vehicle_id] = vehicle.model_copy(
                update={
                    "passenger_count": None,
                    "mobility_aids": None,
                    "load_factor": None,
                    "occupancy_confidence": None,
                    "occupancy_status": OccupancyStatus.UNKNOWN,
                }
            )

    def vehicle_history(
        self, vehicle_id: str, minutes: int
    ) -> list[VehicleHistoryPoint]:
        cutoff = utc_now() - timedelta(minutes=minutes)
        return [
            point
            for point in self.history.get(vehicle_id, [])
            if point.measured_at >= cutoff
        ]

    def list_routes(self) -> list[RouteSummary]:
        counts: dict[str, int] = defaultdict(int)
        for vehicle in self.list_vehicles():
            counts[vehicle.route_id] += 1
        return [
            route.model_copy(update={"vehicle_count": counts[route.route_id]})
            for route in self.routes.values()
        ]

    def route_shape(self, route_id: str, direction_id: int) -> RouteShape | None:
        coordinates = self.shapes.get((route_id, direction_id))
        if not coordinates:
            return None
        return RouteShape(
            geometry={"type": "LineString", "coordinates": coordinates},
            properties={"routeId": route_id, "directionId": direction_id},
        )

    def scenarios(self) -> list[Scenario]:
        definitions = [
            (
                "overload-line-16",
                "Przeciążenie linii 16",
                "94% zapełnienia przez trzy minuty.",
            ),
            (
                "sensor-offline",
                "Czujnik offline",
                "Nieaktualny pomiar nie tworzy rekomendacji.",
            ),
            (
                "no-reserve-available",
                "Brak rezerwy",
                "Problem istnieje, lecz interwencja jest niewykonalna.",
            ),
            (
                "successful-intervention",
                "Udana interwencja",
                "Pełny scenariusz rekomendacji i symulacji.",
            ),
        ]
        return [
            Scenario(
                id=item[0],
                name=item[1],
                description=item[2],
                active=item[0] == self.active_scenario_id,
            )
            for item in definitions
        ]

    def activate_scenario(self, scenario_id: str) -> ScenarioActivationResponse | None:
        scenario = next(
            (item for item in self.scenarios() if item.id == scenario_id), None
        )
        if scenario is None:
            return None

        self.reset_demo()
        self.active_scenario_id = scenario_id
        vehicle = self.vehicles["2184"]
        now = utc_now()

        if scenario_id == "sensor-offline":
            self.source_health["occupancy"] = "stale"
            measured_at = now - timedelta(minutes=3)
            self._set_occupancy(vehicle, 0.94, measured_at, Freshness.OFFLINE)
            self.history[vehicle.vehicle_id] = [
                self._history_point(vehicle, measured_at)
            ]
        else:
            loads = [0.82, 0.87, 0.91, 0.94]
            self.history[vehicle.vehicle_id] = []
            for index, load in enumerate(loads):
                measured_at = now - timedelta(seconds=180 - index * 60)
                self._set_occupancy(vehicle, load, measured_at, Freshness.LIVE)
                self.history[vehicle.vehicle_id].append(
                    self._history_point(vehicle, measured_at)
                )
            self._set_occupancy(vehicle, 0.94, now, Freshness.LIVE)

        recommendation = self.engine.evaluate(
            vehicle,
            self.history[vehicle.vehicle_id],
            headway_seconds=660,
            reserve_available=scenario_id != "no-reserve-available",
        )
        if recommendation:
            self.recommendations[recommendation.id] = recommendation

        activated = scenario.model_copy(update={"active": True})
        return ScenarioActivationResponse(
            scenario=activated,
            target_vehicle_id=vehicle.vehicle_id,
            recommendation_id=recommendation.id if recommendation else None,
        )

    @staticmethod
    def _set_occupancy(
        vehicle: VehicleState,
        load_factor: float,
        measured_at,
        freshness: Freshness,
    ) -> None:
        vehicle.load_factor = load_factor
        vehicle.capacity = 202
        vehicle.passenger_count = round(load_factor * vehicle.capacity)
        vehicle.occupancy_confidence = 0.91
        vehicle.occupancy_status = occupancy_status(load_factor)
        vehicle.occupancy_measured_at = measured_at
        vehicle.freshness = freshness
        vehicle.updated_at = utc_now()

    def dismiss_recommendation(
        self, recommendation_id: str, reason: str
    ) -> Recommendation | None:
        recommendation = self.recommendations.get(recommendation_id)
        if recommendation is None:
            return None
        recommendation.status = RecommendationStatus.DISMISSED
        recommendation.dismissed_reason = reason
        return recommendation

    def create_dispatch(self, request: CreateDispatchRequest) -> Dispatch:
        recommendation = self.recommendations.get(request.recommendation_id)
        if recommendation is None:
            raise KeyError("Recommendation not found")
        if recommendation.status != RecommendationStatus.OPEN:
            raise ValueError("Recommendation is no longer open")
        if request.route_id not in self.routes:
            raise KeyError("Route not found")
        if (request.route_id, request.direction_id) not in self.shapes:
            raise KeyError("Route shape not found")

        existing = next(
            (
                dispatch
                for dispatch in self.dispatches.values()
                if dispatch.recommendation_id == request.recommendation_id
                and dispatch.status
                not in {DispatchStatus.CANCELLED, DispatchStatus.COMPLETED}
            ),
            None,
        )
        if existing:
            return existing

        number = len(self.dispatches) + 1
        now = utc_now()
        dispatch = Dispatch(
            dispatch_id=f"dispatch-{number:03d}",
            recommendation_id=request.recommendation_id,
            vehicle_id=f"SIM-TRAM-{number:02d}",
            route_id=request.route_id,
            direction_id=request.direction_id,
            start_stop_id=request.start_stop_id,
            end_stop_id=request.end_stop_id,
            capacity=request.capacity,
            status=DispatchStatus.DISPATCHED,
            simulation_speed=request.simulation_speed,
            created_at=now,
            estimated_start_at=now + timedelta(seconds=request.departure_delay_seconds),
        )
        self.dispatches[dispatch.dispatch_id] = dispatch
        recommendation.status = RecommendationStatus.ACCEPTED
        self._upsert_simulated_vehicle(dispatch, progress=0)
        return dispatch

    def cancel_dispatch(self, dispatch_id: str) -> Dispatch | None:
        dispatch = self.dispatches.get(dispatch_id)
        if dispatch is None:
            return None
        if dispatch.status == DispatchStatus.COMPLETED:
            raise ValueError("Completed dispatch cannot be cancelled")
        dispatch.status = DispatchStatus.CANCELLED
        self.vehicles.pop(dispatch.vehicle_id, None)
        return dispatch

    def refresh_simulations(self) -> None:
        now = utc_now()
        for dispatch in self.dispatches.values():
            if dispatch.status in {DispatchStatus.CANCELLED, DispatchStatus.COMPLETED}:
                continue
            if now < dispatch.estimated_start_at:
                dispatch.status = DispatchStatus.WAITING_FOR_DEPARTURE
                self._upsert_simulated_vehicle(dispatch, progress=0)
                continue

            simulated_seconds = (
                now - dispatch.estimated_start_at
            ).total_seconds() * dispatch.simulation_speed
            progress = min(1.0, simulated_seconds / 900)
            dispatch.status = (
                DispatchStatus.IN_SERVICE if progress < 1 else DispatchStatus.COMPLETED
            )
            self._upsert_simulated_vehicle(dispatch, progress)
        for run in self.demo_runs.values():
            simulated_seconds = (
                (now - run.created_at).total_seconds()
                * min(run.simulation_speed, DEMO_MAX_SPEED)
            )
            progress = (simulated_seconds / 900) % 1
            self._upsert_demo_vehicle(run, progress)

    def create_demo_vehicle(self, request: CreateDemoVehicleRequest) -> VehicleState:
        if request.route_id not in self.routes:
            raise KeyError("Route not found")
        candidates = [
            direction_id
            for route_id, direction_id in self.shapes
            if route_id == request.route_id
        ]
        if not candidates:
            raise KeyError("Route shape not found")
        direction_id = (
            request.direction_id
            if request.direction_id in candidates
            else candidates[0]
        )
        number = len(self.demo_runs) + 1
        vehicle_id = f"SIM-DEMO-{number:02d}"
        while vehicle_id in self.vehicles:
            number += 1
            vehicle_id = f"SIM-DEMO-{number:02d}"
        run = DemoRun(
            vehicle_id=vehicle_id,
            route_id=request.route_id,
            direction_id=direction_id,
            capacity=request.capacity,
            simulation_speed=min(request.simulation_speed, DEMO_MAX_SPEED),
            created_at=utc_now(),
        )
        self.demo_runs[vehicle_id] = run
        return self._upsert_demo_vehicle(run, 0)

    def start_demo_overload(self, vehicle_id: str | None) -> VehicleState:
        """Holds a live tram full, as if its door counter reported it.

        Without an id it picks the live tram closest to the city centre. Raises
        `KeyError` for an unknown or unsuitable vehicle and `LookupError` when no live
        tram is on the map.
        """
        vehicle = (
            self._overload_candidate(vehicle_id)
            if vehicle_id
            else self._central_live_tram()
        )
        capacity = vehicle.capacity or DEMO_OVERLOAD_CAPACITY
        now = utc_now()
        overload = DemoOverload(
            vehicle_id=vehicle.vehicle_id,
            occupancy=round(capacity * DEMO_OVERLOAD_LOAD),
            capacity=capacity,
            started_at=now,
            refreshed_at=now,
        )
        self.demo_overloads[vehicle.vehicle_id] = overload
        updated, _ = self._anchor_overload(overload, now)
        return updated or vehicle

    def stop_demo_overload(self, vehicle_id: str) -> bool:
        return self.demo_overloads.pop(vehicle_id, None) is not None

    def refresh_demo_overloads(
        self,
    ) -> list[tuple[VehicleState, Recommendation | None]]:
        """Re-anchors held trams before their count goes stale; releases old ones."""
        now = utc_now()
        refreshed = []
        for overload in list(self.demo_overloads.values()):
            if now - overload.started_at > DEMO_OVERLOAD_DURATION:
                self.demo_overloads.pop(overload.vehicle_id)
            elif now - overload.refreshed_at >= DEMO_OVERLOAD_REFRESH:
                overload.refreshed_at = now
                vehicle, recommendation = self._anchor_overload(overload, now)
                if vehicle:
                    refreshed.append((vehicle, recommendation))
        return refreshed

    def _anchor_overload(
        self, overload: DemoOverload, now: datetime
    ) -> tuple[VehicleState | None, Recommendation | None]:
        self.occupancy.record_anchor(
            overload.vehicle_id,
            overload.capacity,
            overload.occupancy,
            now,
            DEMO_OVERLOAD_AIDS,
        )
        return self.apply_counter_update(overload.vehicle_id)

    def _overload_candidate(self, vehicle_id: str) -> VehicleState:
        vehicle = self.vehicles.get(vehicle_id)
        if vehicle is None or vehicle.is_simulation:
            raise KeyError("Vehicle not found")
        if vehicle.vehicle_mode != VehicleMode.TRAM:
            raise KeyError("Only trams can be overloaded")
        return vehicle

    def _central_live_tram(self) -> VehicleState:
        trams = [
            vehicle
            for vehicle in self.vehicles.values()
            if not vehicle.is_simulation
            and vehicle.vehicle_mode == VehicleMode.TRAM
            and vehicle.vehicle_id not in self.demo_overloads
        ]
        if not trams:
            raise LookupError("No live tram on the map")
        latitude, longitude = KRAKOW_CENTRE
        return min(
            trams,
            key=lambda tram: (
                (tram.latitude - latitude) ** 2 + (tram.longitude - longitude) ** 2
            ),
        )

    def delete_demo_vehicle(self, vehicle_id: str) -> bool:
        if vehicle_id not in self.demo_runs:
            return False
        self.demo_runs.pop(vehicle_id, None)
        self.vehicles.pop(vehicle_id, None)
        self.history.pop(vehicle_id, None)
        return True

    def _upsert_demo_vehicle(self, run: DemoRun, progress: float) -> VehicleState:
        coordinates = self.shapes[(run.route_id, run.direction_id)]
        longitude, latitude, bearing = self._position_on_shape(coordinates, progress)
        now = utc_now()
        route = self.routes[run.route_id]
        vehicle = VehicleState(
            vehicle_id=run.vehicle_id,
            trip_id=f"demo-trip-{run.vehicle_id}",
            route_id=run.route_id,
            route_short_name=route.short_name,
            headsign="WIRTUALNY POJAZD DEMO",
            direction_id=run.direction_id,
            latitude=latitude,
            longitude=longitude,
            bearing=bearing,
            speed_mps=5,
            passenger_count=0,
            capacity=run.capacity,
            load_factor=0,
            occupancy_confidence=1,
            occupancy_status=OccupancyStatus.LOW,
            position_measured_at=now,
            occupancy_measured_at=now,
            updated_at=now,
            freshness=Freshness.SIMULATION,
            source="SIMULATOR",
            vehicle_mode=VehicleMode.TRAM,
            is_simulation=True,
        )
        self.vehicles[vehicle.vehicle_id] = vehicle
        points = self.history[vehicle.vehicle_id]
        if not points or (now - points[-1].measured_at).total_seconds() >= 1:
            points.append(self._history_point(vehicle, now))
        return vehicle

    def _upsert_simulated_vehicle(self, dispatch: Dispatch, progress: float) -> None:
        coordinates = self.shapes[(dispatch.route_id, dispatch.direction_id)]
        longitude, latitude, bearing = self._position_on_shape(coordinates, progress)
        now = utc_now()
        route = self.routes[dispatch.route_id]
        vehicle = VehicleState(
            vehicle_id=dispatch.vehicle_id,
            trip_id=f"sim-trip-{dispatch.dispatch_id}",
            route_id=dispatch.route_id,
            route_short_name=route.short_name,
            headsign="SYMULACJA — dodatkowy tramwaj",
            direction_id=dispatch.direction_id,
            latitude=latitude,
            longitude=longitude,
            bearing=bearing,
            speed_mps=8,
            passenger_count=0,
            capacity=dispatch.capacity,
            load_factor=0,
            occupancy_confidence=1,
            occupancy_status=OccupancyStatus.LOW,
            position_measured_at=now,
            occupancy_measured_at=now,
            updated_at=now,
            freshness=Freshness.SIMULATION,
            source="SIMULATOR",
            is_simulation=True,
        )
        self.vehicles[vehicle.vehicle_id] = vehicle
        points = self.history[vehicle.vehicle_id]
        if not points or (now - points[-1].measured_at).total_seconds() >= 1:
            points.append(self._history_point(vehicle, now))

    @staticmethod
    def _position_on_shape(
        coordinates: list[list[float]], progress: float
    ) -> tuple[float, float, float]:
        scaled = progress * (len(coordinates) - 1)
        start_index = min(int(scaled), len(coordinates) - 2)
        local_progress = scaled - start_index
        start = coordinates[start_index]
        end = coordinates[start_index + 1]
        longitude = start[0] + (end[0] - start[0]) * local_progress
        latitude = start[1] + (end[1] - start[1]) * local_progress
        y = sin(radians(end[0] - start[0])) * cos(radians(end[1]))
        x = cos(radians(start[1])) * sin(radians(end[1])) - sin(
            radians(start[1])
        ) * cos(radians(end[1])) * cos(radians(end[0] - start[0]))
        bearing = (degrees(atan2(y, x)) + 360) % 360
        return longitude, latitude, bearing

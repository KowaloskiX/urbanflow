from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.domain.common import ApiModel, SourceStatus


class OccupancyStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    BUSY = "BUSY"
    CROWDED = "CROWDED"
    OVER_CAPACITY = "OVER_CAPACITY"


class Freshness(StrEnum):
    LIVE = "LIVE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"
    SIMULATION = "SIMULATION"


class VehicleMode(StrEnum):
    TRAM = "TRAM"
    BUS = "BUS"


class MobilityAids(ApiModel):
    """What a cabin camera sees besides people: items that take the floor of several."""

    wheelchairs: int = 0
    strollers: int = 0
    bicycles: int = 0


class VehicleState(ApiModel):
    vehicle_id: str
    trip_id: str
    route_id: str
    route_short_name: str
    headsign: str
    direction_id: int
    latitude: float
    longitude: float
    bearing: float | None = None
    speed_mps: float | None = None
    current_stop_sequence: int | None = None
    next_stop_id: str | None = None
    next_stop_name: str | None = None
    delay_seconds: int | None = None
    passenger_count: int | None = None
    capacity: int | None = None
    load_factor: float | None = Field(default=None, ge=0)
    occupancy_confidence: float | None = Field(default=None, ge=0, le=1)
    occupancy_status: OccupancyStatus = OccupancyStatus.UNKNOWN
    position_measured_at: datetime
    occupancy_measured_at: datetime | None = None
    mobility_aids: MobilityAids | None = None
    updated_at: datetime
    freshness: Freshness
    source: str
    vehicle_mode: VehicleMode = VehicleMode.TRAM
    is_simulation: bool = False


class VehicleHistoryPoint(ApiModel):
    measured_at: datetime
    latitude: float
    longitude: float
    load_factor: float | None = None
    delay_seconds: int | None = None


class VehicleListResponse(ApiModel):
    generated_at: datetime
    vehicles: list[VehicleState]
    source_health: dict[str, SourceStatus]


class VehicleDetails(ApiModel):
    vehicle: VehicleState
    history: list[VehicleHistoryPoint]
    route: dict

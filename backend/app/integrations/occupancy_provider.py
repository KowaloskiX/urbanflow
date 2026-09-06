from datetime import datetime
from typing import Protocol

from pydantic import Field

from app.domain.common import ApiModel


class OccupancyMeasurement(ApiModel):
    vehicle_id: str
    trip_id: str | None = None
    passenger_count: int = Field(ge=0)
    capacity: int = Field(gt=0)
    load_factor: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    measured_at: datetime
    source: str


class OccupancyProvider(Protocol):
    async def get_measurements(
        self,
        vehicle_ids: list[str],
    ) -> list[OccupancyMeasurement]:
        """Return the newest measurements for requested GTFS vehicle IDs."""

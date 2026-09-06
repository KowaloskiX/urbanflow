from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.domain.common import ApiModel


class DispatchStatus(StrEnum):
    DISPATCHED = "DISPATCHED"
    WAITING_FOR_DEPARTURE = "WAITING_FOR_DEPARTURE"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CreateDispatchRequest(ApiModel):
    recommendation_id: str
    route_id: str
    direction_id: int
    start_stop_id: str
    end_stop_id: str
    capacity: int = Field(gt=0)
    departure_delay_seconds: int = Field(ge=0)
    simulation_speed: int = Field(default=20, gt=0, le=100)


class Dispatch(ApiModel):
    dispatch_id: str
    recommendation_id: str
    vehicle_id: str
    route_id: str
    direction_id: int
    start_stop_id: str
    end_stop_id: str
    capacity: int
    status: DispatchStatus
    is_simulation: bool = True
    simulation_speed: int
    created_at: datetime
    estimated_start_at: datetime


class ResetResponse(ApiModel):
    status: str = "reset"

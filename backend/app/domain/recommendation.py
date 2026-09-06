from datetime import datetime
from enum import StrEnum

from app.domain.common import ApiModel


class RecommendationStatus(StrEnum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"


class Segment(ApiModel):
    from_stop_id: str
    to_stop_id: str


class RecommendationReason(ApiModel):
    load_factor: float
    duration_seconds: int
    next_vehicle_headway_seconds: int
    measurement_confidence: float


class ProposedAction(ApiModel):
    departure_delay_seconds: int
    capacity: int
    start_stop_id: str
    end_stop_id: str


class ExpectedImpact(ApiModel):
    estimated_waiting_passengers_served: int
    passenger_minutes_saved: int
    projected_peak_load_factor: float


class Recommendation(ApiModel):
    id: str
    type: str = "ADD_EXTRA_TRAM"
    status: RecommendationStatus
    severity: str = "HIGH"
    route_id: str
    route_short_name: str
    direction_id: int
    segment: Segment
    reason: RecommendationReason
    proposed_action: ProposedAction
    expected_impact: ExpectedImpact
    created_at: datetime
    dismissed_reason: str | None = None


class DismissRecommendationRequest(ApiModel):
    reason: str

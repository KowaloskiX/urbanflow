from app.domain.common import utc_now
from app.domain.recommendation import (
    ExpectedImpact,
    ProposedAction,
    Recommendation,
    RecommendationReason,
    RecommendationStatus,
    Segment,
)
from app.domain.vehicle import Freshness, VehicleHistoryPoint, VehicleState


class DecisionEngine:
    """Small, explicit rule engine matching the MVP description."""

    overload_threshold = 0.85
    required_duration_seconds = 120
    minimum_confidence = 0.75
    minimum_headway_seconds = 420

    def evaluate(
        self,
        vehicle: VehicleState,
        history: list[VehicleHistoryPoint],
        *,
        headway_seconds: int,
        reserve_available: bool,
    ) -> Recommendation | None:
        if vehicle.freshness != Freshness.LIVE:
            return None
        if (vehicle.occupancy_confidence or 0) < self.minimum_confidence:
            return None
        if headway_seconds < self.minimum_headway_seconds or not reserve_available:
            return None

        overloaded: list[VehicleHistoryPoint] = []
        for point in reversed(history):
            if point.load_factor is None or point.load_factor < self.overload_threshold:
                break
            overloaded.append(point)
        overloaded.reverse()
        if len(overloaded) < 2:
            return None

        duration = int(
            (overloaded[-1].measured_at - overloaded[0].measured_at).total_seconds()
        )
        if duration < self.required_duration_seconds:
            return None

        now = utc_now()
        recommendation_id = (
            f"rec-{vehicle.route_short_name}-{vehicle.direction_id}-"
            f"{int(now.timestamp())}"
        )
        return Recommendation(
            id=recommendation_id,
            status=RecommendationStatus.OPEN,
            route_id=vehicle.route_id,
            route_short_name=vehicle.route_short_name,
            direction_id=vehicle.direction_id,
            segment=Segment(from_stop_id="stop-3012", to_stop_id="stop-3078"),
            reason=RecommendationReason(
                load_factor=vehicle.load_factor or 0,
                duration_seconds=duration,
                next_vehicle_headway_seconds=headway_seconds,
                measurement_confidence=vehicle.occupancy_confidence or 0,
            ),
            proposed_action=ProposedAction(
                departure_delay_seconds=120,
                capacity=202,
                start_stop_id="stop-3012",
                end_stop_id="stop-3078",
            ),
            expected_impact=ExpectedImpact(
                estimated_waiting_passengers_served=87,
                passenger_minutes_saved=624,
                projected_peak_load_factor=0.78,
            ),
            created_at=now,
        )

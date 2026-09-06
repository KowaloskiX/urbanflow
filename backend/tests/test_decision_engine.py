from datetime import timedelta

from app.config import Settings
from app.domain.common import utc_now
from app.domain.vehicle import Freshness, VehicleHistoryPoint
from app.services.state_store import StateStore


def test_single_high_measurement_does_not_create_recommendation() -> None:
    store = StateStore(Settings())
    vehicle = store.vehicles["2184"]
    now = utc_now()
    vehicle.load_factor = 0.94
    vehicle.occupancy_confidence = 0.91
    vehicle.freshness = Freshness.LIVE
    history = [
        VehicleHistoryPoint(
            measured_at=now,
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=0.94,
        )
    ]

    recommendation = store.engine.evaluate(
        vehicle,
        history,
        headway_seconds=660,
        reserve_available=True,
    )

    assert recommendation is None


def test_persistent_overload_creates_recommendation() -> None:
    store = StateStore(Settings())
    vehicle = store.vehicles["2184"]
    now = utc_now()
    vehicle.load_factor = 0.94
    vehicle.occupancy_confidence = 0.91
    vehicle.freshness = Freshness.LIVE
    history = [
        VehicleHistoryPoint(
            measured_at=now - timedelta(seconds=120),
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=0.86,
        ),
        VehicleHistoryPoint(
            measured_at=now,
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=0.94,
        ),
    ]

    recommendation = store.engine.evaluate(
        vehicle,
        history,
        headway_seconds=660,
        reserve_available=True,
    )

    assert recommendation is not None
    assert recommendation.type == "ADD_EXTRA_TRAM"


def test_low_measurement_breaks_overload_period() -> None:
    store = StateStore(Settings())
    vehicle = store.vehicles["2184"]
    now = utc_now()
    vehicle.load_factor = 0.94
    vehicle.occupancy_confidence = 0.91
    vehicle.freshness = Freshness.LIVE
    history = [
        VehicleHistoryPoint(
            measured_at=now - timedelta(seconds=180),
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=0.90,
        ),
        VehicleHistoryPoint(
            measured_at=now - timedelta(seconds=60),
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=0.70,
        ),
        VehicleHistoryPoint(
            measured_at=now,
            latitude=vehicle.latitude,
            longitude=vehicle.longitude,
            load_factor=0.94,
        ),
    ]

    recommendation = store.engine.evaluate(
        vehicle,
        history,
        headway_seconds=660,
        reserve_available=True,
    )

    assert recommendation is None

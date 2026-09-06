from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.vehicle import Freshness, VehicleMode
from app.main import app
from app.services.state_store import StateStore


def test_vehicle_filters() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/vehicles", params={"routeId": "route-16"})

    assert response.status_code == 200
    vehicles = response.json()["vehicles"]
    assert len(vehicles) == 1
    assert vehicles[0]["routeShortName"] == "16"


def test_route_shape_is_geojson() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/routes/route-16/shape",
            params={"directionId": 1},
        )

    assert response.status_code == 200
    assert response.json()["geometry"]["type"] == "LineString"


def test_invalid_bbox_returns_clear_error() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/vehicles", params={"bbox": "19,50,20"})

    assert response.status_code == 400


def test_missing_vehicle_in_one_snapshot_remains_as_stale_position() -> None:
    store = StateStore(Settings(seed_fixtures=True))
    vehicle_in_batch = store.vehicles["2184"]

    store.apply_realtime_snapshot(
        SimpleNamespace(
            vehicles=[vehicle_in_batch],
            routes={},
            shapes={},
            modes_online={VehicleMode.TRAM},
        )
    )

    assert store.vehicles["2371"].freshness == Freshness.STALE
    assert store.vehicles["2371"].position_measured_at == vehicle_in_batch.position_measured_at

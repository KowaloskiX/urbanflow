"""A staged overload: one click makes a live tram full for a presentation.

It goes through the same counter path a camera uses, so everything downstream — the
map colour, the history, the decision engine — behaves as it would for real data.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.vehicle import OccupancyStatus
from app.main import app
from app.services.state_store import DEMO_OVERLOAD_DURATION, DEMO_OVERLOAD_REFRESH


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_without_an_id_a_live_tram_turns_crowded(client: TestClient) -> None:
    response = client.post("/api/v1/demo/overload", json={})

    assert response.status_code == 201
    vehicle = response.json()
    assert vehicle["occupancyStatus"] == OccupancyStatus.CROWDED
    assert vehicle["isSimulation"] is False
    assert vehicle["mobilityAids"]["wheelchairs"] == 1
    assert client.get("/api/v1/demo/overload").json() == [vehicle["vehicleId"]]


def test_a_chosen_tram_is_the_one_overloaded(client: TestClient) -> None:
    response = client.post("/api/v1/demo/overload", json={"vehicleId": "2371"})

    assert response.json()["vehicleId"] == "2371"
    listed = client.get("/api/v1/vehicles/2371").json()["vehicle"]
    assert listed["occupancyStatus"] == OccupancyStatus.CROWDED


def test_an_unknown_vehicle_is_404(client: TestClient) -> None:
    response = client.post("/api/v1/demo/overload", json={"vehicleId": "nope"})
    assert response.status_code == 404


def test_the_tram_stays_full_past_the_stale_window(client: TestClient) -> None:
    """Without re-anchoring the count would go stale after three minutes and the tram
    would quietly fall back to UNKNOWN in the middle of the pitch."""
    store = client.app.state.store
    client.post("/api/v1/demo/overload", json={"vehicleId": "2184"})
    overload = store.demo_overloads["2184"]
    overload.refreshed_at -= DEMO_OVERLOAD_REFRESH

    refreshed = store.refresh_demo_overloads()

    assert [vehicle.vehicle_id for vehicle, _ in refreshed] == ["2184"]
    assert store.occupancy.current("2184") is not None


def test_a_forgotten_overload_is_released(client: TestClient) -> None:
    store = client.app.state.store
    client.post("/api/v1/demo/overload", json={"vehicleId": "2184"})
    store.demo_overloads["2184"].started_at -= DEMO_OVERLOAD_DURATION + timedelta(
        seconds=1
    )

    store.refresh_demo_overloads()

    assert "2184" not in store.demo_overloads


def test_stopping_releases_the_tram(client: TestClient) -> None:
    client.post("/api/v1/demo/overload", json={"vehicleId": "2184"})

    assert client.delete("/api/v1/demo/overload/2184").status_code == 204
    assert client.delete("/api/v1/demo/overload/2184").status_code == 404

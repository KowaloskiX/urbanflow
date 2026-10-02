"""Door counters writing occupancy into UrbanFlow.

The point is the joins, not the arithmetic: a counter's number has to survive the
GTFS-Realtime poll, reach the dashboard, and reach the decision engine.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.domain.common import utc_now
from app.domain.vehicle import Freshness, OccupancyStatus
from app.main import app
from app.services.devices import Device, generate_key

VEHICLE = "2184"  # the demo fixture on line 16
CAPACITY = 202


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def key(client: TestClient) -> str:
    issued = generate_key()
    client.app.state.store.devices.register(
        issued, Device(vehicle_id=VEHICLE, capacity=CAPACITY)
    )
    return issued


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def passage(event_id: str, direction: str, passengers: int, seconds_ago: int = 0):
    return {
        "eventId": event_id,
        "door": "front",
        "direction": direction,
        "passengers": passengers,
        "observedAt": (utc_now() - timedelta(seconds=seconds_ago)).isoformat(),
    }


def boardings(prefix: str, total: int, seconds_ago: int = 0) -> list[dict]:
    """`total` people as realistic events: at most 50 through one doorway at once, which
    is the API's own limit — anything above that is a broken counter."""
    events, index = [], 0
    while total > 0:
        chunk = min(total, 50)
        events.append(passage(f"{prefix}-{index}", "boarding", chunk, seconds_ago))
        total -= chunk
        index += 1
    return events


def vehicle(client: TestClient) -> dict:
    return client.get(f"/api/v1/vehicles/{VEHICLE}").json()["vehicle"]


def test_boardings_reach_the_dashboard(client: TestClient, key: str) -> None:
    response = client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "boarding", 40), passage("e2", "boarding", 20)]},
        headers=auth(key),
    )

    assert response.status_code == 200, response.text
    assert response.json()["occupancy"] == 60
    shown = vehicle(client)
    assert shown["passengerCount"] == 60
    assert shown["loadFactor"] == pytest.approx(60 / CAPACITY)
    assert shown["occupancyStatus"] == OccupancyStatus.LOW


def test_a_replayed_batch_does_not_move_the_count(client: TestClient, key: str) -> None:
    """A counter that never saw the response resends. Counting it again would leave the
    tram permanently fuller than it is."""
    batch = {"events": [passage("e1", "boarding", 30)]}
    client.post("/api/v1/ingest/passages", json=batch, headers=auth(key))
    second = client.post("/api/v1/ingest/passages", json=batch, headers=auth(key))

    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1
    assert second.json()["occupancy"] == 30


def test_alightings_cannot_drive_the_count_negative(
    client: TestClient, key: str
) -> None:
    response = client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "alighting", 15)]},
        headers=auth(key),
    )

    assert response.json()["occupancy"] == 0


def test_the_count_survives_a_gtfs_poll(client: TestClient, key: str) -> None:
    """The bug this integration exists to avoid. GTFS-RT carries no occupancy, and the
    store replaces every vehicle on each poll — so without the overlay the counter's
    number vanished five seconds after it arrived."""
    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "boarding", 50)]},
        headers=auth(key),
    )
    store = client.app.state.store
    fresh_from_feed = store.vehicles[VEHICLE].model_copy(
        update={
            "passenger_count": None,
            "load_factor": None,
            "occupancy_status": OccupancyStatus.UNKNOWN,
            "position_measured_at": utc_now(),
        }
    )

    merged = store.apply_realtime_snapshot(
        SimpleNamespace(
            vehicles=[fresh_from_feed], routes={}, shapes={}, modes_online={"TRAM"}
        )
    )

    assert merged[0].passenger_count == 50, "the poll wiped the counter's reading"
    assert vehicle(client)["passengerCount"] == 50


def test_sustained_overload_from_counters_creates_a_recommendation(
    client: TestClient, key: str
) -> None:
    """Until now the engine only ran for scripted scenarios. A real counter reporting a
    full tram for over two minutes now produces the same recommendation."""
    client.app.state.store.history[VEHICLE] = []
    client.post(
        "/api/v1/ingest/passages",
        json={"events": boardings("early", 185, seconds_ago=150)},
        headers=auth(key),
    )
    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e2", "boarding", 5)]},
        headers=auth(key),
    )

    recommendations = client.get("/api/v1/recommendations").json()
    assert len(recommendations) == 1
    assert recommendations[0]["routeShortName"] == "16"


def test_one_overloaded_line_is_one_recommendation(
    client: TestClient, key: str
) -> None:
    """A tram that stays full is one problem, not one recommendation per batch."""
    client.app.state.store.history[VEHICLE] = []
    for index, seconds_ago in enumerate((300, 150, 60, 0)):
        client.post(
            "/api/v1/ingest/passages",
            json={
                "events": boardings(
                    f"b{index}", 190 if index == 0 else 1, seconds_ago=seconds_ago
                )
            },
            headers=auth(key),
        )

    assert len(client.get("/api/v1/recommendations").json()) == 1


def test_a_reserve_on_its_way_silences_the_line(client: TestClient, key: str) -> None:
    """Accepting a recommendation answers the problem. While the extra tram runs, the
    still-full tram must not raise the same alarm again."""
    client.app.state.store.history[VEHICLE] = []
    client.post(
        "/api/v1/ingest/passages",
        json={"events": boardings("early", 185, seconds_ago=150)},
        headers=auth(key),
    )
    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e2", "boarding", 5)]},
        headers=auth(key),
    )
    recommendation = client.get("/api/v1/recommendations").json()[0]
    action = recommendation["proposedAction"]
    dispatched = client.post(
        "/api/v1/mock-dispatch/extra-trams",
        json={
            "recommendationId": recommendation["id"],
            "routeId": recommendation["routeId"],
            "directionId": recommendation["directionId"],
            "startStopId": action["startStopId"],
            "endStopId": action["endStopId"],
            "capacity": action["capacity"],
            "departureDelaySeconds": 0,
        },
    )
    assert dispatched.status_code == 201

    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e3", "boarding", 1)]},
        headers=auth(key),
    )

    statuses = [rec["status"] for rec in client.get("/api/v1/recommendations").json()]
    assert statuses == ["ACCEPTED"]


def test_a_stale_count_is_not_shown_as_current(client: TestClient, key: str) -> None:
    """A frozen reading presented as live is how somebody dispatches a tram against an
    old number. Past the stale window the vehicle goes back to UNKNOWN."""
    client.post(
        "/api/v1/ingest/anchor",
        json={
            "occupancy": 190,
            "observedAt": (utc_now() - timedelta(minutes=10)).isoformat(),
        },
        headers=auth(key),
    )

    shown = vehicle(client)
    assert shown["passengerCount"] is None
    assert shown["occupancyStatus"] == OccupancyStatus.UNKNOWN


def test_an_anchor_replaces_accumulated_drift(client: TestClient, key: str) -> None:
    client.post(
        "/api/v1/ingest/passages",
        json={"events": boardings("e", 120)},
        headers=auth(key),
    )

    response = client.post(
        "/api/v1/ingest/anchor",
        json={"occupancy": 0, "observedAt": utc_now().isoformat()},
        headers=auth(key),
    )

    assert response.json()["occupancy"] == 0


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer tbn_made_up"}])
def test_writes_need_a_registered_key(client: TestClient, headers: dict) -> None:
    response = client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "boarding", 1)]},
        headers=headers,
    )

    assert response.status_code == 401


def test_duplicate_ids_inside_one_batch_are_rejected(
    client: TestClient, key: str
) -> None:
    response = client.post(
        "/api/v1/ingest/passages",
        json={
            "events": [passage("same", "boarding", 1), passage("same", "boarding", 1)]
        },
        headers=auth(key),
    )

    assert response.status_code == 422


def test_a_broken_counter_clock_is_rejected(client: TestClient, key: str) -> None:
    response = client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "boarding", 1, seconds_ago=-3600)]},
        headers=auth(key),
    )

    assert response.status_code == 422


def test_a_count_for_a_vehicle_not_yet_on_the_map_is_kept(client: TestClient) -> None:
    """A counter can start before GTFS-RT has reported its tram. The count must wait for
    the vehicle rather than be dropped."""
    store = client.app.state.store
    early = generate_key()
    store.devices.register(early, Device(vehicle_id="ztp-tram:9999", capacity=CAPACITY))

    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "boarding", 33)]},
        headers=auth(early),
    )
    arriving = store.vehicles[VEHICLE].model_copy(
        update={
            "vehicle_id": "ztp-tram:9999",
            "position_measured_at": utc_now(),
            "freshness": Freshness.LIVE,
        }
    )
    merged = store.apply_realtime_snapshot(
        SimpleNamespace(
            vehicles=[arriving], routes={}, shapes={}, modes_online={"TRAM"}
        )
    )

    assert merged[0].passenger_count == 33


def test_a_count_that_goes_stale_later_is_cleared(client: TestClient, key: str) -> None:
    """Demo mode has no GTFS poll to replace the vehicle, so a reading that was fresh
    when it arrived must still be withdrawn once it ages out."""
    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("e1", "boarding", 40)]},
        headers=auth(key),
    )
    assert vehicle(client)["passengerCount"] == 40

    client.app.state.store.occupancy.stale_after = timedelta(seconds=-1)

    shown = vehicle(client)
    assert shown["passengerCount"] is None
    assert shown["occupancyStatus"] == OccupancyStatus.UNKNOWN


def test_a_device_added_to_the_file_works_without_a_restart(tmp_path) -> None:
    """A restart wipes every in-memory count, so provisioning must not need one."""
    from app.services.devices import DeviceRegistry

    file = tmp_path / "devices.json"
    registry = DeviceRegistry.from_file(file)
    issued = generate_key()
    assert registry.resolve(issued) is None

    DeviceRegistry.append_to_file(file, issued, Device(vehicle_id=VEHICLE, capacity=10))

    assert registry.resolve(issued) == Device(vehicle_id=VEHICLE, capacity=10)


def test_a_tram_that_stays_full_is_flagged_without_new_counter_events(
    client: TestClient, key: str
) -> None:
    """A tram packed so full that nobody moves sends no events. The engine still has to
    notice it — on the GTFS poll, not only when the counter speaks."""
    from app.domain.vehicle import VehicleHistoryPoint

    client.post(
        "/api/v1/ingest/passages",
        json={"events": boardings("full", 180)},
        headers=auth(key),
    )
    store = client.app.state.store
    store.recommendations.clear()
    tram = store.vehicles[VEHICLE]
    store.history[VEHICLE] = [
        VehicleHistoryPoint(
            measured_at=utc_now() - timedelta(seconds=seconds_ago),
            latitude=tram.latitude,
            longitude=tram.longitude,
            load_factor=0.9,
        )
        for seconds_ago in (150, 90, 30)
    ]

    created = store.evaluate_counted_vehicles()

    assert len(created) == 1
    assert created[0].route_short_name == "16"


def test_a_cabin_camera_reports_what_takes_extra_space(
    client: TestClient, key: str
) -> None:
    """A cabin camera sends an absolute count plus wheelchairs, strollers and bicycles;
    the map shows them, so a dispatcher (or a wheelchair user) can see them."""
    response = client.post(
        "/api/v1/ingest/anchor",
        json={
            "occupancy": 42,
            "observedAt": utc_now().isoformat(),
            "mobilityAids": {"wheelchairs": 1, "strollers": 2},
        },
        headers=auth(key),
    )

    assert response.status_code == 200
    vehicle = client.get(f"/api/v1/vehicles/{VEHICLE}").json()["vehicle"]
    assert vehicle["passengerCount"] == 42
    assert vehicle["mobilityAids"] == {"wheelchairs": 1, "strollers": 2, "bicycles": 0}


def test_door_passages_do_not_invent_mobility_aids(
    client: TestClient, key: str
) -> None:
    client.post(
        "/api/v1/ingest/passages",
        json={"events": [passage("d1", "boarding", 3)]},
        headers=auth(key),
    )

    vehicle = client.get(f"/api/v1/vehicles/{VEHICLE}").json()["vehicle"]
    assert vehicle["mobilityAids"] is None


def test_an_implausible_mobility_aid_count_is_rejected(
    client: TestClient, key: str
) -> None:
    response = client.post(
        "/api/v1/ingest/anchor",
        json={
            "occupancy": 10,
            "observedAt": utc_now().isoformat(),
            "mobilityAids": {"wheelchairs": 500},
        },
        headers=auth(key),
    )

    assert response.status_code == 422

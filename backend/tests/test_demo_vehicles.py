from fastapi.testclient import TestClient

from app.main import app


def test_manual_demo_vehicle_is_separate_from_real_vehicles() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/demo/vehicles",
            json={"routeId": "route-16", "simulationSpeed": 20},
        )
        assert created.status_code == 201
        demo = created.json()
        assert demo["isSimulation"] is True
        assert demo["freshness"] == "SIMULATION"
        assert demo["source"] == "SIMULATOR"

        real = client.get(
            "/api/v1/vehicles", params={"includeSimulation": "false"}
        ).json()["vehicles"]
        assert all(not vehicle["isSimulation"] for vehicle in real)
        assert demo["vehicleId"] not in {vehicle["vehicleId"] for vehicle in real}

        deleted = client.delete(f"/api/v1/demo/vehicles/{demo['vehicleId']}")
        assert deleted.status_code == 204

from fastapi.testclient import TestClient

from app.main import app


def test_successful_intervention_flow() -> None:
    with TestClient(app) as client:
        activation = client.post(
            "/api/v1/demo/scenarios/successful-intervention/activate"
        )
        assert activation.status_code == 200
        recommendation_id = activation.json()["recommendationId"]
        assert recommendation_id is not None

        recommendations = client.get(
            "/api/v1/recommendations", params={"status": "OPEN"}
        ).json()
        assert len(recommendations) == 1
        assert recommendations[0]["reason"]["loadFactor"] == 0.94

        dispatch = client.post(
            "/api/v1/mock-dispatch/extra-trams",
            json={
                "recommendationId": recommendation_id,
                "routeId": "route-16",
                "directionId": 1,
                "startStopId": "stop-3012",
                "endStopId": "stop-3078",
                "capacity": 202,
                "departureDelaySeconds": 0,
                "simulationSpeed": 20,
            },
        )
        assert dispatch.status_code == 201
        assert dispatch.json()["vehicleId"] == "SIM-TRAM-01"
        assert dispatch.json()["isSimulation"] is True
        assert dispatch.json()["status"] == "DISPATCHED"

        vehicles = client.get("/api/v1/vehicles").json()["vehicles"]
        simulation = next(
            item for item in vehicles if item["vehicleId"] == "SIM-TRAM-01"
        )
        assert simulation["source"] == "SIMULATOR"
        assert simulation["freshness"] == "SIMULATION"


def test_scenarios_block_invalid_recommendations() -> None:
    with TestClient(app) as client:
        for scenario_id in ("sensor-offline", "no-reserve-available"):
            response = client.post(f"/api/v1/demo/scenarios/{scenario_id}/activate")
            assert response.status_code == 200
            assert response.json()["recommendationId"] is None

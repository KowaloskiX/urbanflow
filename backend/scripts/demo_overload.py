"""Plays the whole dispatch path on a live tram: full tram, recommendation, extra tram.

    uv run python -m scripts.demo_overload --vehicle-id ztp-tram:326 --key tbn_...

It speaks the counter's ingest API with a real device key, so everything downstream —
the overlay, the decision engine, the recommendation, the simulated extra tram — runs
exactly as it would for a camera. Only the passenger count is invented.

It does not cheat on time. The engine wants the tram above 85% for two real minutes,
and backdated data is contradicted by the GTFS history recorded in the meantime, so
this keeps the tram full and waits. Expect about two and a half minutes.

For a live presentation pass --no-dispatch: the script stops at the recommendation and
keeps the tram full, and the presenter sends the reserve from the card on the map.
"""

import argparse
import time
from datetime import UTC, datetime

import httpx

FULL_LOAD = 0.92
# Below the 180 s stale window, so the reading never ages out while we wait.
REFRESH_SECONDS = 30
TIMEOUT_SECONDS = 300


def _anchor(client: httpx.Client, key: str, occupancy: int) -> dict:
    response = client.post(
        "/ingest/anchor",
        headers={"Authorization": f"Bearer {key}"},
        json={"occupancy": occupancy, "observedAt": datetime.now(UTC).isoformat()},
    )
    response.raise_for_status()
    return response.json()


def _open_recommendation(client: httpx.Client, route_id: str) -> dict | None:
    for recommendation in client.get(
        "/recommendations", params={"status": "OPEN"}
    ).json():
        if recommendation["routeId"] == route_id:
            return recommendation
    return None


def _hold_until_handled(
    client: httpx.Client, key: str, occupancy: int, recommendation_id: str
) -> None:
    """Keeps the tram full, and red on the map, until someone acts on the card."""
    print("waiting for the dispatcher — use the card on the map (Ctrl+C to stop)")
    while True:
        status = client.get(f"/recommendations/{recommendation_id}").json()["status"]
        if status != "OPEN":
            print(f"recommendation {status.lower()} on the map")
            return
        _anchor(client, key, occupancy)
        time.sleep(REFRESH_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--key", required=True, help="device key for that vehicle")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--speed", type=int, default=20, help="extra tram sim speed")
    parser.add_argument(
        "--no-dispatch",
        action="store_true",
        help="stop at the recommendation; send the reserve from the map instead",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=15) as client:
        vehicle = client.get(f"/vehicles/{args.vehicle_id}")
        if vehicle.status_code == 404:
            raise SystemExit(f"{args.vehicle_id} is not on the map — pick a live tram")
        _anchor(client, args.key, 0)
        tram = client.get(f"/vehicles/{args.vehicle_id}").json()["vehicle"]
        capacity, route_id = tram["capacity"], tram["routeId"]
        full = round(capacity * FULL_LOAD)
        print(f"{args.vehicle_id}: line {tram['routeShortName']} -> {tram['headsign']}")
        print(f"keeping it at {full}/{capacity} and waiting for the engine...")

        started = time.monotonic()
        recommendation = None
        while time.monotonic() - started < TIMEOUT_SECONDS:
            result = _anchor(client, args.key, full)
            elapsed = int(time.monotonic() - started)
            print(f"  {elapsed:4d}s  {result['occupancy']} people, {result['level']}")
            recommendation = _open_recommendation(client, route_id)
            if recommendation:
                break
            time.sleep(REFRESH_SECONDS)

        if recommendation is None:
            raise SystemExit("no recommendation — is the backend on the live feed?")

        reason = recommendation["reason"]
        print(
            f"\nrecommendation {recommendation['id']}: "
            f"{reason['loadFactor']:.0%} for {reason['durationSeconds']} s"
        )
        if args.no_dispatch:
            _hold_until_handled(client, args.key, full, recommendation["id"])
            return
        action = recommendation["proposedAction"]
        dispatch = client.post(
            "/mock-dispatch/extra-trams",
            json={
                "recommendationId": recommendation["id"],
                "routeId": recommendation["routeId"],
                "directionId": recommendation["directionId"],
                "startStopId": action["startStopId"],
                "endStopId": action["endStopId"],
                "capacity": action["capacity"],
                "departureDelaySeconds": 0,
                "simulationSpeed": args.speed,
            },
        )
        dispatch.raise_for_status()
        sent = dispatch.json()
        print(f"dispatched {sent['vehicleId']} on line {tram['routeShortName']}")
        print(
            "watch the Demo layer on the map — it runs the route at "
            f"{args.speed}x speed"
        )


if __name__ == "__main__":
    main()

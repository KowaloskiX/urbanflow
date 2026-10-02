"""Replays a cabin-camera timeline into the ingest API, as an in-vehicle device would.

    uv run python -m scripts.cabin_feed --vehicle-id ztp-tram:326 --key tbn_... \\
        --timeline out-32220631.json

The timeline is the JSON written by the cabin counting PoC: per frame, the number of
people, wheelchairs, strollers and bicycles. Every `--interval` seconds this sends the
current frame as an absolute count, with the mobility aids alongside, through the same
`/ingest/anchor` endpoint a door counter uses at a terminus.
"""

import argparse
import json
import time
from datetime import UTC, datetime

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--key", required=True, help="device key for that vehicle")
    parser.add_argument("--timeline", required=True, help="JSON from the cabin PoC")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds per send")
    parser.add_argument("--loop", action="store_true", help="start over at the end")
    args = parser.parse_args()

    with open(args.timeline) as handle:
        timeline = json.load(handle)["timeline"]
    step = max(1, len(timeline) // 12)  # about a dozen readings per pass

    with httpx.Client(base_url=args.api, timeout=15) as client:
        while True:
            for row in timeline[::step]:
                response = client.post(
                    "/ingest/anchor",
                    headers={"Authorization": f"Bearer {args.key}"},
                    json={
                        "occupancy": row["person"],
                        "observedAt": datetime.now(UTC).isoformat(),
                        "mobilityAids": {
                            "wheelchairs": row["wheelchair"],
                            "strollers": row["stroller"],
                            "bicycles": row["bicycle"],
                        },
                    },
                )
                response.raise_for_status()
                result = response.json()
                print(
                    f"t={row['t']:5.1f}s  {row['person']:3d} people, "
                    f"{row['wheelchair']} wheelchair, {row['stroller']} stroller, "
                    f"{row['bicycle']} bicycle -> {result['level']}"
                )
                time.sleep(args.interval)
            if not args.loop:
                return


if __name__ == "__main__":
    main()

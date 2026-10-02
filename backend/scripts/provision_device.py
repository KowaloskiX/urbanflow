"""Issues a key for a door counter and attaches it to one vehicle.

    uv run python -m scripts.provision_device --vehicle-id ztp-tram:3021

The key is printed once. Only its hash goes into the devices file, so losing the key
means issuing a new one. A running backend picks the new device up without a restart.

Vehicle ids are the ones on the map: `ztp-tram:<number>` / `ztp-bus:<number>` from the
GTFS-Realtime feed, or `2184` for the demo fixture.
"""

import argparse

from app.config import get_settings
from app.services.devices import Device, DeviceRegistry, generate_key

# The capacity the demo scenarios already assume for a Kraków tram.
DEFAULT_CAPACITY = 202


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vehicle-id", required=True)
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY)
    parser.add_argument("--label", default="door-counter")
    parser.add_argument("--file", default=get_settings().ingest_devices_file)
    args = parser.parse_args()

    key = generate_key()
    DeviceRegistry.append_to_file(
        args.file,
        key,
        Device(vehicle_id=args.vehicle_id, capacity=args.capacity, label=args.label),
    )
    print(f"vehicle  {args.vehicle_id}  (capacity {args.capacity})")
    print(f"key      {key}")
    print(f"\nWritten to {args.file}. Shown once — only its hash is stored.")


if __name__ == "__main__":
    main()

"""Which counter may write occupancy for which vehicle.

A counter authenticates with `Authorization: Bearer <key>`. Only the key's sha256 is
kept, so the devices file can leak without handing anybody the ability to write fake
occupancy. sha256 rather than a password hash: the key is 32 random bytes, there is
nothing to brute-force.

One key, one vehicle. A key pulled off a counter in the depot forges data for that tram
only.
"""

import hashlib
import json
import logging
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

KEY_PREFIX = "tbn_"


@dataclass(frozen=True)
class Device:
    vehicle_id: str
    capacity: int
    label: str = ""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    # A recognizable prefix, so secret scanners can spot a leaked key.
    return f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"


def _read(file: Path) -> dict[str, Device]:
    entries = json.loads(file.read_text(encoding="utf-8"))
    return {
        entry["keyHash"]: Device(
            vehicle_id=entry["vehicleId"],
            capacity=int(entry["capacity"]),
            label=entry.get("label", ""),
        )
        for entry in entries
    }


class DeviceRegistry:
    def __init__(
        self, devices: dict[str, Device] | None = None, file: Path | None = None
    ) -> None:
        self._registered: dict[str, Device] = dict(devices or {})
        self._file = file
        self._file_mtime: float | None = None
        self._from_file: dict[str, Device] = {}

    @classmethod
    def from_file(cls, path: str | Path) -> "DeviceRegistry":
        """A missing file is an empty registry: ingest then rejects every key.

        The file is re-read whenever it changes, so a device added with
        `scripts/provision_device.py` works at once. Restarting instead would wipe every
        in-memory count and re-download the GTFS timetables.
        """
        return cls(file=Path(path))

    def register(self, key: str, device: Device) -> None:
        self._registered[hash_key(key)] = device

    def resolve(self, key: str) -> Device | None:
        self._reload_if_changed()
        digest = hash_key(key)
        return self._registered.get(digest) or self._from_file.get(digest)

    def _reload_if_changed(self) -> None:
        if self._file is None:
            return
        try:
            mtime = self._file.stat().st_mtime
        except FileNotFoundError:
            self._from_file, self._file_mtime = {}, None
            return
        if mtime != self._file_mtime:
            self._from_file, self._file_mtime = _read(self._file), mtime

    @staticmethod
    def append_to_file(path: str | Path, key: str, device: Device) -> None:
        file = Path(path)
        entries = json.loads(file.read_text(encoding="utf-8")) if file.exists() else []
        entry = asdict(device)
        entries.append(
            {
                "keyHash": hash_key(key),
                "vehicleId": entry["vehicle_id"],
                "capacity": entry["capacity"],
                "label": entry["label"],
            }
        )
        file.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")

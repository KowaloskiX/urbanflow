"""Door-counter occupancy, kept in memory — the first real `OccupancyProvider`.

Two things this has to get right, both because counters sit on a flaky mobile link:

- **Idempotency.** A counter that delivered a batch but never saw the response sends it
  again. The passenger count is a running sum, so a double-counted batch is not a glitch
  that passes — it stays in the number until the next anchor. Every event carries a
  counter-generated id, and an id seen before moves nothing.
- **Staleness.** A count that stopped updating is not shown as current. `current()`
  returns nothing for a stale vehicle, so the dashboard shows UNKNOWN and the decision
  engine never acts on a frozen reading.

Kept in memory to match `StateStore`. The cost is explicit: a restart forgets every
count and every seen id, so a batch replayed across a restart is counted again. Fine for
the demo; the store's own docstring already names SQLite as the next step, and this
belongs there with it.

No locking: every method is synchronous, so on a single event loop each call runs to
completion before another starts.
"""

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.common import utc_now
from app.domain.occupancy import PassageEventIn, clamp_occupancy, passage_delta
from app.domain.vehicle import MobilityAids
from app.integrations.occupancy_provider import OccupancyMeasurement

SOURCE = "DOOR_COUNTER"
# Event ids remembered per vehicle. A counter retries within seconds, so this only has
# to cover a retry window, not history — it exists to stop memory growing for the life
# of the process.
SEEN_IDS_PER_VEHICLE = 10_000


@dataclass
class _VehicleCount:
    passenger_count: int
    capacity: int
    measured_at: datetime


@dataclass(frozen=True)
class IngestOutcome:
    accepted: int
    duplicates: int
    passenger_count: int
    capacity: int


class DoorCounterOccupancy:
    def __init__(self, *, stale_after_seconds: int, confidence: float) -> None:
        self.stale_after = timedelta(seconds=stale_after_seconds)
        # A door counter has no calibrated confidence. This is a declared number, there
        # so the decision engine's `minimum_confidence` gate has something to compare
        # against. Replace it with a measured one once counts have been checked against
        # a manual tally.
        self.confidence = confidence
        self._counts: dict[str, _VehicleCount] = {}
        # Only a cabin camera reports these, so they age on their own clock: door
        # passages keep the count fresh but say nothing about wheelchairs.
        self._aids: dict[str, tuple[MobilityAids, datetime]] = {}
        self._seen: dict[str, OrderedDict[str, None]] = {}

    def record_passages(
        self, vehicle_id: str, capacity: int, events: Sequence[PassageEventIn]
    ) -> IngestOutcome:
        seen = self._seen.setdefault(vehicle_id, OrderedDict())
        fresh = [event for event in events if event.event_id not in seen]
        state = self._counts.get(vehicle_id) or _VehicleCount(
            0, capacity, fresh[0].observed_at if fresh else utc_now()
        )

        # Oldest first, so each per-event clamp sees the real sequence. A batch buffered
        # through a tunnel arrives in any order.
        count = state.passenger_count
        for event in sorted(fresh, key=lambda item: item.observed_at):
            count = clamp_occupancy(
                count + passage_delta(event.direction, event.passengers), capacity
            )
            seen[event.event_id] = None
        while len(seen) > SEEN_IDS_PER_VEHICLE:
            seen.popitem(last=False)

        if fresh:
            newest = max(event.observed_at for event in fresh)
            # Never move the timestamp backwards: a late batch must not make a live
            # vehicle look older than it is.
            measured_at = (
                max(state.measured_at, newest) if vehicle_id in self._counts else newest
            )
            self._counts[vehicle_id] = _VehicleCount(count, capacity, measured_at)

        return IngestOutcome(
            accepted=len(fresh),
            duplicates=len(events) - len(fresh),
            passenger_count=count,
            capacity=capacity,
        )

    def record_anchor(
        self,
        vehicle_id: str,
        capacity: int,
        occupancy: int,
        observed_at: datetime,
        mobility_aids: MobilityAids | None = None,
    ) -> IngestOutcome:
        """Replaces the running sum. Idempotent by nature — no event id needed."""
        count = clamp_occupancy(occupancy, capacity)
        self._counts[vehicle_id] = _VehicleCount(count, capacity, observed_at)
        if mobility_aids is not None:
            self._aids[vehicle_id] = (mobility_aids, observed_at)
        return IngestOutcome(
            accepted=1, duplicates=0, passenger_count=count, capacity=capacity
        )

    def current(
        self, vehicle_id: str, now: datetime | None = None
    ) -> OccupancyMeasurement | None:
        """The vehicle's count, or `None` when there is none or it has gone stale."""
        state = self._counts.get(vehicle_id)
        if state is None or (now or utc_now()) - state.measured_at > self.stale_after:
            return None
        return OccupancyMeasurement(
            vehicle_id=vehicle_id,
            passenger_count=state.passenger_count,
            capacity=state.capacity,
            load_factor=state.passenger_count / state.capacity,
            confidence=self.confidence,
            measured_at=state.measured_at,
            source=SOURCE,
        )

    def mobility_aids(
        self, vehicle_id: str, now: datetime | None = None
    ) -> MobilityAids | None:
        """What the cabin camera last saw besides people, while that is still fresh."""
        entry = self._aids.get(vehicle_id)
        if entry is None or (now or utc_now()) - entry[1] > self.stale_after:
            return None
        return entry[0]

    def expired_at(
        self, vehicle_id: str, now: datetime | None = None
    ) -> datetime | None:
        """When the vehicle's last count was measured, if that count has gone stale."""
        state = self._counts.get(vehicle_id)
        if state is None or (now or utc_now()) - state.measured_at <= self.stale_after:
            return None
        return state.measured_at

    def has_fresh_data(self) -> bool:
        return any(self.current(vehicle_id) for vehicle_id in self._counts)

    async def get_measurements(
        self, vehicle_ids: list[str]
    ) -> list[OccupancyMeasurement]:
        """Implements `OccupancyProvider` from `integrations/occupancy_provider.py`."""
        return [m for vid in vehicle_ids if (m := self.current(vid)) is not None]

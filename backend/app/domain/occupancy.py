"""Occupancy from door counters: boarding and alighting deltas become a count.

A counter above a door does not measure how many people are inside. It reports people
crossing the doorway, so the count is a running sum — and a running sum drifts, because
every miscount stays in it. Two rules here keep that error bounded:

- the count is clamped to a physical range, so a counter that misses boardings cannot
  drive it negative and one that double-counts cannot drive it to a thousand;
- an anchor replaces the sum with an absolute value. At a terminus everybody gets off,
  so the truth is zero whatever the deltas added up to.

The decision engine reads `load_factor`, not the raw count, and its thresholds are
coarse (85%), which is what makes a drifting estimate usable at all.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, ConfigDict, Field, field_validator

from app.domain.common import ApiModel
from app.domain.vehicle import OccupancyStatus

# A tram's nominal capacity is not the most it can physically hold — crush load runs
# well past it, and OVER_CAPACITY only exists as a status because of that. The clamp
# therefore sits above nominal capacity rather than at it.
MAX_LOAD_FACTOR = 1.3

# One request carries at most this many events: minutes of buffering after a dropped
# link, while keeping a single request bounded.
MAX_EVENTS_PER_BATCH = 200
# Nobody passes one doorway in groups larger than this. A bigger number is a broken
# counter.
MAX_PASSENGERS_PER_EVENT = 50
# Counter clocks are not synced to ours. Some skew is normal; hours of it is a broken
# clock, and a future timestamp would keep a dead counter looking fresh.
MAX_CLOCK_SKEW = timedelta(minutes=5)


class PassageDirection(StrEnum):
    BOARDING = "boarding"
    ALIGHTING = "alighting"


def passage_delta(direction: str, passengers: int) -> int:
    """Signed change in occupancy.

    `==` rather than `is`: `ApiModel` sets `use_enum_values`, so this arrives as a str.
    """
    if passengers < 0:
        raise ValueError("passengers must not be negative")
    return passengers if direction == PassageDirection.BOARDING else -passengers


def clamp_occupancy(count: int, capacity: int) -> int:
    """Keeps the running sum inside what a vehicle can physically hold."""
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    return max(0, min(count, round(capacity * MAX_LOAD_FACTOR)))


def _reject_far_future(value: datetime) -> datetime:
    if value > datetime.now(UTC) + MAX_CLOCK_SKEW:
        raise ValueError(
            "observedAt lies too far in the future — check the counter clock"
        )
    return value


# A counter timestamp: timezone-aware (a naive one from an unknown timezone is unusable)
# and not implausibly ahead of our clock.
ObservedAt = Annotated[AwareDatetime, AfterValidator(_reject_far_future)]


class _StrictModel(ApiModel):
    # A typo in a field name should be a 422, not a silently ignored field.
    model_config = ConfigDict(extra="forbid")


class PositionIn(_StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class PassageEventIn(_StrictModel):
    """One crossing of a doorway.

    `event_id` comes from the counter and must stay the same across retries — that is
    what keeps a redelivered batch from being counted twice.
    """

    event_id: str = Field(min_length=1, max_length=64)
    door: str = Field(min_length=1, max_length=16)
    direction: PassageDirection
    passengers: int = Field(ge=0, le=MAX_PASSENGERS_PER_EVENT)
    observed_at: ObservedAt


class PassageBatchIn(_StrictModel):
    events: list[PassageEventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)
    # Accepted for compatibility with the counter, and deliberately ignored: in
    # UrbanFlow the GTFS-Realtime feed owns vehicle position, and two sources writing it
    # would make the marker jump between them.
    position: PositionIn | None = None

    @field_validator("events")
    @classmethod
    def _unique_ids(cls, events: list[PassageEventIn]) -> list[PassageEventIn]:
        """Two events sharing an id within one batch is a counter bug, not a retry."""
        if len({event.event_id for event in events}) != len(events):
            raise ValueError("eventId must be unique within a batch")
        return events


class MobilityAidsIn(_StrictModel):
    wheelchairs: int = Field(default=0, ge=0, le=20)
    strollers: int = Field(default=0, ge=0, le=20)
    bicycles: int = Field(default=0, ge=0, le=40)


class AnchorIn(_StrictModel):
    """An absolute count replacing the running sum.

    Sent at a terminus by a door counter, or every few seconds by a cabin camera, which
    sees the whole vehicle and can also report what takes extra floor space.
    """

    occupancy: int = Field(ge=0, le=1000)
    observed_at: ObservedAt
    position: PositionIn | None = None
    mobility_aids: MobilityAidsIn | None = None


class IngestResult(ApiModel):
    """`duplicates` is a success: a counter retrying a batch it already delivered."""

    vehicle_id: str
    accepted: int
    duplicates: int
    occupancy: int
    level: OccupancyStatus

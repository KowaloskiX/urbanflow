"""Geometry and events for doorway counting. Pure — no model, no camera, no HTTP.

Everything that decides whether somebody boarded lives here, which is what makes the decision
testable without a camera or a gigabyte of model weights.
"""

from dataclasses import dataclass
from enum import StrEnum


class PassageDirection(StrEnum):
    """Matches the API contract in `app.core.domain.fleet` — the same two words on the wire."""

    BOARDING = "boarding"
    ALIGHTING = "alighting"


@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned box in pixels, top-left origin."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def iou(self, other: "Box") -> float:
        """Intersection over union — how much two boxes overlap, from 0 to 1."""
        left, right = max(self.x1, other.x1), min(self.x2, other.x2)
        top, bottom = max(self.y1, other.y1), min(self.y2, other.y2)
        overlap = max(0.0, right - left) * max(0.0, bottom - top)
        union = self.area + other.area - overlap
        return overlap / union if union > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Detection:
    """One person the model found in one frame."""

    box: Box
    confidence: float


@dataclass(frozen=True, slots=True)
class CountingLine:
    """The tripwire across the doorway.

    Two points in pixel coordinates, plus which side of it is inside the vehicle. A crossing
    from outside to inside is a boarding; the reverse is an alighting.

    Deliberately a line rather than a region. A region needs a person to be fully inside it for
    a frame, which fails at exactly the moment that matters — a crowded door, where people pass
    quickly and half-occluded. A line only needs a centre point to be on one side and then the
    other.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    # `+1` if the positive side of the cross product is inside the vehicle, `-1` otherwise.
    # Which one that is depends on how the camera is mounted, so it is configuration.
    inside_sign: int = 1

    def side(self, point: tuple[float, float]) -> int:
        """Which side of the line a point falls on: `+1`, `-1`, or `0` exactly on it."""
        cross = (self.x2 - self.x1) * (point[1] - self.y1) - (self.y2 - self.y1) * (
            point[0] - self.x1
        )
        if cross > 0:
            return 1
        if cross < 0:
            return -1
        return 0

    def crossed_between(
        self, before: tuple[float, float], after: tuple[float, float]
    ) -> PassageDirection | None:
        """The direction of a crossing between two consecutive positions, or `None`.

        Two conditions, and the second one is the one that is easy to forget: the point has to
        change sides, AND the crossing has to happen **within the segment**. A line is
        infinite; a doorway is not. Without the bound, somebody walking past the far end of the
        tram would be counted as boarding it.
        """
        first, second = self.side(before), self.side(after)
        if first == 0 or second == 0 or first == second:
            return None
        if not self._intersects_segment(before, after):
            return None
        return (
            PassageDirection.BOARDING if second == self.inside_sign else PassageDirection.ALIGHTING
        )

    def _intersects_segment(self, before: tuple[float, float], after: tuple[float, float]) -> bool:
        """Whether the movement crosses the line BETWEEN its endpoints rather than beyond them.

        Standard segment intersection: the two endpoints of the line must also fall on opposite
        sides of the movement.
        """
        dx, dy = after[0] - before[0], after[1] - before[1]

        def side_of_movement(point: tuple[float, float]) -> int:
            cross = dx * (point[1] - before[1]) - dy * (point[0] - before[0])
            return (cross > 0) - (cross < 0)

        start = side_of_movement((self.x1, self.y1))
        end = side_of_movement((self.x2, self.y2))
        return start != end and start != 0 and end != 0


@dataclass(frozen=True, slots=True)
class Crossing:
    """Somebody passed the line. `track_id` is what makes it countable exactly once."""

    track_id: int
    direction: PassageDirection
    frame: int

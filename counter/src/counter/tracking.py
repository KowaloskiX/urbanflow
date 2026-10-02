"""Turning per-frame detections into persistent tracks.

Why a tracker is not optional: a detector answers "there are three people in this frame" and
nothing more. Counting needs "this is the same person as in the previous frame, and they have
just moved from outside to inside" — an identity that survives across frames. Without it, a
person standing in the doorway would be counted once per frame.

Greedy IoU matching, deliberately. ByteTrack and friends add a Kalman filter and appearance
embeddings, which pay off for long occlusions across a wide scene. A doorway is the opposite
case: a small field of view, people crossing in under a second, and a camera that does not
move. Overlap between consecutive frames is enough, and it costs no model and no GPU.
"""

from dataclasses import dataclass, field, replace

from counter.domain import Box, CountingLine, Crossing, Detection


@dataclass(frozen=True, slots=True)
class Track:
    """One person, followed across frames."""

    id: int
    box: Box
    # Consecutive frames this track was not matched to any detection. A person half-occluded
    # by another passenger disappears for a frame or two; dropping them immediately would
    # restart their identity and lose the crossing.
    misses: int = 0
    # Where the centre was when the person was last actually SEEN — the other half of a
    # crossing test. Never a predicted position: see `_advance`.
    previous_centre: tuple[float, float] | None = None
    # Pixels per frame, from the last two observations. Used only to keep matching alive
    # through an occlusion.
    velocity: tuple[float, float] = (0.0, 0.0)
    # A track is counted at most once. Somebody who stops in the doorway and drifts back and
    # forth across the line must not be counted on every wobble.
    counted: bool = False


@dataclass
class DoorwayCounter:
    """Detections in, crossings out.

    Holds the only mutable state in the package: the live tracks and the id counter.
    """

    line: CountingLine
    # Below this, two boxes are treated as different people. Tuned for a doorway, where a
    # person moves a fraction of their own width between frames.
    iou_threshold: float = 0.25
    # How many frames a track survives without a detection. At 15 fps this is roughly a third
    # of a second of occlusion.
    max_misses: int = 5
    # Detections the model is not confident about are dropped before tracking. A false positive
    # that crosses the line is a phantom passenger, and the accumulator keeps it forever.
    min_confidence: float = 0.5

    _tracks: list[Track] = field(default_factory=list)
    _next_id: int = 1
    _frame: int = 0

    @property
    def tracks(self) -> tuple[Track, ...]:
        return tuple(self._tracks)

    def update(self, detections: list[Detection]) -> list[Crossing]:
        """Advances by one frame and returns the crossings that happened in it."""
        self._frame += 1
        confident = [d for d in detections if d.confidence >= self.min_confidence]

        matches, unmatched = self._match(confident)
        crossings: list[Crossing] = []
        survivors: list[Track] = []

        for track in self._tracks:
            detection = matches.get(track.id)
            if detection is None:
                if track.misses + 1 <= self.max_misses:
                    survivors.append(self._advance(track))
                continue

            centre = detection.box.centre
            crossing = self._crossing_for(track, centre)
            if crossing is not None:
                crossings.append(crossing)
            previous = track.previous_centre
            survivors.append(
                replace(
                    track,
                    box=detection.box,
                    misses=0,
                    previous_centre=centre,
                    velocity=(
                        (centre[0] - previous[0], centre[1] - previous[1])
                        if previous is not None
                        else track.velocity
                    ),
                    counted=track.counted or crossing is not None,
                )
            )

        for detection in unmatched:
            survivors.append(
                Track(
                    id=self._next_id,
                    box=detection.box,
                    previous_centre=detection.box.centre,
                )
            )
            self._next_id += 1

        self._tracks = survivors
        return crossings

    def _advance(self, track: Track) -> Track:
        """Carries an unmatched track forward at its last known speed.

        This is what makes `max_misses` worth anything. Overlap between consecutive frames is
        the only association signal here, so a person hidden behind another passenger for half
        a second reappears a stride away from where they vanished — with no overlap, and a
        fresh identity, and their crossing lost.

        The predicted box is used for MATCHING only. `previous_centre` keeps the last position
        the person was actually seen at, because a crossing inferred from a guessed position is
        a passenger nobody observed.
        """
        dx, dy = track.velocity
        box = track.box
        return replace(
            track,
            misses=track.misses + 1,
            box=Box(box.x1 + dx, box.y1 + dy, box.x2 + dx, box.y2 + dy),
        )

    def _crossing_for(self, track: Track, centre: tuple[float, float]) -> Crossing | None:
        if track.counted or track.previous_centre is None:
            return None
        direction = self.line.crossed_between(track.previous_centre, centre)
        if direction is None:
            return None
        return Crossing(track_id=track.id, direction=direction, frame=self._frame)

    def _match(self, detections: list[Detection]) -> tuple[dict[int, Detection], list[Detection]]:
        """Greedy assignment: the best overlap first, and each side used once.

        Greedy rather than the Hungarian algorithm because a doorway holds a handful of people
        and overlaps are unambiguous. The optimal assignment would differ only in cases where
        two people overlap almost identically, and there the answer is a coin toss anyway.
        """
        pairs = sorted(
            (
                (track.box.iou(detection.box), track.id, index)
                for track in self._tracks
                for index, detection in enumerate(detections)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )

        matches: dict[int, Detection] = {}
        used: set[int] = set()
        for score, track_id, index in pairs:
            if score < self.iou_threshold or track_id in matches or index in used:
                continue
            matches[track_id] = detections[index]
            used.add(index)

        unmatched = [d for index, d in enumerate(detections) if index not in used]
        return matches, unmatched

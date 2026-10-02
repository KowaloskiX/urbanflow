"""Tracking is what turns "three people are visible" into "one person just boarded".

Every test here is about identity across frames, because that is the only thing standing
between the model and counting the same passenger once per frame.
"""

from counter.domain import Box, CountingLine, Detection, PassageDirection
from counter.tracking import DoorwayCounter

LINE = CountingLine(x1=0, y1=240, x2=640, y2=240, inside_sign=1)


def person(centre_x: float, centre_y: float, confidence: float = 0.9) -> Detection:
    """A person-sized box around a point, in a 640x480 doorway view."""
    return Detection(
        box=Box(centre_x - 30, centre_y - 60, centre_x + 30, centre_y + 60),
        confidence=confidence,
    )


def test_a_person_walking_in_is_counted_once() -> None:
    counter = DoorwayCounter(line=LINE)

    crossings = [counter.update([person(320, y)]) for y in (150, 200, 250, 300, 350)]
    flat = [crossing for frame in crossings for crossing in frame]

    assert len(flat) == 1
    assert flat[0].direction is PassageDirection.BOARDING


def test_somebody_loitering_on_the_threshold_is_not_counted_repeatedly() -> None:
    """The failure this guards against is not hypothetical: a person waiting in the doorway
    drifts a few pixels either way, and every wobble across the line is a fare."""
    counter = DoorwayCounter(line=LINE)

    for y in (200, 260, 220, 270, 230, 280):
        counter.update([person(320, y)])

    total = sum(len(counter.update([person(320, y)])) for y in (210, 290, 215, 295))

    assert total == 0, "a single track must produce at most one crossing"


def test_two_people_crossing_together_are_counted_separately() -> None:
    counter = DoorwayCounter(line=LINE)
    found = []

    for y in (180, 220, 260, 300):
        found.extend(counter.update([person(200, y), person(440, y)]))

    assert len(found) == 2
    assert {c.track_id for c in found} == {1, 2}


def test_a_track_survives_a_frame_of_occlusion() -> None:
    """Passengers block each other constantly. Dropping a track on the first missed frame
    restarts its identity — and an identity that restarts mid-doorway loses the crossing."""
    counter = DoorwayCounter(line=LINE)

    # Two frames of real movement first, so the track knows how fast this person walks.
    counter.update([person(320, 150)])
    counter.update([person(320, 190)])
    counter.update([])  # hidden behind another passenger
    counter.update([])
    crossings = counter.update([person(320, 310)])

    assert len(crossings) == 1, "the crossing was lost to a re-identified track"
    assert counter.tracks[0].id == 1, "the same person, not a new one"


def test_a_track_lost_for_too_long_is_forgotten() -> None:
    counter = DoorwayCounter(line=LINE, max_misses=2)

    counter.update([person(320, 150)])
    for _ in range(3):
        counter.update([])

    assert counter.tracks == ()


def test_an_unmatched_track_is_not_moved_while_it_waits() -> None:
    """A track kept alive through occlusion has no new position. Interpolating one would
    fabricate a crossing for somebody nobody can see."""
    counter = DoorwayCounter(line=LINE)

    counter.update([person(320, 150)])
    counter.update([person(320, 200)])
    assert counter.update([]) == [], "a predicted position must not produce a crossing"
    assert counter.update([]) == []


def test_low_confidence_detections_never_reach_the_tracker() -> None:
    """A false positive that crosses the line is a phantom passenger, and the server's
    accumulator keeps it until the next anchor."""
    counter = DoorwayCounter(line=LINE, min_confidence=0.6)

    counter.update([person(320, 150, confidence=0.2)])
    crossings = counter.update([person(320, 330, confidence=0.2)])

    assert counter.tracks == ()
    assert crossings == []


def test_someone_walking_past_the_doorway_is_not_a_passenger() -> None:
    """Movement parallel to the line, on the platform side, crosses nothing."""
    counter = DoorwayCounter(line=LINE)

    counter.update([person(100, 150)])
    crossings = counter.update([person(500, 150)])

    assert crossings == []

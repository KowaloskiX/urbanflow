"""The tripwire. Pure geometry, and the place where a wrong sign becomes wrong data.

Getting `inside_sign` backwards records every boarding as an alighting, and the resulting
occupancy is not merely wrong but inverted — so these are tested at the level of "which
direction", not "did something happen".
"""

import pytest

from counter.domain import CountingLine, PassageDirection

# A horizontal line across a 640x480 doorway view. Below it (larger y) is inside the vehicle.
LINE = CountingLine(x1=0, y1=240, x2=640, y2=240, inside_sign=1)


def test_no_crossing_when_the_person_stays_on_one_side() -> None:
    assert LINE.crossed_between((320, 100), (320, 200)) is None
    assert LINE.crossed_between((320, 300), (320, 460)) is None


def test_moving_inwards_is_a_boarding() -> None:
    assert LINE.crossed_between((320, 200), (320, 280)) is PassageDirection.BOARDING


def test_moving_outwards_is_an_alighting() -> None:
    assert LINE.crossed_between((320, 280), (320, 200)) is PassageDirection.ALIGHTING


def test_the_inside_side_is_configuration_not_convention() -> None:
    """The camera can be mounted either way round. Flipping the sign flips the meaning, and
    nothing else about the geometry changes."""
    flipped = CountingLine(x1=0, y1=240, x2=640, y2=240, inside_sign=-1)

    assert flipped.crossed_between((320, 200), (320, 280)) is PassageDirection.ALIGHTING


def test_a_crossing_beyond_the_ends_of_the_line_does_not_count() -> None:
    """A line is infinite; a doorway is not.

    Without the segment bound, somebody walking past the far end of the tram would be recorded
    as boarding it — and on a busy platform that is a constant stream of phantom passengers.
    """
    beyond_the_right_end = LINE.crossed_between((900, 200), (900, 280))

    assert beyond_the_right_end is None


def test_a_person_exactly_on_the_line_is_not_yet_a_crossing() -> None:
    """Standing on the threshold is not passing through it. Counting it would fire again on
    the next frame, when they step off in either direction."""
    assert LINE.crossed_between((320, 200), (320, 240)) is None
    assert LINE.crossed_between((320, 240), (320, 280)) is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ((100, 100), (500, 400), PassageDirection.BOARDING),
        ((500, 400), (100, 100), PassageDirection.ALIGHTING),
    ],
)
def test_diagonal_movement_still_resolves_a_direction(
    before: tuple[float, float], after: tuple[float, float], expected: PassageDirection
) -> None:
    """People do not walk perpendicular to the doorway."""
    assert LINE.crossed_between(before, after) is expected

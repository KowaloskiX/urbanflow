"""Delivery from a device on a mobile link inside a moving vehicle.

Every test here is a network failure, because that is the normal condition: tunnels, handovers,
a depot with no signal. What must never happen is a boarding counted twice — the server's
occupancy is an accumulator, so a double-counted retry stays wrong until the next anchor.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from counter.domain import Crossing, PassageDirection
from counter.ingest import MAX_BATCH, IngestClient, Position


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def accepted(request: httpx.Request) -> httpx.Response:
    events = json.loads(request.content)["events"]
    return httpx.Response(
        200,
        json={
            "accepted": len(events),
            "duplicates": 0,
            "occupancy": len(events),
            "level": "empty",
        },
    )


def ingest() -> IngestClient:
    return IngestClient(api_url="http://api", device_key="tbn_test", run_id="abc123", door="front")


def crossing(track_id: int) -> Crossing:
    return Crossing(track_id=track_id, direction=PassageDirection.BOARDING, frame=1)


async def test_recording_never_touches_the_network() -> None:
    """Counting happens between two video frames. A blocking send there would drop frames, and
    a dropped frame is a missed crossing."""
    buffered = ingest()

    buffered.record(crossing(1))
    buffered.record(crossing(2))

    assert buffered.pending == 2


async def test_a_flush_delivers_the_buffer_and_empties_it() -> None:
    buffered = ingest()
    buffered.record(crossing(1))

    async with client_for(accepted) as client:
        assert await buffered.flush(client) is True

    assert buffered.pending == 0


async def test_a_failed_delivery_keeps_the_events_for_the_next_attempt() -> None:
    """The tunnel case. Discarding here would lose passengers silently, and the vehicle would
    read low for the rest of the run."""
    buffered = ingest()
    buffered.record(crossing(1))

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with client_for(unreachable) as client:
        assert await buffered.flush(client) is False

    assert buffered.pending == 1


async def test_a_retry_carries_the_same_event_ids() -> None:
    """The guarantee that makes buffering safe.

    If the first attempt actually reached the server and only the response was lost, the retry
    must fold into duplicates rather than count the same people again.
    """
    buffered = ingest()
    buffered.record(crossing(7))
    seen: list[list[str]] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        events = json.loads(request.content)["events"]
        seen.append([event["event_id"] for event in events])
        if len(seen) == 1:
            raise httpx.ReadTimeout("response lost")
        return accepted(request)

    async with client_for(flaky) as client:
        await buffered.flush(client)
        await buffered.flush(client)

    assert seen[0] == seen[1], "a retry invented new ids and would be counted twice"
    assert buffered.pending == 0


async def test_ids_differ_between_runs() -> None:
    """A restarted counter must not reuse ids. If it did, every event of the new run would be
    a duplicate of the old one and the vehicle would silently stop counting."""
    first = IngestClient(api_url="http://api", device_key="k", run_id="run-one")
    second = IngestClient(api_url="http://api", device_key="k", run_id="run-two")
    first.record(crossing(1))
    second.record(crossing(1))

    async def ids(source: IngestClient) -> str:
        captured: list[str] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content)["events"][0]["event_id"])
            return accepted(request)

        async with client_for(capture) as client:
            await source.flush(client)
        return captured[0]

    assert await ids(first) != await ids(second)


async def test_a_permanently_rejected_batch_is_discarded() -> None:
    """A malformed batch will never be accepted. Retrying it forever would wedge the buffer and
    block every event queued behind it."""
    buffered = ingest()
    buffered.record(crossing(1))

    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"code": "validation_failed", "message": "bad"})

    async with client_for(rejected) as client:
        assert await buffered.flush(client) is False

    assert buffered.pending == 0, "an unacceptable batch must not block the queue forever"


async def test_a_conflict_is_kept_and_retried() -> None:
    """409 means the write lost a race with an identical one — the one 4xx that retrying fixes."""
    buffered = ingest()
    buffered.record(crossing(1))

    def conflict(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"code": "ingest_conflict", "message": "retry"})

    async with client_for(conflict) as client:
        assert await buffered.flush(client) is False

    assert buffered.pending == 1


async def test_one_request_never_exceeds_what_the_api_accepts() -> None:
    """The API rejects a batch larger than `MAX_EVENTS_PER_BATCH`, and a rejected batch after a
    long outage is exactly when the buffer is fullest."""
    buffered = ingest()
    for track_id in range(MAX_BATCH + 50):
        buffered.record(crossing(track_id))
    sizes: list[int] = []

    def measure(request: httpx.Request) -> httpx.Response:
        sizes.append(len(json.loads(request.content)["events"]))
        return accepted(request)

    async with client_for(measure) as client:
        await buffered.flush(client)

    assert sizes == [MAX_BATCH]
    assert buffered.pending == 50, "the remainder waits for the next flush"


async def test_position_rides_along_when_the_device_knows_where_it_is() -> None:
    buffered = ingest()
    buffered.record(crossing(1))
    captured: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return accepted(request)

    async with client_for(capture) as client:
        await buffered.flush(client, Position(latitude=51.1, longitude=17.03))

    assert captured[0]["position"] == {"latitude": 51.1, "longitude": 17.03}


async def test_an_empty_buffer_makes_no_request() -> None:
    buffered = ingest()

    def fail(request: httpx.Request) -> httpx.Response:
        pytest.fail("flushing an empty buffer must not hit the network")

    async with client_for(fail) as client:
        assert await buffered.flush(client) is True

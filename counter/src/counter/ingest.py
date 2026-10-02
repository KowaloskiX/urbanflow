"""Delivering crossings to the API.

The device side of the contract described in the README. Three things it has to get right, all
of them consequences of running on a mobile link inside a moving vehicle:

- **Batch.** One HTTP request per person through a doorway would be dozens per stop on a link
  that drops in tunnels.
- **Buffer.** A failed delivery is retried later, not discarded. Events accumulate while the
  connection is gone.
- **Repeat the same ids.** A retry carries the identical `event_id` values, so the server folds
  it into nothing instead of counting the same boarding twice. That guarantee is what makes
  buffering safe in the first place.
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from counter.domain import Crossing

logger = logging.getLogger(__name__)

# The API rejects a batch larger than this (`MAX_EVENTS_PER_BATCH` in `app.schemas.fleet`).
MAX_BATCH = 200
# How many events to hold while the link is down. At a busy stop a doorway produces a few
# dozen, so this is roughly an hour of buffering — past that, the oldest are dropped and said
# so out loud, because silent loss looks exactly like a quiet afternoon.
BUFFER_LIMIT = 2_000


@dataclass(frozen=True, slots=True)
class Position:
    latitude: float
    longitude: float


@dataclass
class IngestClient:
    """Buffers crossings and posts them as delta batches."""

    api_url: str
    device_key: str
    # Distinguishes this process from an earlier one in every `event_id`. Without it a
    # restarted counter reuses ids, the server recognizes every event as a duplicate, and the
    # vehicle silently stops counting.
    run_id: str
    door: str = "front"
    timeout_seconds: float = 10.0

    _buffer: deque[dict[str, object]] = field(default_factory=lambda: deque(maxlen=BUFFER_LIMIT))
    _dropped: int = 0

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def record(self, crossing: Crossing, observed_at: datetime | None = None) -> None:
        """Queues one crossing. Never blocks and never talks to the network."""
        if len(self._buffer) == self._buffer.maxlen:
            self._dropped += 1
            logger.error(
                "ingest buffer full — dropped %d event(s); the vehicle will read low until the "
                "next anchor",
                self._dropped,
            )
        self._buffer.append(
            {
                # Stable across retries, unique across runs. `track_id` is what stops the same
                # person being counted twice within a run.
                "event_id": f"{self.run_id}:{self.door}:{crossing.track_id}",
                "door": self.door,
                "direction": crossing.direction,
                "passengers": 1,
                "observed_at": (observed_at or datetime.now(UTC)).isoformat(),
            }
        )

    async def flush(self, client: httpx.AsyncClient, position: Position | None = None) -> bool:
        """Sends what is buffered. Returns whether it landed.

        On failure the batch stays in the buffer, in order, and goes out again with the same
        ids — which the server folds into duplicates if part of it had in fact arrived.
        """
        if not self._buffer:
            return True

        batch = list(self._buffer)[:MAX_BATCH]
        payload: dict[str, object] = {"events": batch}
        if position is not None:
            payload["position"] = {
                "latitude": position.latitude,
                "longitude": position.longitude,
            }

        try:
            response = await client.post(
                f"{self.api_url}/ingest/passages",
                json=payload,
                headers={"Authorization": f"Bearer {self.device_key}"},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as error:
            logger.warning(
                "ingest unreachable, keeping %d event(s) buffered: %s", len(batch), error
            )
            return False

        if response.status_code != 200:
            # 4xx other than 409 means the batch is malformed and will never be accepted.
            # Retrying it forever would block every event behind it.
            if 400 <= response.status_code < 500 and response.status_code != 409:
                logger.error(
                    "ingest rejected a batch permanently (%s): %s — discarding %d event(s)",
                    response.status_code,
                    response.text[:200],
                    len(batch),
                )
                self._forget(len(batch))
            return False

        self._forget(len(batch))
        body = response.json()
        logger.info(
            "delivered %d event(s): %d new, %d duplicate, occupancy now %d (%s)",
            len(batch),
            body["accepted"],
            body["duplicates"],
            body["occupancy"],
            body["level"],
        )
        return True

    async def anchor(
        self, client: httpx.AsyncClient, occupancy: int, position: Position | None = None
    ) -> bool:
        """Reports an absolute occupancy — a terminus, or a manual reset.

        Sent separately from the deltas and with no idempotency key, because writing the same
        absolute value twice is the same as writing it once.
        """
        payload: dict[str, object] = {
            "occupancy": occupancy,
            "observed_at": datetime.now(UTC).isoformat(),
        }
        if position is not None:
            payload["position"] = {
                "latitude": position.latitude,
                "longitude": position.longitude,
            }
        try:
            response = await client.post(
                f"{self.api_url}/ingest/anchor",
                json=payload,
                headers={"Authorization": f"Bearer {self.device_key}"},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as error:
            logger.warning("anchor failed: %s", error)
            return False
        return response.status_code == 200

    def _forget(self, count: int) -> None:
        for _ in range(min(count, len(self._buffer))):
            self._buffer.popleft()

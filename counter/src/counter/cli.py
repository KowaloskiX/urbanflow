"""Runs the counter over a camera or a video file.

    uv sync --extra ml
    uv run count-doorway --source 0 --device-key tbn_... --preview

The pipeline is four steps, and only the first needs a model: detect people, follow them
across frames, notice who crossed the line, post the crossings in batches.
"""

import asyncio
import logging
import secrets
from collections import Counter
from typing import Any

import httpx
from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict

from counter.domain import CountingLine
from counter.ingest import IngestClient, Position
from counter.tracking import DoorwayCounter

logger = logging.getLogger(__name__)


def _parse_line(value: str, inside_sign: int) -> CountingLine:
    parts = [piece.strip() for piece in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--line takes four comma-separated pixel coordinates: x1,y1,x2,y2")
    x1, y1, x2, y2 = (float(part) for part in parts)
    return CountingLine(x1=x1, y1=y1, x2=x2, y2=y2, inside_sign=inside_sign)


def _default_line(width: int, height: int, inside_sign: int) -> CountingLine:
    """A horizontal line across the middle of the frame.

    Guessing beats demanding four numbers from somebody who has not seen the frame yet. It is
    right for the common mounting — camera above the door, looking down, passengers crossing
    top to bottom — and `--preview` shows immediately when it is not.
    """
    middle = height / 2
    return CountingLine(x1=0, y1=middle, x2=float(width), y2=middle, inside_sign=inside_sign)


def _draw(frame: Any, counter: DoorwayCounter, detections: list[Any], tally: Counter[str]) -> bool:
    """Draws the frame with the line, the tracks and the running tally. Returns False on `q`.

    This exists because two settings cannot be chosen without seeing a frame: where the line
    goes, and which side of it is inside. Getting `--inside-sign` backwards records every
    boarding as an alighting, and the occupancy is then not merely wrong but inverted — with no
    symptom until somebody compares it against a real tram.
    """
    import cv2

    line = counter.line
    cv2.line(
        frame,
        (int(line.x1), int(line.y1)),
        (int(line.x2), int(line.y2)),
        (0, 215, 255),
        2,
    )
    # A short arrow from the middle of the line towards the inside. If it does not point into
    # the vehicle, flip --inside-sign.
    mid = ((line.x1 + line.x2) / 2, (line.y1 + line.y2) / 2)
    normal = (-(line.y2 - line.y1), line.x2 - line.x1)
    length = (normal[0] ** 2 + normal[1] ** 2) ** 0.5 or 1.0
    step = 40 * line.inside_sign
    tip = (mid[0] + normal[0] / length * step, mid[1] + normal[1] / length * step)
    cv2.arrowedLine(frame, (int(mid[0]), int(mid[1])), (int(tip[0]), int(tip[1])), (0, 215, 255), 2)
    cv2.putText(
        frame,
        "inside",
        (int(tip[0]) + 6, int(tip[1])),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 215, 255),
        1,
    )

    for detection in detections:
        box = detection.box
        cv2.rectangle(
            frame, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), (120, 120, 120), 1
        )

    for track in counter.tracks:
        box = track.box
        colour = (80, 200, 80) if track.counted else (240, 160, 40)
        cv2.rectangle(frame, (int(box.x1), int(box.y1)), (int(box.x2), int(box.y2)), colour, 2)
        cv2.putText(
            frame,
            f"#{track.id}",
            (int(box.x1), int(box.y1) - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            colour,
            1,
        )

    cv2.putText(
        frame,
        f"in {tally['boarding']}   out {tally['alighting']}   q to quit",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )
    cv2.imshow("doorway", frame)
    # Typed explicitly: without the `ml` extra cv2 is untyped, and the comparison would
    # leak `Any` out of a function declared to return bool.
    key: int = cv2.waitKey(1) & 0xFF
    return key != ord("q")


# How long to let a camera settle before believing what it sends. A webcam is ready almost
# at once; an iPhone over Continuity Camera takes a second or two and hands out black frames
# until it is.
_WARM_UP_SECONDS = 4.0
# Mean pixel value below which a frame is darkness rather than a dark room.
_BLACK_FRAME = 5.0
# Consecutive failed reads tolerated from a live camera before declaring it gone. A
# wireless camera drops frames while it reconnects; half a second apart, this is about
# fifteen seconds of patience.
_MAX_DROPPED_FRAMES = 30


def _warm_up(capture: Any) -> None:
    """Reads and discards frames until the camera is actually producing an image.

    Without this the detector spends its first seconds looking at black frames. It finds
    nothing there, which is correct and useless — and on a camera that never wakes up it looks
    exactly like a camera pointed at an empty doorway, with nothing in the log to tell them
    apart.
    """
    import time

    deadline = time.monotonic() + _WARM_UP_SECONDS
    while time.monotonic() < deadline:
        ok, frame = capture.read()
        if ok and frame is not None and frame.mean() > _BLACK_FRAME:
            return
    logger.warning(
        "camera still dark after %.0fs — check the lens cover, or that the right --source is "
        "selected (0 and 1 are different cameras)",
        _WARM_UP_SECONDS,
    )


class CountDoorway(BaseSettings):
    """CLI settings (pydantic-settings instead of argparse — typed and validated)."""

    #  so booleans read as `--preview` and `--no-post` rather than
    # `--preview true`.  for the same reason: nobody types `--device_key`.
    model_config = SettingsConfigDict(
        cli_parse_args=True, cli_kebab_case=True, cli_implicit_flags=True
    )

    # A camera index (`0`) or a path to a video file.
    source: str = "0"
    # The API root including its version prefix; ingest paths are appended to it.
    api_url: str = "http://localhost:8000/api/v1"
    # Required unless --no-post. Issued by `scripts/provision_device.py` in the backend.
    device_key: str = ""
    # Show the frame with detections, tracks and the line drawn on it. This is how you aim the
    # camera and check `--inside-sign`, and there is no way to get either right without seeing
    # a frame. Needs a display; press q to stop.
    preview: bool = False
    # Run the detector without sending anything. For trying the model out.
    post: bool = True
    # The tripwire across the doorway, in pixels: x1,y1,x2,y2. Empty means a horizontal line
    # across the middle of the frame, which is right for the usual mounting and wrong visibly.
    line: str = ""
    # Which side of the line is inside the vehicle: 1 or -1. Get this backwards and every
    # boarding is recorded as an alighting, so verify it once against a real run.
    inside_sign: int = 1
    door: str = "front"
    model_name: str = "PekingU/rtdetr_r18vd_coco_o365"
    threshold: float = 0.5
    torch_device: str = "cpu"
    # How often to deliver. Batching is what keeps a doorway from producing dozens of requests
    # per stop on a link that drops in tunnels.
    flush_seconds: float = 5.0
    # Process every Nth frame. Detection is the expensive step and a person takes most of a
    # second to cross, so a device without a GPU can skip frames and still see both sides of
    # the line.
    frame_stride: int = 2

    async def cli_cmd(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        # `transformers` and `httpx` log every HTTP request at INFO. On a first run that buries
        # the only lines that matter — the crossings — under model-download chatter.
        for noisy in ("httpx", "transformers", "urllib3", "filelock"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        if self.post and not self.device_key:
            raise SystemExit(
                "--device-key is required. Issue one with `scripts/provision_device.py` in the "
                "backend, or pass --no-post to run the detector without sending anything."
            )

        capture = self._capture()
        width = int(capture.get(3)) or 640
        height = int(capture.get(4)) or 480
        line = (
            _parse_line(self.line, self.inside_sign)
            if self.line
            else _default_line(width, height, self.inside_sign)
        )
        logger.info(
            "frame %dx%d, line (%.0f,%.0f)-(%.0f,%.0f), inside_sign=%d",
            width,
            height,
            line.x1,
            line.y1,
            line.x2,
            line.y2,
            self.inside_sign,
        )

        counter = DoorwayCounter(line=line, min_confidence=self.threshold)
        ingest = IngestClient(
            api_url=self.api_url,
            device_key=self.device_key,
            run_id=secrets.token_hex(3),
            door=self.door,
        )
        detector = self._detector()

        logger.info("counting %s%s", self.source, "" if self.post else " (not posting)")
        async with httpx.AsyncClient() as client:
            await self._loop(capture, detector, counter, ingest, client)

    async def _loop(
        self,
        capture: Any,
        detector: Any,
        counter: DoorwayCounter,
        ingest: IngestClient,
        client: httpx.AsyncClient,
    ) -> None:
        import cv2

        frame_index = 0
        last_flush = 0.0
        tally: Counter[str] = Counter()
        loop = asyncio.get_running_loop()

        # A file ends; a camera hiccups. Treating both the same way meant one dropped frame
        # from a wireless camera ended the run — a counter in a vehicle would stop at the
        # first tunnel and report nothing for the rest of the service.
        live = not isinstance(self.source, str) or self.source.isdigit() or "://" in self.source
        misses = 0

        while True:
            ok, frame = await asyncio.to_thread(capture.read)
            if not ok:
                if not live:
                    break
                misses += 1
                if misses > _MAX_DROPPED_FRAMES:
                    logger.error(
                        "camera stopped delivering frames (%d in a row) — giving up",
                        misses,
                    )
                    break
                logger.warning("dropped frame %d/%d, retrying", misses, _MAX_DROPPED_FRAMES)
                await asyncio.sleep(0.5)
                continue
            misses = 0
            frame_index += 1
            if frame_index % self.frame_stride:
                continue

            # Detection is CPU- or GPU-bound and blocking. Off the event loop, or the flush
            # below never gets a turn.
            detections = await asyncio.to_thread(
                detector.detect, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            )
            for crossing in counter.update(detections):
                logger.info("%s (track %d)", crossing.direction, crossing.track_id)
                tally[crossing.direction] += 1
                if self.post:
                    ingest.record(crossing)

            if self.preview and not _draw(frame, counter, detections, tally):
                break

            now = loop.time()
            if self.post and now - last_flush >= self.flush_seconds and ingest.pending:
                await ingest.flush(client, self._position())
                last_flush = now

        # Whatever is left when the stream ends. A video file that finished must not take its
        # last stop's passengers with it.
        if self.post:
            await ingest.flush(client, self._position())
        capture.release()
        if self.preview:
            cv2.destroyAllWindows()
        logger.info("done: %d boarding, %d alighting", tally["boarding"], tally["alighting"])

    def _position(self) -> Position | None:
        """No GPS on this device yet.

        Left explicit rather than omitted: position comes either from a receiver on the counter
        or from the operator's own vehicle-location feed matched by side number, and which one
        is a deployment decision, not a default.
        """
        return None

    def _detector(self) -> Any:
        from counter.adapters.rtdetr import RtDetrDetector

        return RtDetrDetector(
            model_name=self.model_name, threshold=self.threshold, device=self.torch_device
        )

    def _capture(self) -> Any:
        try:
            import cv2
        except ImportError as error:  # pragma: no cover - depends on the optional extra
            raise SystemExit(
                "Reading a camera needs the machine-learning extra: `uv sync --extra ml`."
            ) from error

        source: int | str = int(self.source) if self.source.isdigit() else self.source
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise SystemExit(f"Could not open video source: {self.source}")
        if isinstance(source, int):
            _warm_up(capture)
        return capture


def main() -> None:
    CliApp.run(CountDoorway)


if __name__ == "__main__":
    main()

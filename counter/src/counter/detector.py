"""The detector port: what the counting pipeline needs from a model, and nothing more.

A Protocol rather than a base class, and one method rather than a framework. Everything above
this line — tracking, crossing, batching, ingest — is testable with a list of boxes, so the
model can be swapped, mocked, or absent entirely.
"""

from typing import Protocol, runtime_checkable

from counter.domain import Detection


@runtime_checkable
class PersonDetector(Protocol):
    """Finds people in one frame.

    `frame` is an HxWx3 array of uint8 in RGB order. Typed loosely on purpose: the pipeline
    never looks inside it, and pinning it to `numpy.ndarray` would drag numpy into a package
    whose whole point is that it installs without the machine-learning stack.
    """

    def detect(self, frame: object) -> list[Detection]: ...

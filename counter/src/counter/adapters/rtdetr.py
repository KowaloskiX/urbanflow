"""RT-DETR from Hugging Face — the default detector.

**Why not YOLO.** Ultralytics YOLO (v8, v11 and the v10 fork) is licensed **AGPL-3.0**. Running
it inside a product means either publishing that product's source or buying a commercial
licence, and the obligation reaches a server you merely operate. RT-DETR is Apache-2.0, from
the same COCO person class, at comparable accuracy and speed. Picking it costs nothing and
removes the question entirely.

**Why COCO out of the box is a starting point, not the finished thing.** COCO people are
photographed from the front, at eye level. A doorway camera looks down at heads and shoulders,
which is out of distribution — expect it to work adequately and to miss in exactly the
conditions that matter, meaning a packed doorway. The fix is fine-tuning on footage from the
actual mounting position, and the seam for it is this file: a fine-tuned checkpoint is a
different `model_name`, nothing else changes.

Requires the `ml` extra: `uv sync --extra ml`.
"""

from dataclasses import dataclass, field
from typing import Any

from counter.domain import Box, Detection

# The COCO class this model was trained on. Everything else in the frame — bags, seats,
# bicycles — is discarded.
_PERSON_LABEL = "person"
_DEFAULT_MODEL = "PekingU/rtdetr_r18vd_coco_o365"


@dataclass
class RtDetrDetector:
    """A person detector backed by `transformers`.

    Loading is lazy: constructing this class must not pull several hundred megabytes of weights
    onto a device that is only being configured.
    """

    model_name: str = _DEFAULT_MODEL
    # Detections below this never reach the tracker. A false positive that crosses the line is
    # a phantom passenger, and the server's accumulator keeps it until the next anchor.
    threshold: float = 0.5
    device: str = "cpu"

    _model: Any = field(default=None, init=False, repr=False)
    _processor: Any = field(default=None, init=False, repr=False)

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import AutoImageProcessor, AutoModelForObjectDetection
        except ImportError as error:  # pragma: no cover - depends on the optional extra
            raise RuntimeError(
                "The detector needs the machine-learning extra: `uv sync --extra ml`."
            ) from error

        self._processor = AutoImageProcessor.from_pretrained(self.model_name)
        self._model = AutoModelForObjectDetection.from_pretrained(self.model_name).to(self.device)
        self._model.eval()

    def detect(self, frame: object) -> list[Detection]:
        import torch

        self._load()
        assert self._processor is not None and self._model is not None

        inputs = self._processor(images=frame, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self._model(**inputs)

        height, width = _frame_size(frame)
        results = self._processor.post_process_object_detection(
            outputs, target_sizes=[(height, width)], threshold=self.threshold
        )[0]

        labels = self._model.config.id2label
        return [
            Detection(
                box=Box(float(box[0]), float(box[1]), float(box[2]), float(box[3])),
                confidence=float(score),
            )
            for score, label, box in zip(
                results["scores"], results["labels"], results["boxes"], strict=True
            )
            if labels[int(label)] == _PERSON_LABEL
        ]


def _frame_size(frame: Any) -> tuple[int, int]:
    """Height and width, whether the frame is an array or a PIL image."""
    shape = getattr(frame, "shape", None)
    if shape is not None:
        return int(shape[0]), int(shape[1])
    return int(frame.height), int(frame.width)

"""Task and result messages exchanged between the coordinator and a worker.

Field names and rules mirror the coordinator's TCP v1 contract
(scheduling-simulation/README.md on the mohamed/python-coordinator branch):
the coordinator sends a JSON header plus raw image bytes, and the worker
replies with a JSON result containing person boxes in original-image pixels.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

PERSON = "person"
SUCCESS = "success"
FAILURE = "failure"


@dataclass(frozen=True)
class Detection:
    """One person box in original-image pixels, origin top-left, (x1, y1, x2, y2)."""

    box_xyxy: tuple[float, float, float, float]
    confidence: float
    label: str = PERSON

    def __post_init__(self):
        box = tuple(float(v) for v in self.box_xyxy)
        object.__setattr__(self, "box_xyxy", box)
        object.__setattr__(self, "confidence", float(self.confidence))
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ValueError(f"box must be 4 finite numbers, got {self.box_xyxy}")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 and 0 <= y1 < y2):
            raise ValueError(f"box must satisfy 0 <= x1 < x2 and 0 <= y1 < y2, got {box}")
        if not (math.isfinite(self.confidence) and 0 <= self.confidence <= 1):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")
        if self.label != PERSON:
            raise ValueError(f"only '{PERSON}' detections are allowed, got {self.label!r}")

    def to_dict(self) -> dict:
        return {"label": self.label, "confidence": self.confidence, "box_xyxy": list(self.box_xyxy)}


@dataclass(frozen=True)
class DetectionTask:
    """One image to process, as received from the coordinator."""

    task_id: int
    attempt_id: int
    image_id: str
    image: bytes
    sha256: str

    @classmethod
    def from_wire(cls, header: dict, payload: bytes) -> DetectionTask:
        """Build a task from a decoded TCP frame, rejecting corrupted images."""
        if header.get("type") != "task":
            raise ValueError(f"expected a task message, got {header.get('type')!r}")
        task = cls(task_id=header["task_id"], attempt_id=header["attempt_id"],
                   image_id=header["image_id"], image=payload, sha256=header["sha256"])
        if hashlib.sha256(payload).hexdigest() != task.sha256:
            raise ValueError(f"checksum mismatch for image {task.image_id!r}")
        return task


@dataclass(frozen=True)
class DetectionResult:
    """The worker's answer for one task. Empty detections is a successful no-person result."""

    task_id: int
    attempt_id: int
    image_id: str
    status: str
    processing_ms: float
    detector: str
    detections: list[Detection] = field(default_factory=list)
    image_size: tuple[int, int] | None = None  # (width, height) of the original image
    error: str | None = None

    def __post_init__(self):
        if self.status not in (SUCCESS, FAILURE):
            raise ValueError(f"status must be '{SUCCESS}' or '{FAILURE}', got {self.status!r}")
        if not (math.isfinite(self.processing_ms) and self.processing_ms >= 0):
            raise ValueError(f"processing_ms must be a nonnegative number, got {self.processing_ms}")
        if self.image_size is not None:
            width, height = self.image_size
            for d in self.detections:
                if d.box_xyxy[2] > width or d.box_xyxy[3] > height:
                    raise ValueError(f"box {d.box_xyxy} lies outside the {width}x{height} image")

    @classmethod
    def success(cls, task: DetectionTask, detections: list[Detection], processing_ms: float,
                detector: str, image_size: tuple[int, int]) -> DetectionResult:
        return cls(task.task_id, task.attempt_id, task.image_id, SUCCESS, processing_ms,
                   detector, list(detections), image_size)

    @classmethod
    def failure(cls, task: DetectionTask, error: str, processing_ms: float,
                detector: str) -> DetectionResult:
        return cls(task.task_id, task.attempt_id, task.image_id, FAILURE, processing_ms,
                   detector, error=error)

    def to_wire(self) -> dict:
        """JSON header for the result frame (the coordinator adds payload_bytes on send)."""
        message = {"type": "result", "task_id": self.task_id, "attempt_id": self.attempt_id,
                   "image_id": self.image_id, "status": self.status,
                   "processing_ms": self.processing_ms, "detector": self.detector,
                   "synthetic": False, "detections": [d.to_dict() for d in self.detections]}
        if self.image_size is not None:
            message["image_size"] = {"width": self.image_size[0], "height": self.image_size[1]}
        if self.error is not None:
            message["error"] = self.error
        return message

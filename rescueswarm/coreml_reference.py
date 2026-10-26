"""Reference pre- and post-processing for the Core ML export of YOLO26n (nms=True).

The exported model takes a fixed square RGB image and returns final boxes, so the app has to:
  1. letterbox the photo: shrink it to fit the square, keep the aspect ratio, pad with gray;
  2. keep the "person" rows of the model output;
  3. map the boxes from the square back to the original photo's pixels.
This module is the tested recipe for those steps; the Swift detector must do the same.

Model outputs (one row per box after the model's own NMS):
  coordinates: (N, 4) center x, center y, width, height as fractions of the square input
  confidence:  (N, 80) score per COCO class; column 0 is "person"
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from rescueswarm.detector import COCO_PERSON
from rescueswarm.messages import Detection

PAD_VALUE = 114  # gray used by Ultralytics for letterbox padding


@dataclass(frozen=True)
class Letterbox:
    """Where an original width x height photo sits inside the size x size model input."""

    scale: float  # input pixels per original pixel
    left: int     # padding columns on the left
    top: int      # padding rows on top
    resized_width: int
    resized_height: int
    size: int

    @classmethod
    def fit(cls, width: int, height: int, size: int) -> Letterbox:
        scale = min(size / width, size / height)
        resized_width, resized_height = round(width * scale), round(height * scale)
        return cls(scale, (size - resized_width) // 2, (size - resized_height) // 2,
                   resized_width, resized_height, size)

    def to_original(self, x: float, y: float) -> tuple[float, float]:
        """Model-input pixel -> original-photo pixel."""
        return (x - self.left) / self.scale, (y - self.top) / self.scale


def letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, Letterbox]:
    """Shrink a BGR image to fit a size x size square, centered, with gray padding."""
    height, width = image.shape[:2]
    box = Letterbox.fit(width, height, size)
    resized = cv2.resize(image, (box.resized_width, box.resized_height), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), PAD_VALUE, np.uint8)
    canvas[box.top:box.top + box.resized_height, box.left:box.left + box.resized_width] = resized
    return canvas, box


def decode(coordinates: np.ndarray, confidence: np.ndarray, box: Letterbox,
           original_width: int, original_height: int, conf: float) -> list[Detection]:
    """Turn the model's outputs into person detections in original-photo pixels."""
    detections = []
    for (cx, cy, w, h), scores in zip(np.asarray(coordinates).reshape(-1, 4), np.asarray(confidence)):
        if int(np.argmax(scores)) != COCO_PERSON or scores[COCO_PERSON] < conf:
            continue
        x1, y1 = box.to_original((cx - w / 2) * box.size, (cy - h / 2) * box.size)
        x2, y2 = box.to_original((cx + w / 2) * box.size, (cy + h / 2) * box.size)
        # Clip to the photo: a box can reach into the padding.
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(float(original_width), x2), min(float(original_height), y2)
        if x1 < x2 and y1 < y2:
            detections.append(Detection((x1, y1, x2, y2), float(scores[COCO_PERSON])))
    return detections

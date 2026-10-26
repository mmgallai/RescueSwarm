"""Person detection with a pretrained Ultralytics YOLO model (YOLO26n by default)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rescueswarm.messages import Detection

COCO_PERSON = 0  # class index of "person" in the COCO classes YOLO is pretrained on

# YOLO's usual 640 shrinks a 5472-px drone photo 8.5x, leaving people a few pixels tall.
# All 227 SAR-DAG images at conf 0.25 (scripts/evaluate.py; ms = decode + detect on a Mac):
#   640: precision 0.81, recall 0.22,  73 ms    1280: 0.88, 0.55, 112 ms    1920: 0.93, 0.61, 182 ms
# 1280 more than doubles recall over 640; 1920 adds a little more for ~60% extra time.
DEFAULT_IMGSZ = 1280


@dataclass(frozen=True)
class DetectorOutput:
    detections: list[Detection]
    inference_ms: float  # preprocessing + model + postprocessing for this one image


class PersonDetector:
    """Finds people in a BGR image and returns boxes in that image's own pixel coordinates.

    Ultralytics resizes and pads the image to `imgsz` internally and maps boxes back to the
    original size, so callers never see resized coordinates.
    """

    def __init__(self, weights: str | Path = "yolo26n.pt", imgsz: int = DEFAULT_IMGSZ, conf: float = 0.25,
                 device: str | None = None, model=None):
        if model is None:
            from ultralytics import YOLO  # imported lazily: it is slow and pulls in PyTorch
            model = YOLO(str(weights))
        self.model = model
        self.name = Path(str(weights)).stem
        self.imgsz = imgsz
        self.conf = conf
        self.device = device

    @property
    def config(self) -> dict:
        """Settings that change the results, reported alongside them."""
        return {"model": self.name, "imgsz": self.imgsz, "conf": self.conf}

    def warmup(self) -> None:
        """Run once on a blank image so model loading isn't counted in the first real timing."""
        self.detect(np.zeros((self.imgsz, self.imgsz, 3), np.uint8))

    def detect(self, image: np.ndarray) -> DetectorOutput:
        height, width = image.shape[:2]
        started = time.perf_counter()
        result = self.model.predict(image, imgsz=self.imgsz, conf=self.conf, classes=[COCO_PERSON],
                                    device=self.device, verbose=False)[0]
        inference_ms = (time.perf_counter() - started) * 1000

        detections = []
        boxes = result.boxes
        for (x1, y1, x2, y2), confidence, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(),
                                                     boxes.cls.tolist()):
            if int(cls) != COCO_PERSON:
                continue
            # Clip to the image: the model can predict slightly past the edges.
            x1, x2 = max(0.0, x1), min(float(width), x2)
            y1, y2 = max(0.0, y1), min(float(height), y2)
            if x1 < x2 and y1 < y2:
                detections.append(Detection((x1, y1, x2, y2), confidence))
        return DetectorOutput(detections, inference_ms)

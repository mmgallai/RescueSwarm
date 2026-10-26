"""Turns a coordinator task into a result: decode the image, detect people, report timing.

This is transport-free on purpose: the TCP connection to the coordinator only has to call
Worker.handle() for each task it receives and send back result.to_wire().
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from rescueswarm.detector import PersonDetector
from rescueswarm.messages import DetectionResult, DetectionTask


def decode_image(data: bytes) -> np.ndarray:
    """JPEG/PNG/PPM bytes -> BGR pixel array, upright according to the EXIF orientation."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"could not decode image ({len(data)} bytes)")
    return image


class Worker:
    def __init__(self, detector: PersonDetector):
        self.detector = detector

    def handle(self, task: DetectionTask) -> DetectionResult:
        """Process one task. Never raises: any problem becomes a failure result for the coordinator."""
        started = time.perf_counter()
        try:
            image = decode_image(task.image)
            output = self.detector.detect(image)
            height, width = image.shape[:2]
            return DetectionResult.success(task, output.detections, elapsed_ms(started),
                                           self.detector.name, (width, height), self.detector.config)
        except Exception as exc:  # one bad image must not take the worker down
            return DetectionResult.failure(task, f"{type(exc).__name__}: {exc}", elapsed_ms(started),
                                           self.detector.name, self.detector.config)


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000

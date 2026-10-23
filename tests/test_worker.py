import hashlib

import cv2
import numpy as np
import pytest

from rescueswarm.detector import DetectorOutput
from rescueswarm.messages import Detection, DetectionTask
from rescueswarm.worker import Worker, decode_image


class FakeDetector:
    """Stands in for PersonDetector: returns fixed detections and records what it was given."""

    name = "fake"
    config = {"model": "fake", "imgsz": 1280, "conf": 0.25}

    def __init__(self, detections=(), error=None):
        self.detections, self.error, self.images = list(detections), error, []

    def detect(self, image):
        self.images.append(image)
        if self.error:
            raise self.error
        return DetectorOutput(self.detections, inference_ms=5.0)


def make_task(image_bytes: bytes) -> DetectionTask:
    return DetectionTask(task_id=7, attempt_id=2, image_id="polje/DJI_0001.JPG", image=image_bytes,
                         sha256=hashlib.sha256(image_bytes).hexdigest())


def jpeg(width=640, height=480) -> bytes:
    ok, data = cv2.imencode(".jpg", np.full((height, width, 3), 120, np.uint8))
    assert ok
    return data.tobytes()


def test_decode_image_returns_bgr_pixels():
    assert decode_image(jpeg(640, 480)).shape == (480, 640, 3)


def test_decode_image_rejects_garbage():
    with pytest.raises(ValueError, match="could not decode"):
        decode_image(b"not an image")


def test_success_result_carries_detections_size_and_config():
    detector = FakeDetector([Detection((10, 20, 50, 120), 0.8)])
    result = Worker(detector).handle(make_task(jpeg(640, 480)))

    assert result.status == "success"
    assert (result.task_id, result.attempt_id, result.image_id) == (7, 2, "polje/DJI_0001.JPG")
    assert result.detections == [Detection((10, 20, 50, 120), 0.8)]
    assert result.image_size == (640, 480)
    assert result.detector == "fake"
    assert result.to_wire()["detector_config"] == {"model": "fake", "imgsz": 1280, "conf": 0.25}
    assert detector.images[0].shape == (480, 640, 3)  # the detector got the decoded image


def test_processing_time_covers_decoding_and_detection():
    result = Worker(FakeDetector()).handle(make_task(jpeg()))
    assert result.processing_ms > 0


def test_no_people_is_a_success():
    result = Worker(FakeDetector()).handle(make_task(jpeg()))
    assert result.status == "success" and result.detections == []


def test_undecodable_image_becomes_failure_result():
    detector = FakeDetector()
    result = Worker(detector).handle(make_task(b"\xff\xd8 truncated jpeg"))
    assert result.status == "failure"
    assert "could not decode" in result.error
    assert detector.images == []  # the detector never ran


def test_detector_crash_becomes_failure_result():
    result = Worker(FakeDetector(error=RuntimeError("model exploded"))).handle(make_task(jpeg()))
    assert result.status == "failure"
    assert result.error == "RuntimeError: model exploded"
    assert result.to_wire()["status"] == "failure"

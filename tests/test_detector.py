from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rescueswarm.dataset import DEFAULT_ROOT, load_flight
from rescueswarm.detector import PersonDetector


class FakeModel:
    """Stands in for an Ultralytics YOLO model, returning fixed boxes."""

    def __init__(self, xyxy, conf, cls):
        self.boxes = SimpleNamespace(xyxy=np.array(xyxy, float).reshape(-1, 4),
                                     conf=np.array(conf, float), cls=np.array(cls, float))
        self.calls = []

    def predict(self, image, **kwargs):
        self.calls.append(kwargs)
        return [SimpleNamespace(boxes=self.boxes)]


def test_returns_person_boxes_and_timing():
    model = FakeModel([[10, 20, 50, 120]], [0.8], [0])
    out = PersonDetector(model=model).detect(np.zeros((480, 640, 3), np.uint8))
    assert [(d.box_xyxy, d.confidence) for d in out.detections] == [((10, 20, 50, 120), 0.8)]
    assert out.inference_ms >= 0


def test_asks_model_for_people_only_at_configured_size():
    model = FakeModel([], [], [])
    PersonDetector(imgsz=1280, conf=0.3, model=model).detect(np.zeros((10, 10, 3), np.uint8))
    assert model.calls[0]["classes"] == [0]
    assert (model.calls[0]["imgsz"], model.calls[0]["conf"]) == (1280, 0.3)


def test_drops_non_person_classes():
    model = FakeModel([[0, 0, 10, 10], [5, 5, 20, 20]], [0.9, 0.7], [2, 0])  # a car, then a person
    out = PersonDetector(model=model).detect(np.zeros((100, 100, 3), np.uint8))
    assert [d.box_xyxy for d in out.detections] == [(5, 5, 20, 20)]


def test_clips_boxes_to_image_and_drops_boxes_entirely_outside():
    model = FakeModel([[-5, -3, 30, 40], [90, 10, 110, 50], [100, 0, 120, 10]], [0.9, 0.8, 0.7], [0, 0, 0])
    out = PersonDetector(model=model).detect(np.zeros((60, 100, 3), np.uint8))
    assert [d.box_xyxy for d in out.detections] == [(0, 0, 30, 40), (90, 10, 100, 50)]


def test_empty_result_is_fine():
    out = PersonDetector(model=FakeModel([], [], [])).detect(np.zeros((10, 10, 3), np.uint8))
    assert out.detections == []


def test_config_describes_settings():
    det = PersonDetector("models/yolo26n.pt", imgsz=1280, conf=0.25, model=FakeModel([], [], []))
    assert det.config == {"model": "yolo26n", "imgsz": 1280, "conf": 0.25}


# --- Real model on real data (skipped when the dataset or weights are unavailable) ---

WEIGHTS = Path(__file__).resolve().parent.parent / "yolo26n.pt"
needs_real = pytest.mark.skipif(not (DEFAULT_ROOT.exists() and WEIGHTS.exists()),
                                reason="needs SAR-DAG and yolo26n.pt in the repo root")


def iou(a, b):
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


@needs_real
def test_real_boxes_are_in_original_image_coordinates():
    import cv2
    frame = next(f for f in load_flight("vinograd2") if f.image_id == "vinograd2/DJI_0086.JPG")
    image = cv2.imread(str(frame.image_path))
    detector = PersonDetector(WEIGHTS)

    full = detector.detect(image).detections
    assert max(iou(d.box_xyxy, frame.gt_boxes[0]) for d in full) > 0.5

    # The same person in a crop must come back shifted by exactly the crop offset.
    left, top = 2800, 1300
    crop = detector.detect(np.ascontiguousarray(image[top:top + 1000, left:left + 1000])).detections
    shifted = [(x1 + left, y1 + top, x2 + left, y2 + top) for x1, y1, x2, y2 in (d.box_xyxy for d in crop)]
    assert max(iou(b, frame.gt_boxes[0]) for b in shifted) > 0.5

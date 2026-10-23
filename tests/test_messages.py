import hashlib
import json

import pytest

from rescueswarm.messages import Detection, DetectionResult, DetectionTask

IMAGE = b"fake image bytes"


def task_header(**overrides):
    header = {"type": "task", "task_id": 3, "attempt_id": 1, "image_id": "frame-0003.jpg",
              "sha256": hashlib.sha256(IMAGE).hexdigest(), "payload_bytes": len(IMAGE)}
    return {**header, **overrides}


def test_task_from_wire_reads_ids_and_image():
    task = DetectionTask.from_wire(task_header(), IMAGE)
    assert (task.task_id, task.attempt_id, task.image_id) == (3, 1, "frame-0003.jpg")
    assert task.image == IMAGE


def test_task_from_wire_rejects_corrupted_image():
    with pytest.raises(ValueError, match="checksum"):
        DetectionTask.from_wire(task_header(), IMAGE + b"!")


def test_task_from_wire_rejects_other_message_types():
    with pytest.raises(ValueError, match="task message"):
        DetectionTask.from_wire(task_header(type="heartbeat"), IMAGE)


@pytest.mark.parametrize("box, confidence", [
    ((10, 10, 5, 20), 0.5),                 # x2 < x1
    ((10, 10, 20, 10), 0.5),                # zero height
    ((-1, 0, 5, 5), 0.5),                   # negative coordinate
    ((0, 0, float("nan"), 5), 0.5),         # not finite
    ((0, 0, 5, 5), 1.5),                    # confidence out of range
    ((0, 0, 5), 0.5),                       # wrong number of values
])
def test_detection_rejects_invalid_boxes(box, confidence):
    with pytest.raises(ValueError):
        Detection(box, confidence)


def test_detection_rejects_non_person_label():
    with pytest.raises(ValueError, match="person"):
        Detection((0, 0, 5, 5), 0.5, label="car")


def test_result_rejects_box_outside_image():
    task = DetectionTask.from_wire(task_header(), IMAGE)
    with pytest.raises(ValueError, match="outside"):
        DetectionResult.success(task, [Detection((0, 0, 650, 10), 0.9)], 12.0, "yolo26n", (640, 480))


def test_success_result_matches_coordinator_wire_format():
    task = DetectionTask.from_wire(task_header(), IMAGE)
    result = DetectionResult.success(task, [Detection((1, 2, 30, 40), 0.87)], 12.5, "yolo26n", (640, 480))
    wire = json.loads(json.dumps(result.to_wire()))  # must survive a JSON round trip
    assert wire == {
        "type": "result", "task_id": 3, "attempt_id": 1, "image_id": "frame-0003.jpg",
        "status": "success", "processing_ms": 12.5, "detector": "yolo26n", "synthetic": False,
        "detections": [{"label": "person", "confidence": 0.87, "box_xyxy": [1.0, 2.0, 30.0, 40.0]}],
        "image_size": {"width": 640, "height": 480},
    }


def test_empty_detections_is_a_success():
    task = DetectionTask.from_wire(task_header(), IMAGE)
    wire = DetectionResult.success(task, [], 8.0, "yolo26n", (640, 480)).to_wire()
    assert wire["status"] == "success" and wire["detections"] == []


def test_failure_result_carries_error():
    task = DetectionTask.from_wire(task_header(), IMAGE)
    wire = DetectionResult.failure(task, "could not decode image", 1.0, "yolo26n").to_wire()
    assert wire["status"] == "failure"
    assert wire["error"] == "could not decode image"
    assert wire["detections"] == [] and "image_size" not in wire

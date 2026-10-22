import hashlib
from datetime import datetime

import cv2
import numpy as np
import pytest

from rescueswarm.dataset import Frame, Telemetry
from rescueswarm.detector import DetectorOutput
from rescueswarm.messages import Detection
from rescueswarm.runner import make_task, summarize, timed_run
from rescueswarm.worker import Worker

TELEMETRY = Telemetry(datetime(2022, 1, 14), 45.4, 16.7, 0, 30, 0, 0, 0, -90, 0, 0, 84, 8.8, "P4", "FC6310")


class FakeDetector:
    name, config = "fake", {"model": "fake"}

    def detect(self, image):
        return DetectorOutput([Detection((1, 1, 5, 5), 0.9)] if image.mean() > 100 else [], 1.0)


def write_frame(tmp_path, name, content: bytes) -> Frame:
    path = tmp_path / name
    path.write_bytes(content)
    return Frame("f", f"f/{name}", path, 64, 48, (), TELEMETRY)


def jpeg(brightness: int) -> bytes:
    return cv2.imencode(".jpg", np.full((48, 64, 3), brightness, np.uint8))[1].tobytes()


def test_task_is_built_like_the_coordinator_builds_it(tmp_path):
    frame = write_frame(tmp_path, "a.jpg", jpeg(200))
    task = make_task(frame, task_id=4)
    assert (task.task_id, task.attempt_id, task.image_id) == (4, 1, "f/a.jpg")
    assert task.image == frame.image_path.read_bytes()
    assert task.sha256 == hashlib.sha256(task.image).hexdigest()


def test_timed_run_processes_every_frame_in_order(tmp_path):
    frames = [write_frame(tmp_path, "bright.jpg", jpeg(200)), write_frame(tmp_path, "dark.jpg", jpeg(10)),
              write_frame(tmp_path, "broken.jpg", b"not an image")]
    seen = []
    results, summary = timed_run(frames, Worker(FakeDetector()), on_result=lambda f, r: seen.append(f.image_id))

    assert seen == ["f/bright.jpg", "f/dark.jpg", "f/broken.jpg"]
    assert [r.task_id for r in results] == [0, 1, 2]
    assert [r.status for r in results] == ["success", "success", "failure"]
    assert (summary.tasks, summary.succeeded, summary.failed) == (3, 2, 1)
    assert (summary.images_with_detections, summary.detections) == (1, 1)


def test_summary_timing_statistics():
    from rescueswarm.messages import DetectionResult
    results = [DetectionResult(i, 1, str(i), "success", ms, "fake") for i, ms in enumerate([10, 20, 30, 40])]
    summary = summarize(results, wall_s=2.0)
    assert (summary.mean_ms, summary.median_ms) == (25, 25)
    assert summary.p95_ms == pytest.approx(38.5)
    assert summary.images_per_s == 2.0


def test_summary_of_nothing_does_not_crash():
    assert summarize([], wall_s=0).tasks == 0

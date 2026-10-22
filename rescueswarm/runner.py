"""Run dataset frames through a Worker in-process, standing in for the coordinator.

Tasks are built exactly as the coordinator builds them (raw file bytes + SHA-256), so the
worker takes the same path it will over TCP; only the network is missing.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import numpy as np

from rescueswarm.dataset import Frame
from rescueswarm.messages import SUCCESS, DetectionResult, DetectionTask
from rescueswarm.worker import Worker


def make_task(frame: Frame, task_id: int, attempt_id: int = 1) -> DetectionTask:
    data = frame.image_path.read_bytes()
    return DetectionTask(task_id, attempt_id, frame.image_id, data, hashlib.sha256(data).hexdigest())


def run_frames(frames: Iterable[Frame], worker: Worker) -> Iterator[tuple[Frame, DetectionResult]]:
    """Process frames one at a time, yielding each result as soon as it is ready."""
    for task_id, frame in enumerate(frames):
        yield frame, worker.handle(make_task(frame, task_id))


@dataclass(frozen=True)
class RunSummary:
    tasks: int
    succeeded: int
    failed: int
    images_with_detections: int
    detections: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    wall_s: float

    @property
    def images_per_s(self) -> float:
        return self.tasks / self.wall_s if self.wall_s else 0.0


def summarize(results: list[DetectionResult], wall_s: float) -> RunSummary:
    times = np.array([r.processing_ms for r in results]) if results else np.zeros(1)
    ok = [r for r in results if r.status == SUCCESS]
    return RunSummary(
        tasks=len(results),
        succeeded=len(ok),
        failed=len(results) - len(ok),
        images_with_detections=sum(bool(r.detections) for r in ok),
        detections=sum(len(r.detections) for r in ok),
        mean_ms=float(times.mean()),
        median_ms=float(np.median(times)),
        p95_ms=float(np.percentile(times, 95)),
        wall_s=wall_s,
    )


def timed_run(frames: Iterable[Frame], worker: Worker, on_result=None) -> tuple[list[DetectionResult], RunSummary]:
    """Run all frames, calling on_result(frame, result) after each one, and summarize."""
    started = time.perf_counter()
    results = []
    for frame, result in run_frames(frames, worker):
        results.append(result)
        if on_result:
            on_result(frame, result)
    return results, summarize(results, time.perf_counter() - started)

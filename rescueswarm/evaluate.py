"""Score detections against SAR-DAG ground truth: precision, recall and F1.

A detection is a true positive when it overlaps a not-yet-matched ground-truth box with
IoU >= the threshold; detections are matched highest-confidence first, so a duplicate box
on an already-found person counts as a false positive.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rescueswarm.dataset import Box, Frame
from rescueswarm.messages import SUCCESS, DetectionResult


def iou(a: Box, b: Box) -> float:
    """Intersection over union of two xyxy boxes: 0 = no overlap, 1 = identical."""
    width = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


@dataclass(frozen=True)
class Counts:
    tp: int = 0  # correct detections
    fp: int = 0  # false alarms
    fn: int = 0  # missed people

    def __add__(self, other: Counts) -> Counts:
        return Counts(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)

    @property
    def precision(self) -> float:
        """Share of detections that were real people (0 when nothing was detected)."""
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        """Share of real people that were found (0 when there were none)."""
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def match_frame(gt_boxes: Iterable[Box], detections: Iterable[tuple[Box, float]],
                iou_threshold: float = 0.5) -> Counts:
    """Counts for one image, given its ground truth and (box, confidence) detections."""
    unmatched = list(gt_boxes)
    tp = fp = 0
    for box, _ in sorted(detections, key=lambda d: d[1], reverse=True):
        best = max(unmatched, key=lambda gt: iou(box, gt), default=None)
        if best is not None and iou(box, best) >= iou_threshold:
            unmatched.remove(best)
            tp += 1
        else:
            fp += 1
    return Counts(tp, fp, len(unmatched))


def evaluate(pairs: Iterable[tuple[Frame, DetectionResult]], conf_threshold: float = 0.0,
             iou_threshold: float = 0.5) -> Counts:
    """Total counts over many images, ignoring detections below conf_threshold.

    A failed result found nobody, so all of that image's people count as missed.
    """
    total = Counts()
    for frame, result in pairs:
        detections = [(d.box_xyxy, d.confidence) for d in result.detections
                      if result.status == SUCCESS and d.confidence >= conf_threshold]
        total += match_frame(frame.gt_boxes, detections, iou_threshold)
    return total

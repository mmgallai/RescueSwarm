from datetime import datetime
from pathlib import Path

import pytest

from rescueswarm.dataset import Frame, Telemetry
from rescueswarm.evaluate import Counts, evaluate, iou, match_frame
from rescueswarm.messages import Detection, DetectionResult

PERSON = (100, 100, 120, 160)
TELEMETRY = Telemetry(datetime(2022, 1, 14), 45.4, 16.7, 0, 30, 0, 0, 0, -90, 0, 0, 84, 8.8, "P4", "FC6310")


def test_iou():
    assert iou(PERSON, PERSON) == 1
    assert iou(PERSON, (200, 200, 220, 260)) == 0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)


def test_exact_hit_is_a_true_positive():
    assert match_frame([PERSON], [(PERSON, 0.9)]) == Counts(tp=1)


def test_missed_person_is_a_false_negative():
    assert match_frame([PERSON], []) == Counts(fn=1)


def test_detection_on_empty_image_is_a_false_positive():
    assert match_frame([], [(PERSON, 0.9)]) == Counts(fp=1)


def test_box_in_the_wrong_place_is_both_a_miss_and_a_false_alarm():
    assert match_frame([PERSON], [((300, 300, 320, 360), 0.9)]) == Counts(fp=1, fn=1)


def test_duplicate_box_counts_once_and_the_more_confident_one_wins():
    shifted = (101, 101, 121, 161)
    assert match_frame([PERSON], [(shifted, 0.5), (PERSON, 0.9)]) == Counts(tp=1, fp=1)


def test_precision_recall_f1():
    c = Counts(tp=6, fp=2, fn=4)
    assert (c.precision, c.recall) == (0.75, 0.6)
    assert c.f1 == pytest.approx(2 * 0.75 * 0.6 / 1.35)
    assert Counts().precision == Counts().recall == Counts().f1 == 0


def frame(gt):
    return Frame("f", "f/a.jpg", Path("a.jpg"), 640, 480, gt, TELEMETRY)


def result(detections, status="success"):
    return DetectionResult(0, 1, "f/a.jpg", status, 1.0, "fake", detections)


def test_evaluate_applies_confidence_threshold():
    pairs = [(frame((PERSON,)), result([Detection(PERSON, 0.3)])),
             (frame(()), result([Detection(PERSON, 0.2)]))]
    assert evaluate(pairs, conf_threshold=0.1) == Counts(tp=1, fp=1)
    assert evaluate(pairs, conf_threshold=0.25) == Counts(tp=1)
    assert evaluate(pairs, conf_threshold=0.5) == Counts(fn=1)


def test_failed_result_misses_everyone_in_the_image():
    assert evaluate([(frame((PERSON,)), result([], status="failure"))]) == Counts(fn=1)

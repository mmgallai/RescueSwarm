"""Measure detector accuracy and speed on SAR-DAG for several input sizes and confidence thresholds.

The detector runs once per input size at the lowest threshold; higher thresholds are scored
by dropping the less confident detections, so the sweep costs no extra inference.

Accuracy is the same however sizes are combined, but ms/img is only trustworthy with one
--imgsz per run: on a Mac, sizes after the first in one process measured ~2-3x slower.

    python scripts/evaluate.py                         # imgsz 640 and 1280 on all 227 images
    python scripts/evaluate.py --imgsz 1280 1920 --conf 0.1 0.25 0.4
"""
from __future__ import annotations

import argparse

from rescueswarm.dataset import list_flights, load_dataset
from rescueswarm.detector import PersonDetector
from rescueswarm.evaluate import evaluate
from rescueswarm.runner import timed_run
from rescueswarm.worker import Worker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--imgsz", type=int, nargs="+", default=[640, 1280])
    parser.add_argument("--conf", type=float, nargs="+", default=[0.1, 0.25, 0.4])
    parser.add_argument("--iou", type=float, default=0.5, help="overlap needed to count as a match")
    parser.add_argument("--weights", default="yolo26n.pt")
    args = parser.parse_args()

    frames = load_dataset()
    people = sum(len(f.gt_boxes) for f in frames)
    print(f"{len(frames)} images, {people} people, {sum(not f.has_person for f in frames)} images without anyone\n")
    print(f"{'imgsz':>5} {'conf':>5} {'precision':>9} {'recall':>6} {'F1':>5} {'TP':>4} {'FP':>4} {'FN':>4} {'ms/img':>7}")

    for imgsz in args.imgsz:
        detector = PersonDetector(args.weights, imgsz=imgsz, conf=min(args.conf))
        detector.warmup()
        results, summary = timed_run(frames, Worker(detector))
        pairs = list(zip(frames, results))
        for conf in sorted(args.conf):
            c = evaluate(pairs, conf, args.iou)
            print(f"{imgsz:>5} {conf:>5.2f} {c.precision:>9.2f} {c.recall:>6.2f} {c.f1:>5.2f} "
                  f"{c.tp:>4} {c.fp:>4} {c.fn:>4} {summary.mean_ms:>7.0f}")

        conf = 0.25 if 0.25 in args.conf else min(args.conf)
        per_flight = ", ".join(
            f"{flight} {evaluate([p for p in pairs if p[0].flight == flight], conf, args.iou).recall:.2f}"
            for flight in list_flights())
        print(f"      recall per flight at conf {conf}: {per_flight}\n")


if __name__ == "__main__":
    main()

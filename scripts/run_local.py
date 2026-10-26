"""Run SAR-DAG images through one worker on this machine and report results and timing.

    python scripts/run_local.py --flight polje --limit 10
    python scripts/run_local.py --imgsz 640 --output runs/local/results.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rescueswarm.dataset import load_dataset
from rescueswarm.detector import DEFAULT_IMGSZ, PersonDetector
from rescueswarm.runner import timed_run
from rescueswarm.worker import Worker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flight", action="append", help="flight name (repeatable; default: all flights)")
    parser.add_argument("--limit", type=int, help="process at most this many images")
    parser.add_argument("--weights", default="yolo26n.pt")
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--output", type=Path, help="write each result's wire JSON to this JSONL file")
    args = parser.parse_args()

    frames = load_dataset(flights=args.flight)[:args.limit]
    detector = PersonDetector(args.weights, imgsz=args.imgsz, conf=args.conf)
    detector.warmup()  # keep model loading out of the timings
    print(f"Processing {len(frames)} images with {detector.config}")

    def show(frame, result):
        people = ", ".join(f"{d.confidence:.2f}" for d in result.detections) or "-"
        truth = "person" if frame.has_person else "empty"
        status = result.status if result.status == "success" else f"FAILED ({result.error})"
        print(f"{frame.image_id:32} {status:8} {result.processing_ms:6.0f} ms  truth={truth:6}  found: {people}")

    results, summary = timed_run(frames, Worker(detector), on_result=show)

    print(f"\n{summary.succeeded}/{summary.tasks} succeeded, {summary.failed} failed")
    print(f"{summary.detections} people found in {summary.images_with_detections} images")
    print(f"per image: mean {summary.mean_ms:.0f} ms, median {summary.median_ms:.0f} ms, p95 {summary.p95_ms:.0f} ms")
    print(f"total {summary.wall_s:.1f} s ({summary.images_per_s:.1f} images/s)")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(r.to_wire()) + "\n" for r in results))
        print(f"results written to {args.output}")


if __name__ == "__main__":
    main()

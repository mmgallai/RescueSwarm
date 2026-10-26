"""Export YOLO26n to Core ML for the iOS app and check it agrees with the PyTorch detector.

coremltools does not support Python 3.14 or the newest PyTorch yet, so run this from a separate
Python 3.12 environment with PyTorch 2.7.0 (the newest version coremltools 9.0 was tested with):

    /opt/homebrew/bin/python3.12 -m venv .venv-export
    .venv-export/bin/pip install -e . coremltools "torch==2.7.0" "torchvision==0.22.0"
    .venv-export/bin/python scripts/export_coreml.py

The model is exported with nms=True: duplicate boxes are removed inside the model, so the app
only letterboxes the photo and maps the boxes back (see rescueswarm/coreml_reference.py).
"""
from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import cv2
from PIL import Image

from rescueswarm.coreml_reference import decode, letterbox
from rescueswarm.dataset import load_dataset
from rescueswarm.detector import DEFAULT_IMGSZ, PersonDetector
from rescueswarm.evaluate import Counts, iou, match_frame

ROOT = Path(__file__).resolve().parent.parent
IOU_THRESHOLD = 0.7  # the model's internal NMS; same as Ultralytics' default


def export(weights: str, imgsz: int, out_dir: Path) -> Path:
    from ultralytics import YOLO
    exported = Path(YOLO(weights).export(format="coreml", imgsz=imgsz, nms=True))
    target = out_dir / f"{Path(weights).stem}-{imgsz}.mlpackage"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(exported), target)
    return target


def coreml_detect(model, image, imgsz: int, conf: float):
    """Run the Core ML model the way the app will: letterbox, predict, decode."""
    square, box = letterbox(image, imgsz)
    rgb = Image.fromarray(cv2.cvtColor(square, cv2.COLOR_BGR2RGB))
    out = model.predict({"image": rgb, "iouThreshold": IOU_THRESHOLD, "confidenceThreshold": conf})
    height, width = image.shape[:2]
    return decode(out["coordinates"], out["confidence"], box, width, height, conf)


def verify(package: Path, weights: str, imgsz: int, conf: float) -> None:
    import coremltools as ct
    model = ct.models.MLModel(str(package))
    torch_detector = PersonDetector(weights, imgsz=imgsz, conf=conf)
    torch_detector.warmup()

    frames = load_dataset()
    both = only_torch = only_coreml = 0
    ious, conf_diffs = [], []
    truth = {"pytorch": Counts(), "coreml": Counts()}
    coreml_ms = 0.0
    for frame in frames:
        image = cv2.imread(str(frame.image_path))
        torch_dets = torch_detector.detect(image).detections
        started = time.perf_counter()
        coreml_dets = coreml_detect(model, image, imgsz, conf)
        coreml_ms += (time.perf_counter() - started) * 1000

        # Agreement between the two models: pair up boxes that overlap.
        unmatched = list(coreml_dets)
        for t in torch_dets:
            best = max(unmatched, key=lambda c: iou(c.box_xyxy, t.box_xyxy), default=None)
            if best is not None and iou(best.box_xyxy, t.box_xyxy) >= 0.5:
                unmatched.remove(best)
                both += 1
                ious.append(iou(best.box_xyxy, t.box_xyxy))
                conf_diffs.append(abs(best.confidence - t.confidence))
            else:
                only_torch += 1
        only_coreml += len(unmatched)

        for name, dets in (("pytorch", torch_dets), ("coreml", coreml_dets)):
            truth[name] += match_frame(frame.gt_boxes, [(d.box_xyxy, d.confidence) for d in dets])

    print(f"\n{len(frames)} images, conf {conf}, imgsz {imgsz}")
    print(f"boxes found by both: {both}, only PyTorch: {only_torch}, only Core ML: {only_coreml}")
    if ious:
        print(f"matched boxes: mean IoU {sum(ious) / len(ious):.3f}, "
              f"mean confidence difference {sum(conf_diffs) / len(conf_diffs):.3f}")
    for name, c in truth.items():
        print(f"{name:8} vs ground truth: precision {c.precision:.2f}, recall {c.recall:.2f} "
              f"(TP {c.tp}, FP {c.fp}, FN {c.fn})")
    print(f"Core ML on this Mac: {coreml_ms / len(frames):.0f} ms/image (letterbox + predict + decode)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--weights", default="yolo26n.pt")
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--out", type=Path, default=ROOT / "models")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    package = export(args.weights, args.imgsz, args.out)
    print(f"exported {package}")
    if not args.skip_verify:
        verify(package, args.weights, args.imgsz, args.conf)


if __name__ == "__main__":
    main()

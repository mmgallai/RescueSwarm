"""Write reference detections for the Swift detector's parity test.

Runs the exported Core ML model with the Python reference letterbox/decode
(rescueswarm/coreml_reference.py) on every SAR-DAG image and saves, per image, the
reference person boxes plus the ground truth. The Swift test runs its own detector on
the same images and checks it finds the same boxes. Needs the export environment, and runs
as a module from the repository root because it reuses scripts/export_coreml.py:

    .venv-export/bin/python -m scripts.export_swift_fixture \\
        --out ../RescueSwarm-app/rescue-swarm-ios/Tests/RescueSwarmCoreTests/Fixtures/sardag-reference.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import coremltools as ct
import cv2

from rescueswarm.dataset import DEFAULT_ROOT, load_dataset
from scripts.export_coreml import coreml_detect

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "yolo26n-1280.mlpackage")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    model = ct.models.MLModel(str(args.model))
    images = []
    for frame in load_dataset():
        image = cv2.imread(str(frame.image_path))
        detections = coreml_detect(model, image, args.imgsz, args.conf)
        images.append({
            "image_id": frame.image_id,
            "path": str(frame.image_path.relative_to(DEFAULT_ROOT)),  # relative to drone_data/
            "width": frame.width,
            "height": frame.height,
            "ground_truth": [[round(v, 1) for v in box] for box in frame.gt_boxes],
            "reference": [{"box_xyxy": [round(v, 1) for v in d.box_xyxy], "confidence": round(d.confidence, 4)}
                          for d in detections],
        })

    args.out.write_text(json.dumps({"model": args.model.name, "imgsz": args.imgsz, "conf": args.conf,
                                    "images": images}, indent=1))
    found = sum(len(i["reference"]) for i in images)
    print(f"wrote {len(images)} images, {found} reference detections to {args.out}")


if __name__ == "__main__":
    main()

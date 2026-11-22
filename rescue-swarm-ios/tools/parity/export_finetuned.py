"""Export a copy of the retained D85 checkpoint for testing; never modify the app."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from ultralytics import YOLO
import coremltools as ct
import torch
import ultralytics
from compare import HERE, MODEL, model_hashes

EXPECTED = "321b3164ad4c94005345bfd716997e2e5741d6dfb6687dabd156080e1cec47ae"
checkpoint = Path(os.environ["PARITY_CHECKPOINT"])
root = Path(os.environ["PARITY_ROOT"])
assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == EXPECTED
root.mkdir(parents=True, exist_ok=True)
copy = root / "export-source.pt"
shutil.copy2(checkpoint, copy)
model = YOLO(str(copy))
assert model.names == {0: "person"}, model.names
exported = Path(model.export(format="coreml", imgsz=1280, nms=True, half=False, device="cpu"))
assert not MODEL.exists(), "Never overwrite an existing export"
exported.rename(MODEL)
assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == EXPECTED
manifest = json.loads((HERE / "manifest.json").read_text())
manifest["source_checkpoint_sha256"] = EXPECTED
manifest["source_checkpoint"] = "D85: yolo26n-wisard-full-20261022/mixed640/weights/best.pt"
manifest["model_files"] = model_hashes()
manifest["settings"]["weights"] = "Frozen D85 checkpoint, separate CoreML export; no retraining or app replacement"
manifest["export_environment"] = {"torch": torch.__version__, "ultralytics": ultralytics.__version__,
    "coremltools": ct.__version__, "nms": True, "half_argument": False, "imgsz": 1280}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps({"source_sha256": EXPECTED, "export_files": manifest["model_files"],
                  "environment": manifest["export_environment"]}, indent=2))

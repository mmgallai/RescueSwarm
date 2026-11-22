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
size = int(os.environ.get("PARITY_SIZE", "1280"))
exported = Path(model.export(format="coreml", imgsz=size, nms=True, half=False, device="cpu"))
assert not MODEL.exists(), "Never overwrite an existing export"
exported.rename(MODEL)
assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == EXPECTED
manifest = json.loads((HERE / "manifest.json").read_text())
manifest["source_checkpoint_sha256"] = EXPECTED
manifest["source_checkpoint"] = "D85: yolo26n-wisard-full-20261022/mixed640/weights/best.pt"
manifest["model_files"] = model_hashes()
manifest["settings"]["imgsz"] = size
if os.environ.get("PARITY_TILED") == "1":
    manifest["settings"].update(conf=0.2193603515625, iou=0.5,
        inference_conf=0.21923828125, global_nms_iou=0.5, grid=4, margin_per_side=0.1)
manifest["settings"]["weights"] = "Frozen D85 checkpoint, separate CoreML export; no retraining or app replacement"
manifest["export_environment"] = {"torch": torch.__version__, "ultralytics": ultralytics.__version__,
    "coremltools": ct.__version__, "nms": True, "half_argument": False, "imgsz": size}
(root / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps({"source_sha256": EXPECTED, "export_files": manifest["model_files"],
                  "environment": manifest["export_environment"]}, indent=2))

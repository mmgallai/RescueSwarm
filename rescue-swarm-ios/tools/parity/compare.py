"""Frozen, inference-only Python/CoreML versus app Swift/CoreML comparison."""
import argparse
import hashlib
import json
import platform
import shutil
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = HERE.parents[1] / "App/YOLO26n.mlpackage"


def model_hashes():
    return {p.relative_to(MODEL).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(MODEL.rglob("*")) if p.is_file()}


def provision(root):
    from remote_zip import RemoteZip
    manifest = json.loads((HERE / "manifest.json").read_text())
    assert model_hashes() == manifest["model_files"], "Model changed"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "manifest.json", root / "manifest.json")
    with zipfile.ZipFile(RemoteZip()) as archive:
        for row in manifest["images"]:
            path = root / row["path"]
            if not path.exists():
                # ZipFile checks CRC; SHA256 must also match the corrected-label manifest.
                data = archive.read("heridal_keras_retinanet_voc/JPEGImages/" + row["path"])
                assert hashlib.sha256(data).hexdigest() == row["sha256"], row["id"]
                path.write_bytes(data)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
            print("VERIFIED", row["id"], flush=True)
    print("Provisioned all 32 frozen validation images", flush=True)


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0


def pair(a, b, cutoff=0.5):
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    if not a or not b:
        return []
    overlaps = np.array([[iou(x["box"], y["box"]) for y in b] for x in a])
    weights = np.where(overlaps >= cutoff, 10000 + overlaps, 0)
    ii, jj = linear_sum_assignment(-weights)
    return [(int(i), int(j), float(overlaps[i, j])) for i, j in zip(ii, jj) if overlaps[i, j] >= cutoff]


def run(root):
    import coremltools as ct
    import cv2
    import numpy as np
    from PIL import Image
    from reference import Letterbox, letterbox, decode
    manifest = json.loads((root / "manifest.json").read_text())
    assert model_hashes() == manifest["model_files"]
    settings = manifest["settings"]
    model = ct.models.MLModel(str(MODEL), compute_units=ct.ComputeUnit.ALL)
    swift = {r["id"]: r for r in json.loads((root / "swift-results.json").read_text())["images"]}
    records = []
    for row in manifest["images"]:
        path = root / row["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        original = cv2.imread(str(path))
        assert original is not None and list(original.shape[:2]) == [row["height"], row["width"]]
        results = {}
        for mode in ["python_native", "python_swift_pixels"]:
            began = time.perf_counter()
            if mode == "python_native":
                square, box = letterbox(original, settings["imgsz"])
                rgb = Image.fromarray(cv2.cvtColor(square, cv2.COLOR_BGR2RGB))
            else:
                rgb = Image.open(root / (row["id"] + "-swift.ppm")).convert("RGB")
                box = Letterbox.fit(row["width"], row["height"], settings["imgsz"])
            output = model.predict({"image": rgb, "iouThreshold": settings["iou"], "confidenceThreshold": settings["conf"]})
            detections = decode(output["coordinates"], output["confidence"], box, row["width"], row["height"], settings["conf"])
            results[mode] = {"detections": [{"box": [float(v) for v in d.box_xyxy], "confidence": float(d.confidence)} for d in detections],
                             "elapsed_ms": (time.perf_counter()-began)*1000}
        records.append({"id": row["id"], "swift": swift[row["id"]], **results})
        print("PARITY_PYTHON", row["id"], {k: len(v["detections"]) for k, v in results.items()}, flush=True)
    (root / "paired-results.json").write_text(json.dumps({"images": records, "environment": {
        "python": platform.python_version(), "platform": platform.platform(), "coremltools": ct.__version__,
        "opencv": cv2.__version__, "numpy": np.__version__}, "model_files": model_hashes()}, indent=2))
    audit(root)


def audit(root):
    manifest = json.loads((root / "manifest.json").read_text())
    paired = json.loads((root / "paired-results.json").read_text())
    rows = {r["id"]: r for r in manifest["images"]}
    assert {r["id"] for r in paired["images"]} == set(rows) and len(rows) == 32
    summary = {"images": len(rows), "annotated_people": sum(len(r["boxes"]) for r in rows.values()),
               "settings": manifest["settings"], "model_files": manifest["model_files"], "accuracy": {}, "agreement": {}}
    for mode in ["swift", "python_native", "python_swift_pixels"]:
        tp = fp = fn = 0
        misses = []
        for r in paired["images"]:
            gt = [{"box": b} for b in rows[r["id"]]["boxes"]]
            det = r[mode]["detections"]
            matches = pair(gt, det)
            tp += len(matches); fp += len(det)-len(matches); fn += len(gt)-len(matches)
            found = {m[0] for m in matches}
            misses.extend([f"{r['id']}:{i}" for i in range(len(gt)) if i not in found])
        summary["accuracy"][mode] = {"tp": tp, "fp": fp, "fn": fn, "precision": tp/max(tp+fp, 1),
            "recall": tp/max(tp+fn, 1), "missed_annotation_ids": misses}
    for mode in ["python_native", "python_swift_pixels"]:
        total_a = total_b = matched = 0
        overlaps, differences, unmatched = [], [], []
        for r in paired["images"]:
            a, b = r[mode]["detections"], r["swift"]["detections"]
            matches = pair(a, b)
            total_a += len(a); total_b += len(b); matched += len(matches)
            overlaps.extend(m[2] for m in matches)
            differences.extend(abs(a[i]["confidence"]-b[j]["confidence"]) for i,j,_ in matches)
            if len(matches) != len(a) or len(matches) != len(b):
                unmatched.append({"id": r["id"], "python": len(a), "swift": len(b), "matched": len(matches)})
        summary["agreement"][mode] = {"python_boxes": total_a, "swift_boxes": total_b, "matched": matched,
            "python_only": total_a-matched, "swift_only": total_b-matched,
            "mean_iou": sum(overlaps)/max(1,len(overlaps)), "min_iou": min(overlaps,default=0),
            "mean_confidence_difference": sum(differences)/max(1,len(differences)),
            "max_confidence_difference": max(differences,default=0), "unmatched_images": unmatched}
    shared = summary["agreement"]["python_swift_pixels"]
    summary["shared_pixel_check"] = "PASS" if (shared["matched"] > 0 and shared["python_only"] == shared["swift_only"] == 0
        and shared["min_iou"] >= 0.999 and shared["max_confidence_difference"] <= 0.0001) else "FAIL"
    summary["limitations"] = ["Reused, stratified corrected-validation sample; not a new accuracy benchmark.",
        "Both languages execute the exact bundled CoreML package; this does not test the Python PyTorch worker or trained research checkpoints.",
        "Native Python uses OpenCV resize; Swift uses ImageIO/CoreGraphics. Shared-pixel pass isolates preprocessing differences."]
    (root / "comparison.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    assert summary["shared_pixel_check"] == "PASS", "Shared-pixel inference or decoding mismatch: inspect paired outputs"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["provision", "run", "audit"])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    {"provision": provision, "run": run, "audit": audit}[args.action](args.root)

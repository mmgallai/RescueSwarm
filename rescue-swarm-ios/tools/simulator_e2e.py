"""Run three actual iOS Simulator app instances over TCP. macOS/Xcode only.

Uses a public non-aerial photo and explicitly synthetic camera metadata to check
plumbing, not detector accuracy or real geolocation. Does not mock inference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

PHOTO = "https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg"
PHOTO_SHA = "c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63"
PROGRESS = None


def command(*args):
    print("Running:", " ".join(args), flush=True)
    if PROGRESS:
        with PROGRESS.open("a") as log:
            log.write(time.strftime("%H:%M:%S ") + " ".join(args) + "\n")
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=180).strip()
    except subprocess.CalledProcessError as error:
        print(error.output, flush=True)
        raise


def sim(*args):
    return command("xcrun", "simctl", *args)


def wait_for(fn, seconds=240):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.5)
    raise TimeoutError(f"Condition not reached in {seconds}s")


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def validate(report, recovery):
    assert report["state"] == "finished", report
    assert report["failed_task_ids"] == [], report
    results = report["results"]
    assert len(results) == 6
    assert sorted(r["result"]["task_id"] for r in results) == list(range(6))
    assert len({r["result"]["image_id"] for r in results}) == 6
    assert len(report["tasks_per_worker"]) == (1 if recovery else 2)
    assert report["retries"] == (1 if recovery else 0)
    assert report["assignments"] == (7 if recovery else 6)
    detections = 0
    for row in results:
        result = row["result"]
        assert result["status"] == "success" and result["synthetic"] is False
        assert result["detector"] == "yolo26n"
        assert result["image_size"] == {"width": 810, "height": 1080}
        assert result["detections"], "Real detector must find at least one person"
        detections += len(result["detections"])
    sightings = report["sightings"]
    assert len(sightings) == detections
    assert len({s["id"] for s in sightings}) == detections
    for sighting in sightings:
        assert not sighting.get("issue"), sighting
        assert abs(sighting["latitude"] - 42) < 0.002
        assert abs(sighting["longitude"] + 76) < 0.002
        event = ET.fromstring(sighting["cot_xml"])
        assert event.attrib["uid"] == sighting["id"]
        assert abs(float(event.find("point").attrib["lat"]) - sighting["latitude"]) < 1e-6
    return {"completed": 6, "sightings": detections, "retries": report["retries"],
            "workers_with_results": len(report["tasks_per_worker"]), "elapsed_s": report["elapsed_s"]}


def main():
    global PROGRESS
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("TestResults/simulator-e2e"))
    parser.add_argument("--embedded-workers", action="store_true",
                        help="One iOS simulator, three independent SessionModels and real TCP; no device/process isolation")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    PROGRESS = args.output / "progress.log"
    bundle = plistlib.loads((args.app / "Info.plist").read_bytes())["CFBundleIdentifier"]
    photo = urllib.request.urlopen(PHOTO, timeout=60).read()
    assert hashlib.sha256(photo).hexdigest() == PHOTO_SHA
    (args.output / "photo-provenance.json").write_text(json.dumps({"url": PHOTO, "sha256": PHOTO_SHA,
        "purpose": "Integration only; synthetic camera telemetry; not SAR-DAG or aerial accuracy."}, indent=2))
    runtimes = json.loads(sim("list", "runtimes", "--json"))["runtimes"]
    runtime = min((r for r in runtimes if r["isAvailable"] and ".iOS-" in r["identifier"]),
                  key=lambda r: tuple(map(int, r["version"].split("."))))["identifier"]
    types = json.loads(sim("list", "devicetypes", "--json"))["devicetypes"]
    # simctl's list is newest first; reversing it selected unsupported iPhone 6s.
    supported = {t["identifier"] for r in runtimes if r["identifier"] == runtime
                 for t in r.get("supportedDeviceTypes", [])}
    types.sort(key=lambda t: t["name"] != "iPhone 16 Pro")
    device_type = next(t["identifier"] for t in types if t["name"].startswith("iPhone")
                       and (not supported or t["identifier"] in supported))
    devices, containers, summaries = [], [], {}
    try:
        for i in range(1 if args.embedded_workers else 3):
            device = sim("create", f"RescueSwarm-E2E-{i}", device_type, runtime)
            devices.append(device)
            sim("boot", device)
            sim("bootstatus", device, "-b")
            sim("install", device, str(args.app.resolve()))
            containers.append(Path(sim("get_app_container", device, bundle, "data")))
        for case, policy, recovery in [("next-available", "nextAvailable", False),
                                       ("round-robin", "roundRobin", False),
                                       ("disconnect-recovery", "nextAvailable", True)]:
            case_dir = args.output / case
            case_dir.mkdir(exist_ok=True)
            for i, container in enumerate(containers):
                documents = container / "Documents"
                documents.mkdir(exist_ok=True)
                for f in documents.glob("e2e-*"):
                    f.unlink()
                (documents / "e2e-config.json").write_text(json.dumps({"role": "coordinator" if i == 0 else "worker",
                    "port": "18765", "policy": policy,
                    "holdTask": recovery and (i == 1 or args.embedded_workers),
                    "embeddedWorkers": args.embedded_workers}))
            docs = containers[0] / "Documents"
            images = docs / "images"
            images.mkdir(exist_ok=True)
            for i in range(6):
                (images / f"photo-{i}.jpg").write_bytes(photo)
            (docs / "telemetry.json").write_text(json.dumps({"schema_version": 1, "images": [{
                "image_sha256": PHOTO_SHA, "width": 810, "height": 1080,
                "captured_at": "2026-11-21T12:00:00Z", "latitude": 42, "longitude": -76,
                "altitude_agl_m": 50, "horizontal_fov_deg": 70, "vertical_fov_deg": 55,
                "camera_heading_deg": 0, "camera_pitch_deg": -90, "camera_roll_deg": 0}]}))
            previous = set((containers[0] / "Library/Application Support/Reports").glob("*.json"))
            for device in devices:
                sim("launch", device, bundle, "--simulator-e2e")
            if recovery and not args.embedded_workers:
                state = containers[1] / "Documents/e2e-state.json"
                wait_for(lambda: read_json(state).get("status") == "E2E holding assigned task")
                sim("terminate", devices[1], bundle)
            state = docs / "e2e-state.json"
            final = wait_for(lambda: (s if (s := read_json(state)) and not s["running"] else None))
            if recovery and args.embedded_workers:
                assert final["injected_disconnect"] is True
            assert not final["report_error"], final
            reports = set((containers[0] / "Library/Application Support/Reports").glob("*.json")) - previous
            assert len(reports) == 1, reports
            report_path = reports.pop()
            shutil.copy2(report_path, case_dir / "session-report.json")
            summaries[case] = validate(read_json(report_path), recovery)
            print(case, json.dumps(summaries[case]), flush=True)
            for device in devices:
                subprocess.run(["xcrun", "simctl", "terminate", device, bundle], capture_output=True, timeout=30)
        (args.output / "summary.json").write_text(json.dumps({"status": "PASS", "cases": summaries,
            "simulator_count": len(devices), "embedded_workers": args.embedded_workers,
            "limitation": "Simulator CPU/network behavior, synthetic camera telemetry. Not device performance or field accuracy."}, indent=2))
    finally:
        for i, (device, container) in enumerate(zip(devices, containers)):
            for source in [container / "Documents", container / "Library/Application Support/Reports"]:
                if source.exists():
                    shutil.copytree(source, args.output / f"device-{i}" / source.name, dirs_exist_ok=True)
        for device in devices:
            for action in ["shutdown", "delete"]:
                try:
                    subprocess.run(["xcrun", "simctl", action, device], capture_output=True, timeout=20)
                except subprocess.TimeoutExpired:
                    print(f"Cleanup {action} timed out for {device}", flush=True)


if __name__ == "__main__":
    main()

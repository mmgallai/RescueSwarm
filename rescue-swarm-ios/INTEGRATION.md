# Coordinator, detector and geolocation integration

The `codex/swift-integration` branch combines Mohamed's Swift coordinator,
Evi's bundled Core ML YOLO26n worker and Aidan's Swift geolocation package.

## Run a session

1. Open `rescue-swarm-ios/RescueSwarm.xcodeproj` in Xcode from this repository.
   Keep the sibling `swift` directory alongside it for the package dependency.
2. Build and install on two iPhones. Connect both to the same local Wi-Fi.
3. On the coordinator choose images, then **Import telemetry JSON**. Verify the
   number of matched images. The SHA256 is of the original JPEG/PNG file bytes,
   before import renames it. Duplicate source filenames are handled by content hash.
4. Select Single worker, start the coordinator, and join from the worker phone.
5. Candidate sightings show estimated coordinates or the reason a location could
   not be computed. Export the saved JSON report to inspect boxes, metadata,
   timestamps, per-detection IDs and generated CoT XML.
6. Repeat with three phones, selecting two workers and Next available. Disconnect
   a worker while processing and confirm reassignment and one accepted result per task.

Telemetry may cover part of a batch. Images without matching metadata still
produce detections, with a missing-telemetry issue for each sighting. Selecting
a new image batch clears previous metadata. Failed telemetry imports retain the
previous metadata. Reports saved before this integration remain readable.

## Telemetry JSON

Supply real values from the image's camera record. The shape below is illustrative.
Replace the hash and every measurement before using it with a real photograph.

```json
{
  "schema_version": 1,
  "images": [{
    "image_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "width": 4000,
    "height": 3000,
    "captured_at": "2026-11-21T12:00:00Z",
    "latitude": 42.0,
    "longitude": -76.0,
    "altitude_agl_m": 50.0,
    "horizontal_fov_deg": 70.0,
    "vertical_fov_deg": 55.0,
    "camera_heading_deg": 0.0,
    "camera_pitch_deg": -90.0,
    "camera_roll_deg": 0.0
  }]
}
```

Dimensions, FOV and heading describe the upright decoded image. The metadata
producer must account for any EXIF rotation or preprocessing. AGL means height
above the ground directly beneath the camera. Heading is clockwise from north.
This integration supports nadir pitch -90 and roll 0, flat ground and box
bottom-center anchoring. Tilted images receive an explicit unsupported-angle
issue. Optional `ground_hae_m` supplies ground elevation above the ellipsoid.
See `../GEOLOCATION.md` for geometry and height assumptions.

Each sighting gets a run/task/detection ID that survives retry and report reload.
Different images can represent the same person and require later tracking.
The report preserves capture time and computes CoT time/stale from that capture
time. Historical events can therefore already be stale. A live TAK transport
and its time/review policy are a later integration step. Generated XML is saved
for inspection. This milestone performs no TAK network delivery.

## Verification

Run `python tools/test_project.py -v`, `swift test`, and
`bash tools/test_on_mac.sh` from `rescue-swarm-ios`. Run `swift test` in `swift`
for the geolocation package. GitHub Actions executes the Mac tests and unsigned
iOS Simulator build. Actual signing, file pickers, permission prompts, physical
phone networking and interactive review require the two/three-phone session above.

The detector parity test requires Evi's SAR-DAG fixture and is skipped when that
external dataset is absent. The bundled app model retains its existing detector
configuration. Training research results must be evaluated separately before
choosing a new app model.

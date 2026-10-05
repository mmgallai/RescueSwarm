# Shared implementation contracts

Design v1, not implemented Swift APIs yet. All teammates implement against these
boundaries. Wire compatibility uses the Python coordinator contribution's README, not Swift's
default property naming. Explicit Codable keys must preserve existing snake_case.

## Mohamed: transport and scheduling

`ImageTask`: session/run ID, integer task ID, integer attempt ID, image ID, file URL,
byte count and SHA-256. File URLs are device-local and never transmitted as usable peer paths.
`WorkerState`: worker ID, connection status, readiness, current assignment, battery,
thermal state, model identity and measured timings. Device ID must not depend on display name.

`Transport`: startHost, discoverHosts, connect, sendTask, sendResult, disconnect;
events for connected, disconnected, taskReceived, resultReceived and heartbeat.
Network callbacks deliver data to Coordinator; they never directly modify task state.

`Scheduler`: enqueue, workerReady, resultReceived, workerLost, deadlineExpired,
pause, resume, stop. Emit taskAssigned, resultAccepted, taskFailed and sessionProgress.
Model loading means not ready. Never dispatch unsupported image/model configurations.

Developer interoperability: 4-byte unsigned big-endian JSON length, JSON header,
payload_bytes raw bytes. hello/version=1/worker_id; task IDs, image ID, hash; result
status, IDs, detections, processing_ms; heartbeat. Preserve partial reads and serialize
writes. Use the Python protocol limits. The v1 TCP connection is scoped to one session;
the app maps it to a local session ID. Additional session/security/capability messages
require a separately negotiated version before use, not an unannounced v1 change.

## Evi: detector

Conceptual Swift boundary: `detect(image: ImageInput) async throws -> DetectionResult`.
`ImageInput`: bytes or file URL plus image ID. Decode orientation into one canonical
upright raster shared with annotations and telemetry. Record any rotation/crop transform.
`DetectionResult`: original raster width/height, detections, inference duration,
model identifier/version and preprocessing configuration. Each detection has person
label, confidence in [0,1] and finite xyxy box in original-image pixels, origin top-left.
Allow box edges up to width/height; a selected pixel point must lie inside the raster.
Define resizing/letterbox reversal in this adapter; no downstream component should guess.

Empty detections are a successful result, not an exception. A decode/model error is
failure and retryable only under the configured attempt policy. Keep model conversion,
warmup and download out of measured per-image inference. Bundle/import model before
offline use. The coordinator measures end-to-end latency separately from worker timing.

## Aidan: geolocation and TAK

`Geolocator`: accepted result + matching CameraMetadata -> candidate estimates/errors.
Metadata contains capture timestamp with time base, camera intrinsics and distortion/
rectification convention, camera position/altitude datum, camera orientation and axis
convention, and ground-plane height or terrain reference. Missing required values
yield locationUnavailable with a reason. Detection remains reviewable without a location.
Drone coordinates must not be presented as the person's coordinates.

`Sighting`: (session, task, detection index) identity, source image/box, model confidence,
optional coordinate estimate, estimation method, optional uncertainty, provenance,
capture time and receipt time separately, review status. Confidence is not GPS accuracy.
Initial flat-ground point selection is bottom midpoint; handle edge-coordinate conventions
explicitly and document the standing-person/ground-contact assumption.

`TAKPublisher`: enqueue(sighting), retry(messageID), deliveryState(messageID).
Use an outbox: pending, sending, sentToTransport, confirmedByReceiver if actually
supported, failed. A successful socket send does not prove iTAK displayed a marker.
Default user flow reviews a candidate before publication. Preserve message identity
on retry. Do not publish synthetic test events to an operational destination.
Aidan validates the actual transport/server/iTAK configuration; no direct access to
another app's internal data is assumed. Switching to iTAK can background RescueSwarm.

## Storage and shared fixtures

Persist source-image reference/hash, metadata, accepted results, task/attempt state,
review status, outbox and event history. Commit accepted result and terminal task state
atomically. On import copy files into session storage so temporary picker URLs do not expire.
Persist run identity across reopen; new sessions get new IDs.

Reference wire fixture: `Tests/RescueSwarmCoreTests/Fixtures/python-task.bin`.
The Python coordinator branch can generate JSON reports and JSONL accepted results.
Mock fixtures are synthetic and useful for
contract parsing, duplicate suppression and UI fixtures, not model accuracy or GPS validation.
Swift session storage is not required to use the same format; exported data must preserve
the documented fields and explicitly identify its schema version.

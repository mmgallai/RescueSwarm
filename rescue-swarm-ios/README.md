# RescueSwarm native app foundation

Implemented source for the first native milestone, not a finished rescue app.
The coordinator sends a selected batch of imported images or one built-in PPM fixture. A worker
verifies SHA-256, simulates 150ms processing and returns an explicitly synthetic,
empty result. No detector or TAK connection is included in this build.

## What is in the folder

- `RescueSwarm.xcodeproj`: prepared Xcode app project and shared scheme.
- `App/`: SwiftUI role/session screens, image importer, Bonjour discovery, TCP connection and session logic.
- `Sources/RescueSwarmCore/`: incremental framed protocol, file-backed image batches and three-policy task ledger.
- `Tests/`: twenty-nine Swift XCTest methods for reports, discovery, imports, policies, fragmentation, combined frames, invalid
  lengths, retries, stale/duplicate results, attempt limits and empty queues.
- `tools/test_project.py`: Windows-runnable project/fixture checks, not a Swift compiler.
- `tools/test_on_mac.sh`: Swift tests followed by an unsigned iOS Simulator build.

## Test and build on the teammate's Mac

1. Copy this entire folder. Install/open Xcode and complete its initial setup.
2. From this folder run `bash tools/test_on_mac.sh`. It stops on failure and saves logs
   in TestResults. Do not call the app verified until this passes.
3. Open `RescueSwarm.xcodeproj`. Select the RescueSwarm scheme and an iPhone simulator.
   Run and inspect the UI. The project initially targets iOS 16+; confirm team devices.
4. For a real iPhone, select a signing team in Signing & Capabilities and choose a
   unique bundle identifier if required. Select the device and Run. Signing is not
   needed for the script's simulator build.
5. Repeat on the second iPhone for actual phone-to-phone validation.

The workflow `.github/workflows/swift-tests.yml` runs package tests and the simulator
build on macOS after the repository is pushed. It has been prepared, not executed here.
Neither code nor messages have been sent to teammates automatically.

## First two-phone test

1. Connect both phones to the same local Wi-Fi and keep RescueSwarm in the foreground.
2. On phone A choose Coordinator. Use the fixture, or choose up to 500 JPG/PNG files,
   each under 16 MiB. Choose Single worker for a two-phone test (one coordinator,
   one worker). Leave port 8765 and tap Start. Wait for the listening status.
3. Set a recognizable session name on A before starting. On phone B choose Worker,
   tap Find nearby sessions, then Join beside A's name. Allow local-network access when
   prompted. The selected Bonjour endpoint supplies the connection address and port.
4. Phone A must show one accepted result per image; phone B must log verified image
   hashes and submitted tasks. Results are synthetic and contain no person detections.
5. Repeat with an imported photo. Turn off Internet upstream while retaining local Wi-Fi
   and repeat. If discovery is unavailable, enter A's Wi-Fi IP and port on B and tap
   Start. The Python coordinator is not advertised through Bonjour; use manual mode for it.

Discovery uses `_rescueswarm._tcp` and the declared local-network permission. Refresh
replaces the previous browser and clears stale entries. Changing roles, joining,
leaving the screen or backgrounding stops discovery. A waiting/failed browser gives
a retry message; an empty list does not prove permission was denied. Discovery can
be blocked by Wi-Fi client isolation. Names identify a selection, not an authenticated
device; secure pairing remains a later milestone. No automatic join is performed.

Device checks for discovery: start two coordinators with distinct names, confirm both
appear, stop one and confirm its entry disappears, refresh repeatedly, deny/restore
Local Network permission and retry, then join and complete a batch. Also test manual
IP connection to the Python reference. These checks have not yet run on devices.

For multiple workers choose Round robin or Next available and set the required worker
count. Processing starts only when that many workers join. Round robin fixes the initial
roster sorted by worker name; lost owners' tasks and retries can move to another worker.
Single mode allows one connected worker. Each image gets a unique prefixed image ID
even if imported filenames collide; match future telemetry to these imported IDs.

Imports copy into app-owned storage, replacing the previous selection only on success.
Files are read off the UI thread when assigned, one image per active worker; entire
datasets are not loaded into RAM. Selection is in-memory: relaunch restoration and
cleanup of abandoned imports are still pending. No pause/resume yet.

Each test session has a 10-minute limit. The coordinator gives a task 10 seconds and
disconnects peers silent for 3 seconds; a failed assignment can retry up to 3 attempts.
After loss, a worker rejoins using Start. Starting a new coordinator test creates a new
in-memory ledger. Backgrounding stops the session explicitly; durable resume comes later.
Only the coordinator acceptance proves a completed task; worker "submitted" is not acknowledgment.

## Test against Mohamed's Windows Python peer

From `scheduling-simulation`, start the reference coordinator, then join with the iPhone:

```powershell
python network.py coordinator --host 0.0.0.0 --port 8765 --workers 1 --tasks 1 --run-timeout 60
```

For the other direction, start the iPhone coordinator and replace IP_ADDRESS below:

```powershell
python network.py worker --host IP_ADDRESS --port 8765 --worker-id windows --no-reconnect --lifetime 60
```

Use a trusted test LAN; current v1 transport has no authentication or encryption.
Windows firewall or router client isolation can block a real LAN test. No settings
were changed automatically. Existing Python TCP functionality was previously tested;
these Swift/Python device instructions still require execution on a Mac/iPhone.

## Current verification

Five Windows checks passed: project/scheme references, build source coverage, plist
permission description, matching Bonjour declaration, and Python decoding/checking the fixture.
Twenty-nine Swift tests are written but NOT RUN: no Swift compiler or Xcode is installed
on the available Windows machine. The SwiftUI UI, iOS build and real networking
behavior are therefore unverified. See TEST_STATUS.md for the exact boundary.

## Saved results and exports

Coordinator runs create an atomic JSON checkpoint before accepting work, after each
accepted result, and when stopped or finished. Reopening the app loads Saved coordinator
runs; Export JSON report opens the system share sheet. Workers do not save coordinator
reports. If saving a result fails, the session stops and shows an error instead of
counting an unsaved completion. Unreadable reports are retained and counted in a warning.

Exports contain run identity, UTC start time, policy, input IDs, expected worker count,
accepted results with detector/synthetic provenance, failed IDs, assignment/retry counts,
per-worker completion totals, first-result latency, elapsed session time and batch time.
`received_s` and `first_result_s` measure time since session start, including worker wait.
`batch_s` excludes the initial wait. `image_bytes_submitted` counts payload bytes handed
to transport, including retries; it is not confirmed network delivery or wire overhead.
Timings include checkpoint overhead. First result is not first correct person detection.

`running` in a stored report means an unfinished checkpoint, not proof the old session
is still active. `finished` means all tasks reached a terminal state; inspect failed IDs
before claiming success. `stopped` may have unfinished images. Abrupt termination can
lose activity after the last checkpoint, although previously saved results remain.
Saved reports contain no image bytes and do not resume the queue. JSON exports can
contain image names and detections; share them deliberately using the system sheet.

Mac/device verification: run the Swift suite, process a batch, export its JSON, restart
the app and compare saved IDs/counts. Then stop a partial run and verify it is not shown
as completed. Report tests have been written but not executed on this Windows host.

## Remaining milestones

Build/device fixes first, then persistence/rejoin, measured
comparison reports, real Core ML inference and geolocation/TAK.
The batch foundation does not yet implement every feature in APP_DESIGN.md.

Implementation references: Apple's [receive API](https://developer.apple.com/documentation/network/nwconnection/receive(minimumincompletelength:maximumlength:completion:))
and [file importer](https://developer.apple.com/documentation/swiftui/view/fileimporter(ispresented:allowedcontenttypes:oncompletion:)),
plus [NWBrowser](https://developer.apple.com/documentation/network/nwbrowser) for service discovery.

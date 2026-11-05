# Coordinator and scheduling reference

Mohamed's coordinator contribution. Python 3.10+ standard library only.
No detector model, dataset, geolocation estimator or TAK publisher is included.
Mock workers exercise the interfaces that teammates can implement independently.

From this folder:

```sh
python -m unittest discover -v
python network.py demo --port 0
python network.py demo --port 0 --policy round_robin --disconnect-once
python compare_tcp.py --output results/comparison
```

`simulation.py` models network/compute delays using processes. `network.py` transfers
real bytes through TCP between separate processes; inference is mocked. Single,
round_robin and next_available share the same transport. Next-available is the default.
Round robin fixes a sorted initial worker roster; orphaned tasks and retries can move.
Reports include counts, latency, bytes, retries and per-worker results. JSONL handoffs
contain successful accepted results only; absent camera metadata remains null.
`--telemetry` accepts opaque metadata keyed by image ID for downstream handoff only.
There is no GPS calculation here. Mock results are explicitly marked synthetic.

## Team integration contract

TCP v1: four-byte big-endian JSON header length, UTF-8 JSON, then `payload_bytes`
raw image bytes. Limits: 64 KiB header, 16 MiB payload. Serialize complete frames.

- Hello: `type=hello`, `version=1`, unique `worker_id`.
- Heartbeat: `type=heartbeat`, every 0.2 seconds while connected, including inference.
- Task: `type=task`, integer `task_id`, `attempt_id`, `image_id`, `sha256`, image payload.
- Result: `type=result`, same IDs, `status=success|failure`, `processing_ms`, `detections`,
  `synthetic`, `detector`, `payload_bytes=0`. Failure can include `error`.
- Each person detection: `label=person`, confidence in [0,1], original-image `box_xyxy`.
  Empty detections means successful processing without a person. Optional `image_size`
  contains width/height. No resized/cropped coordinates should escape the detector adapter.

Evi can implement an independent worker or replace `mock_detect`; run blocking inference
off the network event loop so heartbeats continue. Aidan can consume the accepted-result
JSONL export after a batch and join exact image IDs to camera metadata. Exports are not
a live event stream. Coordinate that interface before integrating a live publisher.

Retries can execute a task multiple times, but only the current attempt is accepted once
within a batch. Default deadlines: heartbeat 3s, task 10s, run 60s, at most 3 attempts.
No persistent coordinator recovery, authentication or encryption is implemented.
Use test imagery on a trusted LAN. Loopback timing does not establish phone performance.

For two machines, start `network.py coordinator --host 0.0.0.0 --workers 2`, then
`network.py worker --host COORDINATOR_IP --worker-id UNIQUE_NAME` on each worker.
Physical Wi-Fi remains a separate validation step. No Internet connection is needed
for processing once the code/input files are present.

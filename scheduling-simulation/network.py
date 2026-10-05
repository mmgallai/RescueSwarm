"""TCP coordinator with mock workers. Created with OpenAI Codex assistance."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import struct
import sys
import time
import uuid
from collections import deque
from pathlib import Path


MAX_HEADER = 64 * 1024
MAX_IMAGE = 16 * 1024 * 1024


async def send(writer, message, payload=b"", lock=None):
    header = json.dumps({**message, "payload_bytes": len(payload)}, allow_nan=False).encode()
    if len(header) > MAX_HEADER or len(payload) > MAX_IMAGE:
        raise ValueError("Message exceeds protocol limit")
    async def write():
        writer.write(struct.pack("!I", len(header)) + header + payload)
        await writer.drain()
    if lock:
        async with lock:
            await write()
    else:
        await write()
    return 4 + len(header) + len(payload)


async def receive(reader):
    length, = struct.unpack("!I", await reader.readexactly(4))
    if not 0 < length <= MAX_HEADER:
        raise ValueError("Invalid header length")
    header = json.loads(await reader.readexactly(length))
    if not isinstance(header, dict):
        raise ValueError("Header must be an object")
    size = header.get("payload_bytes")
    if type(size) is not int or not 0 <= size <= MAX_IMAGE:
        raise ValueError("Invalid payload length")
    return header, await reader.readexactly(size), 4 + length + size


def fixture():
    """A valid 320x240 PPM image; no person and no detection ground truth."""
    return b"P6\n320 240\n255\n" + bytes([70, 110, 80]) * (320 * 240)


def load_images(directory, count):
    if directory:
        paths = sorted(p for p in directory.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".ppm"))
        if not paths:
            raise ValueError("No JPG, PNG or PPM images in directory")
        images = [(p.name, p.read_bytes()) for p in paths]
    else:
        images = [(f"fixture-{i:04d}.ppm", fixture()) for i in range(count)]
    if not images or any(not data or len(data) > MAX_IMAGE for _, data in images):
        raise ValueError("Images must be nonempty and at most 16 MiB")
    return images


def validate_detections(message):
    size = message.get("image_size")
    if size is not None and (not isinstance(size, dict) or any(
            type(size.get(k)) is not int or size[k] <= 0 for k in ("width", "height"))):
        raise ValueError("Invalid image_size")
    if "synthetic" in message and type(message["synthetic"]) is not bool:
        raise ValueError("synthetic must be boolean")
    for detection in message["detections"]:
        if not isinstance(detection, dict):
            raise ValueError("Invalid detection")
        box, confidence = detection.get("box_xyxy"), detection.get("confidence")
        if (not isinstance(box, list) or len(box) != 4 or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or not 0 <= box[0] < box[2] or not 0 <= box[1] < box[3]
                or type(confidence) not in (int, float) or not math.isfinite(confidence)
                or not 0 <= confidence <= 1 or detection.get("label") != "person"):
            raise ValueError("Invalid person detection")
        if size and (box[2] > size["width"] or box[3] > size["height"]):
            raise ValueError("Box outside original image")


def handoff_records(report, telemetry):
    """Accepted results only; unknown metadata stays unknown, never invented."""
    return [{"schema_version": 1, "run_id": report["run_id"],
             **{k: r.get(k) for k in ("task_id", "attempt_id", "image_id", "worker_id",
                 "status", "detections", "processing_ms", "received_s", "image_size",
                 "synthetic", "detector", "detector_config")},
             "camera_telemetry": telemetry.get(r["image_id"])} for r in report["results"]]


class Coordinator:
    def __init__(self, images, min_workers=2, task_timeout=10., heartbeat_timeout=3.,
                 run_timeout=60., max_attempts=3, telemetry=None, policy="next_available"):
        if not images or min_workers < 1 or max_attempts < 1:
            raise ValueError("Images, workers and attempts must be positive")
        if min(task_timeout, heartbeat_timeout, run_timeout) <= 0:
            raise ValueError("Timeouts must be positive")
        if not all(math.isfinite(v) for v in (task_timeout, heartbeat_timeout, run_timeout)):
            raise ValueError("Timeouts must be finite")
        if policy not in ("single", "round_robin", "next_available"):
            raise ValueError("Invalid scheduling policy")
        if policy == "single" and min_workers != 1:
            raise ValueError("Single policy requires exactly one worker")
        if len({name for name, _ in images}) != len(images):
            raise ValueError("image_id must be unique within a batch")
        if any(not isinstance(data, bytes) or not 0 < len(data) <= MAX_IMAGE for _, data in images):
            raise ValueError("Invalid image payload")
        self.images = images
        self.policy, self.roster = policy, []
        self.run_id = str(uuid.uuid4())
        self.wakes = {}
        self.min_workers = min_workers
        self.task_timeout = task_timeout
        self.heartbeat_timeout = heartbeat_timeout
        self.run_timeout = run_timeout
        self.max_attempts = max_attempts
        self.telemetry = telemetry or {}
        self.first_detection_result_s = self.first_synthetic_sighting_s = None
        self.pending = deque(range(len(images)))
        self.attempts = [0] * len(images)
        self.results, self.failed, self.connections = {}, {}, {}
        self.events, self.handlers = [], set()
        self.ready, self.done = asyncio.Event(), asyncio.Event()
        self.created = time.monotonic()
        self.started = None
        self.tx_bytes = self.rx_bytes = self.image_bytes = 0
        self.server = None

    def event(self, name, **fields):
        self.events.append({"time_s": time.monotonic()-self.created, "event": name, **fields})

    def notify_workers(self):
        for wake in self.wakes.values():
            wake.set()

    def take_task(self, worker_id):
        if not self.ready.is_set():
            return None
        for task_id in self.pending:
            home = self.roster[task_id % len(self.roster)]
            if (self.policy != "round_robin" or home == worker_id
                    or home not in self.connections or self.attempts[task_id] > 0):
                self.pending.remove(task_id)
                return task_id
        return None

    async def start(self, host="127.0.0.1", port=0):
        self.server = await asyncio.start_server(self.handle, host, port)
        return self.server.sockets[0].getsockname()[1]

    async def handle(self, reader, writer):
        handler = asyncio.current_task()
        self.handlers.add(handler)
        worker_id = None
        assigned = None
        reading = None
        reason = "coordinator stopped"
        try:
            hello, payload, size = await asyncio.wait_for(receive(reader), 3)
            self.rx_bytes += size
            name = hello.get("worker_id")
            if (hello.get("type") != "hello" or hello.get("version") != 1
                    or not isinstance(name, str) or not 1 <= len(name) <= 64
                    or payload or name in self.connections):
                raise ValueError("Invalid hello or duplicate worker ID")
            if self.policy == "single" and self.connections:
                raise ValueError("Single policy accepts one active worker")
            worker_id = name
            self.connections[name] = writer
            wake = self.wakes[name] = asyncio.Event()
            self.event("connected", worker_id=name)
            if len(self.connections) >= self.min_workers and not self.ready.is_set():
                self.roster = sorted(self.connections)
                self.started = time.monotonic()
                self.ready.set()
                self.event("batch_started", roster=self.roster, policy=self.policy)
                self.notify_workers()
            last_message = time.monotonic()
            reading = asyncio.create_task(receive(reader))
            while not self.done.is_set():
                wake.clear()
                task_id = self.take_task(name) if assigned is None else None
                if task_id is not None:
                    self.attempts[task_id] += 1
                    assigned = {"task_id": task_id, "attempt_id": self.attempts[task_id]}
                    image_id, data = self.images[task_id]
                    deadline = time.monotonic() + self.task_timeout
                    message = {"type": "task", **assigned, "image_id": image_id,
                               "sha256": hashlib.sha256(data).hexdigest()}
                    self.event("assigned", worker_id=name, **assigned)
                    self.tx_bytes += await asyncio.wait_for(send(writer, message, data), self.task_timeout)
                    self.image_bytes += len(data)
                timeout = self.heartbeat_timeout - (time.monotonic()-last_message)
                if assigned:
                    timeout = min(timeout, deadline-time.monotonic())
                if timeout <= 0:
                    raise TimeoutError("Task deadline expired" if assigned and time.monotonic() >= deadline
                                       else "Heartbeat timeout")
                waking = asyncio.create_task(wake.wait())
                try:
                    finished, _ = await asyncio.wait((reading, waking), timeout=timeout,
                                                     return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waking.cancel()
                    await asyncio.gather(waking, return_exceptions=True)
                if not finished:
                    raise TimeoutError("Task deadline expired" if assigned and time.monotonic() >= deadline
                                       else "Heartbeat timeout")
                if reading not in finished:
                    continue
                # Preserve the same read task across scheduling wakes: cancelling
                # readexactly midway through a frame would corrupt stream parsing.
                message, payload, size = reading.result()
                last_message = time.monotonic()
                reading = asyncio.create_task(receive(reader))
                self.rx_bytes += size
                if payload:
                    raise ValueError("Worker messages must not contain binary payloads")
                if message.get("type") == "heartbeat":
                    continue
                if message.get("type") != "result":
                    raise ValueError("Unexpected message type")
                if assigned is None or any(type(message.get(k)) is not int or message[k] != v
                                           for k, v in assigned.items()):
                    self.event("stale_result", worker_id=name, task_id=message.get("task_id"),
                               attempt_id=message.get("attempt_id"))
                    continue
                duration = message.get("processing_ms")
                task_id = assigned["task_id"]
                if (message.get("image_id") != self.images[task_id][0]
                        or message.get("status") not in ("success", "failure")
                        or not isinstance(message.get("detections"), list)
                        or type(duration) not in (int, float)
                        or not math.isfinite(duration) or duration < 0):
                    raise ValueError("Invalid result schema")
                if message["status"] == "failure":
                    raise ValueError("Worker reported failure: " + str(message.get("error", "unspecified"))[:200])
                validate_detections(message)
                self.results[task_id] = {**message, "worker_id": name,
                                        "received_s": time.monotonic()-self.started}
                if message["detections"]:
                    elapsed = self.results[task_id]["received_s"]
                    if self.first_detection_result_s is None:
                        self.first_detection_result_s = elapsed
                    if message.get("synthetic") and self.first_synthetic_sighting_s is None:
                        self.first_synthetic_sighting_s = elapsed
                self.event("completed", worker_id=name, **assigned)
                assigned = None
                self.notify_workers()
                if len(self.results) + len(self.failed) == len(self.images):
                    self.done.set()
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError, TimeoutError, ValueError,
                OSError) as exc:
            reason = type(exc).__name__ + ": " + str(exc)
            self.event("connection_lost", worker_id=worker_id, reason=reason)
        finally:
            writer.close()
            if reading:
                reading.cancel()
                await asyncio.gather(reading, return_exceptions=True)
            if worker_id:
                self.connections.pop(worker_id, None)
                self.wakes.pop(worker_id, None)
            if assigned:
                task_id = assigned["task_id"]
                if not self.done.is_set() and self.attempts[task_id] < self.max_attempts:
                    self.pending.appendleft(task_id)
                    self.event("requeued", **assigned, reason=reason)
                elif task_id not in self.results:
                    self.failed[task_id] = reason
                    self.event("task_failed", **assigned, reason=reason)
            self.notify_workers()
            if len(self.results) + len(self.failed) == len(self.images):
                self.done.set()
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            self.handlers.discard(handler)

    async def finish(self):
        try:
            await asyncio.wait_for(self.done.wait(), self.run_timeout)
        except (asyncio.TimeoutError, TimeoutError):
            self.event("run_timeout")
            self.done.set()
        ended = time.monotonic()
        self.server.close()
        await self.server.wait_closed()
        for handler in list(self.handlers):
            handler.cancel()
        await asyncio.gather(*list(self.handlers), return_exceptions=True)
        for task_id in range(len(self.images)):
            if task_id not in self.results:
                self.failed.setdefault(task_id, "run deadline before completion")
        return {"run_id": self.run_id,
                "metrics": {"completed": len(self.results), "failed": len(self.failed),
                            "batch_s": ended-self.started if self.started else None,
                            "elapsed_including_wait_s": ended-self.created,
                            "application_tx_bytes": self.tx_bytes,
                            "application_rx_bytes": self.rx_bytes,
                            "image_bytes_sent": self.image_bytes,
                            "first_detection_result_s": self.first_detection_result_s,
                            "first_synthetic_sighting_s": self.first_synthetic_sighting_s,
                            "first_result_s": min((r["received_s"] for r in self.results.values()), default=None),
                            "ignored_results": sum(e["event"] == "stale_result" for e in self.events),
                            "tasks_per_worker": {name: sum(r["worker_id"] == name for r in self.results.values())
                                                 for name in sorted(set(self.roster) | {r["worker_id"] for r in self.results.values()})},
                            "requeues": sum(e["event"] == "requeued" for e in self.events)},
                "config": {"policy": self.policy, "initial_roster": self.roster,
                           "min_workers": self.min_workers, "task_timeout_s": self.task_timeout,
                           "heartbeat_timeout_s": self.heartbeat_timeout,
                           "run_timeout_s": self.run_timeout, "max_attempts": self.max_attempts},
                "results": [self.results[k] for k in sorted(self.results)],
                "failed_tasks": self.failed, "events": self.events}


async def mock_detect(image_bytes, image_id, delay, synthetic_sightings=False):
    """Teammate replaces this function. Empty list = successful no-person result."""
    await asyncio.sleep(delay)
    if synthetic_sightings:
        # Opt-in fixture only: never fabricate detections on a user's real images.
        if (image_bytes != fixture() or not image_id.startswith("fixture-")
                or not image_id.endswith(".ppm") or not image_id[8:-4].isdigit()):
            raise ValueError("Synthetic sightings require built-in fixtures")
        if int(image_id[8:-4]) % 7 == 0:
            return [{"box_xyxy": [150, 100, 170, 120], "label": "person", "confidence": .9}]
    return []


async def run_worker(host, port, worker_id, delay=.15, disconnect_once=False,
                     reconnect=True, lifetime=70., synthetic_sightings=False):
    end = time.monotonic() + lifetime
    fault_used = False
    while time.monotonic() < end:
        writer = heartbeat = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
            lock = asyncio.Lock()
            await send(writer, {"type": "hello", "version": 1, "worker_id": worker_id}, lock=lock)
            async def beat():
                while True:
                    await send(writer, {"type": "heartbeat"}, lock=lock)
                    await asyncio.sleep(.2)
            heartbeat = asyncio.create_task(beat())
            while time.monotonic() < end:
                task, data, _ = await asyncio.wait_for(receive(reader), min(15, end-time.monotonic()))
                if task.get("type") != "task" or hashlib.sha256(data).hexdigest() != task.get("sha256"):
                    raise ValueError("Invalid task or image checksum mismatch")
                if disconnect_once and not fault_used:
                    fault_used = True
                    break
                started = time.monotonic()
                extra, status = {}, "success"
                try:
                    detections = await mock_detect(data, task["image_id"], delay, synthetic_sightings)
                except (ValueError, RuntimeError) as exc:
                    detections, status = [], "failure"
                    extra = {"error": str(exc)}
                await send(writer, {"type": "result", "task_id": task["task_id"],
                                    "attempt_id": task["attempt_id"], "image_id": task["image_id"],
                                    "status": status, "detections": detections, **extra,
                                    "synthetic": True, "detector": "mock",
                                    "processing_ms": (time.monotonic()-started)*1000}, lock=lock)
        except (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError, TimeoutError, ValueError):
            pass
        finally:
            if writer:
                writer.close()
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            if writer:
                writer.close()
                with contextlib.suppress(ConnectionError, OSError):
                    await writer.wait_closed()
        if not reconnect:
            return
        await asyncio.sleep(.5)


async def main_async(args):
    if args.mode == "worker":
        await run_worker(args.host, args.port, args.worker_id, args.delay,
                         args.disconnect_once, not args.no_reconnect, args.lifetime,
                         args.synthetic_sightings)
        return
    images = load_images(args.images, args.tasks)
    telemetry = json.loads(args.telemetry.read_text(encoding="utf-8")) if args.telemetry else {}
    worker_count = 1 if args.policy == "single" else args.workers
    delays = args.worker_delays or [.1*(i+1) for i in range(worker_count)]
    if len(delays) != worker_count:
        raise ValueError("Provide exactly one --worker-delays value per launched worker")
    coordinator = Coordinator(images, worker_count, task_timeout=args.task_timeout,
                              run_timeout=args.run_timeout, telemetry=telemetry, policy=args.policy)
    port = await coordinator.start(args.host, args.port)
    print(f"Coordinator listening on {args.host}:{port}", flush=True)
    children = []
    try:
        if args.mode == "demo":
            for i in range(worker_count):
                command = [sys.executable, str(Path(__file__).resolve()), "worker",
                           "--host", "127.0.0.1", "--port", str(port),
                           "--worker-id", f"worker-{i}", "--delay", str(delays[i]),
                           "--lifetime", str(args.run_timeout+5)]
                if args.disconnect_once and i == 0:
                    command.append("--disconnect-once")
                if args.synthetic_sightings:
                    command.append("--synthetic-sightings")
                children.append(await asyncio.create_subprocess_exec(*command))
        report = await coordinator.finish()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        args.output.with_suffix(".handoff.jsonl").write_text("".join(
            json.dumps(r, allow_nan=False)+"\n" for r in handoff_records(report, telemetry)), encoding="utf-8")
        print(json.dumps(report["metrics"], indent=2))
        print(f"Report: {args.output.resolve()}")
        return 1 if report["metrics"]["failed"] else 0
    finally:
        for child in children:
            if child.returncode is None:
                child.terminate()
            await child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["demo", "coordinator", "worker"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker-id", default="worker-1")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--policy", choices=["single", "round_robin", "next_available"], default="next_available")
    parser.add_argument("--worker-delays", nargs="+", type=float, help="Mock seconds per worker in demo mode")
    parser.add_argument("--tasks", type=int, default=20)
    parser.add_argument("--images", type=Path)
    parser.add_argument("--task-timeout", type=float, default=10.)
    parser.add_argument("--telemetry", type=Path, help="JSON camera records keyed by image_id")
    parser.add_argument("--synthetic-sightings", action="store_true", help="Opt-in fixture detections; never real sightings")
    parser.add_argument("--delay", type=float, default=.15)
    parser.add_argument("--disconnect-once", action="store_true")
    parser.add_argument("--no-reconnect", action="store_true")
    parser.add_argument("--lifetime", type=float, default=70)
    parser.add_argument("--run-timeout", type=float, default=60)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent/"results"/"network.json")
    args = parser.parse_args()
    if args.synthetic_sightings and (args.images or args.telemetry):
        parser.error("Synthetic sightings cannot be combined with real images or telemetry")
    if (not all(math.isfinite(v) and v >= 0 for v in [args.delay, *(args.worker_delays or [])])
            or not math.isfinite(args.lifetime) or args.lifetime <= 0 or args.tasks < 1 or args.workers < 1):
        parser.error("Delay must be nonnegative; lifetime and tasks must be positive")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

"""RescueSwarm scheduling prototype. Created with assistance from OpenAI Codex.

Real spawned worker processes, synthetic inference, and a modeled shared uplink.
No images, neural networks, phones, or real network traffic are used.
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import queue
import time
from collections import deque
from pathlib import Path


def worker_main(worker_id, inbox, outbox, speed, crash=False, hang=False):
    """Replace the timed inference section with the detector adapter later."""
    outbox.put({"type": "ready", "worker_id": worker_id})
    while True:
        task = inbox.get()
        if task is None:
            return
        time.sleep(max(0, task["upload_done"] - time.monotonic()))
        if crash:
            return  # Deliberate disconnect with an outstanding task.
        if hang:
            time.sleep(60)  # Coordinator must enforce its task deadline.
        started = time.monotonic()
        time.sleep(task["compute_s"] / speed)
        processing_ms = (time.monotonic() - started) * 1000
        # Synthetic fixture, NOT a detection from a real image.
        detections = ([{"box_xyxy": [100, 120, 140, 210], "confidence": 0.9,
                        "label": "person"}] if task["task_id"] % 7 == 0 else [])
        outbox.put({"type": "result", "worker_id": worker_id,
                    "task_id": task["task_id"], "attempt_id": task["attempt_id"],
                    "image_id": task["image_id"], "detections": detections,
                    "processing_ms": processing_ms, "status": "success"})


def is_current(result, assignment):
    return assignment is not None and (
        result["task_id"], result["attempt_id"]
    ) == (assignment["task_id"], assignment["attempt_id"])


def run_simulation(policy="next_available", tasks=20, speeds=(1.0, 0.5),
                   compute_s=0.06, image_bytes=100_000, bandwidth_mbps=40.0,
                   latency_ms=2.0, crash_worker=None, hang_worker=None,
                   task_timeout_s=5.0, max_attempts=3):
    """Run a finite batch; wall time starts after every worker is ready.

    Round robin gives each task a fixed home worker; retries may migrate.
    Next available assigns the oldest pending task to any idle worker.
    Local uses the first worker with zero upload bytes and latency.
    Uploads share one serialized bandwidth budget, overlapping inference.
    Result messages use IPC immediately; their bytes are counted, not delayed.
    """
    if policy not in ("local", "single", "round_robin", "next_available"):
        raise ValueError("Unknown policy")
    if tasks < 1 or not speeds or any(s <= 0 for s in speeds):
        raise ValueError("Use positive task counts and worker speeds")
    if compute_s < 0 or image_bytes < 0 or bandwidth_mbps <= 0 or latency_ms < 0:
        raise ValueError("Invalid compute or network parameters")
    if task_timeout_s <= 0 or max_attempts < 1:
        raise ValueError("Use positive deadlines and attempt limits")
    speeds = tuple(speeds[:1]) if policy in ("local", "single") else tuple(speeds)
    for index in (crash_worker, hang_worker):
        if index is not None and not 0 <= index < len(speeds):
            raise ValueError("Fault worker index is outside this scenario")
    ctx = mp.get_context("spawn")
    outbox = ctx.Queue()
    inboxes = [ctx.Queue() for _ in speeds]
    processes = [ctx.Process(target=worker_main,
                 args=(i, inboxes[i], outbox, speed, i == crash_worker,
                       i == hang_worker)) for i, speed in enumerate(speeds)]
    active = set(range(len(speeds)))
    inflight = {}
    pending = deque(range(tasks))
    attempts = [0] * tasks
    completed, failed, events = {}, {}, []
    sent_bytes = result_bytes = ignored = retries = 0
    first_result = first_sighting = None
    start = time.monotonic()

    def event(kind, **fields):
        events.append({"time_s": round(time.monotonic() - start, 6),
                       "event": kind, **fields})

    def retry(task, reason):
        nonlocal retries
        task_id = task["task_id"]
        if attempts[task_id] >= max_attempts:
            failed[task_id] = reason
            event("task_failed", task_id=task_id, reason=reason)
        else:
            pending.appendleft(task_id)
            retries += 1
            event("requeued", task_id=task_id, reason=reason)

    try:
        for process in processes:
            process.start()
        ready = set()
        startup_deadline = time.monotonic() + 20
        while len(ready) < len(processes):
            if time.monotonic() > startup_deadline:
                raise RuntimeError("Workers did not become ready within 20 seconds")
            try:
                message = outbox.get(timeout=0.1)
                if message["type"] == "ready":
                    ready.add(message["worker_id"])
            except queue.Empty:
                if any(p.exitcode is not None for p in processes):
                    raise RuntimeError("Worker exited during startup")
        startup_s = time.monotonic() - start
        start = upload_free = time.monotonic()
        while len(completed) + len(failed) < tasks:
            # Drain results before detecting departures so completed work is retained.
            while True:
                try:
                    result = outbox.get_nowait()
                except queue.Empty:
                    break
                if result["type"] != "result":
                    continue
                result_bytes += len(json.dumps(result).encode("utf-8"))
                worker_id = result["worker_id"]
                if not is_current(result, inflight.get(worker_id)):
                    ignored += 1
                    event("stale_result", task_id=result["task_id"])
                    continue
                inflight.pop(worker_id)
                if result["status"] != "success":
                    retry(result, "worker reported failure")
                    continue
                elapsed = time.monotonic() - start
                completed[result["task_id"]] = {**result, "received_s": elapsed}
                first_result = elapsed if first_result is None else first_result
                if result["detections"] and first_sighting is None:
                    first_sighting = elapsed
                event("completed", worker_id=worker_id, task_id=result["task_id"],
                      attempt_id=result["attempt_id"])
            for worker_id in sorted(active.copy()):
                assignment = inflight.get(worker_id)
                expired = assignment and time.monotonic() > assignment["deadline"]
                if not processes[worker_id].is_alive() or expired:
                    reason = "task timeout" if expired else "worker disconnected"
                    active.remove(worker_id)
                    if processes[worker_id].is_alive():
                        processes[worker_id].terminate()
                    event("worker_lost", worker_id=worker_id, reason=reason)
                    assignment = inflight.pop(worker_id, None)
                    if assignment:
                        retry(assignment, reason)
            if not active:
                for task_id in pending:
                    failed[task_id] = "no workers remaining"
                    event("task_failed", task_id=task_id, reason=failed[task_id])
                pending.clear()
                break
            for worker_id in sorted(active):
                if worker_id in inflight or not pending:
                    continue
                selected = None
                for task_id in pending:
                    home = task_id % len(speeds)
                    if (policy != "round_robin" or home == worker_id
                            or home not in active or attempts[task_id] > 0):
                        selected = task_id
                        break
                if selected is None:
                    continue
                pending.remove(selected)
                attempts[selected] += 1
                now = time.monotonic()
                task_bytes = 0 if policy == "local" else image_bytes
                upload_free = max(now, upload_free) + task_bytes * 8 / (bandwidth_mbps * 1e6)
                upload_done = upload_free + (0 if policy == "local" else latency_ms / 1000)
                assignment = {"task_id": selected, "attempt_id": attempts[selected],
                              "image_id": f"synthetic-{selected:04d}.jpg",
                              "compute_s": compute_s * (1 + (selected % 3) * 0.25),
                              "upload_done": upload_done,
                              "deadline": upload_done + task_timeout_s}
                inflight[worker_id] = assignment
                sent_bytes += task_bytes
                inboxes[worker_id].put(assignment)
                event("assigned", worker_id=worker_id, task_id=selected,
                      attempt_id=attempts[selected], upload_done_s=upload_done-start)
            if len(completed) + len(failed) < tasks:
                time.sleep(0.002)
        elapsed = time.monotonic() - start
        return {"config": {"policy": policy, "tasks": tasks, "speeds": speeds,
                           "compute_s": compute_s, "image_bytes": image_bytes,
                           "bandwidth_mbps": bandwidth_mbps, "latency_ms": latency_ms,
                           "crash_worker": crash_worker, "hang_worker": hang_worker,
                           "task_timeout_s": task_timeout_s, "max_attempts": max_attempts},
                "metrics": {"total_s": elapsed, "startup_s": startup_s,
                            "completed": len(completed), "failed": len(failed),
                            "throughput_tasks_s": len(completed) / elapsed if elapsed > 0 else None,
                            "first_result_s": first_result,
                            "first_synthetic_sighting_s": first_sighting,
                            "modeled_image_bytes": sent_bytes,
                            "modeled_upload_airtime_s": sent_bytes * 8 / (bandwidth_mbps * 1e6),
                            "result_json_bytes": result_bytes, "requeues": retries,
                            "ignored_results": ignored,
                            "tasks_per_worker": {str(i): sum(r["worker_id"] == i
                                for r in completed.values()) for i in range(len(speeds))}},
                "results": sorted(completed.values(), key=lambda r: r["task_id"]),
                "failed_tasks": failed, "events": events}
    finally:
        for i, process in enumerate(processes):
            if process.pid is not None:
                if process.is_alive():
                    inboxes[i].put(None)
                process.join(timeout=0.5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
        for channel in [*inboxes, outbox]:
            channel.close()
            channel.join_thread()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--speeds", type=float, nargs="+", default=[1.0, 0.5])
    parser.add_argument("--compute-ms", type=float, default=60)
    parser.add_argument("--image-kb", type=float, default=100)
    parser.add_argument("--bandwidth-mbps", type=float, default=40)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    scenarios = [("single", "single", None), ("round_robin", "round_robin", None),
                 ("next_available", "next_available", None),
                 ("disconnect", "next_available", 0)]
    for repeat in range(1, args.repeats + 1):
        for name, policy, crash in scenarios:
            report = run_simulation(policy, args.tasks, args.speeds,
                                    compute_s=args.compute_ms/1000,
                                    image_bytes=int(args.image_kb*1000),
                                    bandwidth_mbps=args.bandwidth_mbps,
                                    crash_worker=crash)
            (args.output / f"{name}-{repeat}.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8")
            row = {"scenario": name, "repeat": repeat, **report["metrics"]}
            row["tasks_per_worker"] = json.dumps(row["tasks_per_worker"])
            rows.append(row)
            print(f"{name:16s} run {repeat}: {row['total_s']:.3f}s, "
                  f"{row['completed']}/{args.tasks} completed, {row['requeues']} requeued")
    with (args.output / "summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    mp.freeze_support()
    main()

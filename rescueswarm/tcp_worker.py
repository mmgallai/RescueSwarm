"""Connect a Worker to the coordinator over TCP, following the coordinator's protocol v1.

Every frame is a 4-byte big-endian header length, a UTF-8 JSON header, then `payload_bytes`
raw bytes (the image, for tasks). The worker says hello, sends a heartbeat every 0.2 s for as
long as it is connected, and answers each task with one result. Inference runs in a thread so
heartbeats keep flowing; otherwise the coordinator would think a busy worker had died.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import struct

from rescueswarm.messages import DetectionTask
from rescueswarm.worker import Worker

PROTOCOL_VERSION = 1
MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 16 * 1024 * 1024
HEARTBEAT_INTERVAL_S = 0.2

log = logging.getLogger(__name__)

CONNECTION_ERRORS = (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError,
                     TimeoutError, ValueError)


async def send_frame(writer: asyncio.StreamWriter, message: dict, lock: asyncio.Lock, payload: bytes = b"") -> None:
    """Send one frame. The lock keeps heartbeats from interleaving with a result mid-frame."""
    header = json.dumps({**message, "payload_bytes": len(payload)}, allow_nan=False).encode()
    if len(header) > MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ValueError("message exceeds protocol limits")
    async with lock:
        writer.write(struct.pack("!I", len(header)) + header + payload)
        await writer.drain()


async def receive_frame(reader: asyncio.StreamReader) -> tuple[dict, bytes]:
    """Read one frame, rejecting anything that breaks the protocol limits."""
    (length,) = struct.unpack("!I", await reader.readexactly(4))
    if not 0 < length <= MAX_HEADER:
        raise ValueError(f"invalid header length {length}")
    header = json.loads(await reader.readexactly(length))
    if not isinstance(header, dict):
        raise ValueError("header must be a JSON object")
    size = header.get("payload_bytes")
    if type(size) is not int or not 0 <= size <= MAX_PAYLOAD:
        raise ValueError(f"invalid payload length {size!r}")
    return header, await reader.readexactly(size)


async def send_heartbeats(writer: asyncio.StreamWriter, lock: asyncio.Lock) -> None:
    while True:
        await send_frame(writer, {"type": "heartbeat"}, lock)
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


async def serve_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                           worker_id: str, worker: Worker) -> None:
    """Handle tasks on one open connection until the coordinator closes it or something breaks."""
    lock = asyncio.Lock()
    await send_frame(writer, {"type": "hello", "version": PROTOCOL_VERSION, "worker_id": worker_id}, lock)
    heartbeat = asyncio.create_task(send_heartbeats(writer, lock))
    try:
        while True:
            header, payload = await receive_frame(reader)
            if header.get("type") != "task":
                raise ValueError(f"unexpected message type {header.get('type')!r}")
            # A checksum mismatch raises here; dropping the connection lets the coordinator retry.
            task = DetectionTask.from_wire(header, payload)
            result = await asyncio.to_thread(worker.handle, task)
            await send_frame(writer, result.to_wire(), lock)
            log.info("task %s (%s): %s, %d people, %.0f ms", task.task_id, task.image_id,
                     result.status, len(result.detections), result.processing_ms)
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        writer.close()
        with contextlib.suppress(*CONNECTION_ERRORS):
            await writer.wait_closed()


async def run_tcp_worker(host: str, port: int, worker_id: str, worker: Worker,
                         reconnect: bool = True, retry_delay_s: float = 1.0) -> None:
    """Connect and serve; with `reconnect`, keep coming back after the connection ends."""
    while True:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 5)
            log.info("connected to %s:%d as %s", host, port, worker_id)
            await serve_connection(reader, writer, worker_id, worker)
        except asyncio.IncompleteReadError:
            log.info("coordinator closed the connection")
        except CONNECTION_ERRORS as exc:
            log.warning("connection ended: %s: %s", type(exc).__name__, exc)
        if not reconnect:
            return
        await asyncio.sleep(retry_delay_s)

"""Tests against a minimal fake coordinator speaking the same TCP v1 framing."""
import asyncio
import hashlib
import struct
import time

import cv2
import numpy as np
import pytest

from rescueswarm.detector import DetectorOutput
from rescueswarm.messages import Detection
from rescueswarm.tcp_worker import receive_frame, run_tcp_worker, send_frame
from rescueswarm.worker import Worker

IMAGE = cv2.imencode(".jpg", np.full((48, 64, 3), 120, np.uint8))[1].tobytes()


class FakeDetector:
    name, config = "fake", {"model": "fake"}

    def __init__(self, delay_s=0.0):
        self.delay_s = delay_s

    def detect(self, image):
        time.sleep(self.delay_s)  # blocking, like real inference
        return DetectorOutput([Detection((1, 2, 30, 40), 0.9)], 1.0)


def task_frame(task_id=5, sha256=None):
    return {"type": "task", "task_id": task_id, "attempt_id": 1, "image_id": "img.jpg",
            "sha256": sha256 or hashlib.sha256(IMAGE).hexdigest()}


async def with_coordinator(coordinator, detector):
    """Run `coordinator(reader, writer)` as the server and one worker against it."""
    done = asyncio.get_running_loop().create_future()

    async def handle(reader, writer):
        try:
            done.set_result(await coordinator(reader, writer))
        except Exception as exc:
            done.set_exception(exc)
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    worker = asyncio.create_task(run_tcp_worker("127.0.0.1", port, "w1", Worker(detector), reconnect=False))
    try:
        return await asyncio.wait_for(done, 10)
    finally:
        await asyncio.wait_for(worker, 10)
        server.close()
        await server.wait_closed()


async def next_non_heartbeat(reader):
    beats = 0
    while True:
        header, payload = await receive_frame(reader)
        if header["type"] != "heartbeat":
            return header, payload, beats
        beats += 1


def test_hello_task_result_round_trip():
    async def coordinator(reader, writer):
        hello, _, _ = await next_non_heartbeat(reader)
        await send_frame(writer, task_frame(), asyncio.Lock(), IMAGE)
        result, payload, _ = await next_non_heartbeat(reader)
        return hello, result, payload

    hello, result, payload = asyncio.run(with_coordinator(coordinator, FakeDetector()))
    assert hello == {"type": "hello", "version": 1, "worker_id": "w1", "payload_bytes": 0}
    assert (result["type"], result["task_id"], result["status"]) == ("result", 5, "success")
    assert result["detections"] == [{"label": "person", "confidence": 0.9, "box_xyxy": [1, 2, 30, 40]}]
    assert result["image_size"] == {"width": 64, "height": 48}
    assert result["payload_bytes"] == 0 and payload == b""


def test_heartbeats_continue_during_slow_inference():
    async def coordinator(reader, writer):
        await next_non_heartbeat(reader)  # hello
        await send_frame(writer, task_frame(), asyncio.Lock(), IMAGE)
        result, _, beats = await next_non_heartbeat(reader)
        return result, beats

    result, beats = asyncio.run(with_coordinator(coordinator, FakeDetector(delay_s=1.0)))
    assert result["status"] == "success"
    assert beats >= 3  # ~5 expected in 1 s at 0.2 s intervals


def test_corrupted_image_makes_worker_disconnect_without_answering():
    async def coordinator(reader, writer):
        await next_non_heartbeat(reader)  # hello
        await send_frame(writer, task_frame(sha256="0" * 64), asyncio.Lock(), IMAGE)
        try:
            await next_non_heartbeat(reader)
        except asyncio.IncompleteReadError:
            return "disconnected"
        return "answered"

    assert asyncio.run(with_coordinator(coordinator, FakeDetector())) == "disconnected"


def test_receive_frame_rejects_oversized_header():
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!I", 10 * 1024 * 1024))
        await receive_frame(reader)

    with pytest.raises(ValueError, match="header length"):
        asyncio.run(run())


def test_receive_frame_rejects_missing_payload_length():
    async def run():
        reader = asyncio.StreamReader()
        header = b'{"type": "task"}'
        reader.feed_data(struct.pack("!I", len(header)) + header)
        await receive_frame(reader)

    with pytest.raises(ValueError, match="payload length"):
        asyncio.run(run())

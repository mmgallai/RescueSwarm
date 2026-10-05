"""Real loopback TCP tests. Created with OpenAI Codex assistance."""
import asyncio
import struct
import unittest
from network import Coordinator, fixture, receive, run_worker, send, MAX_HEADER, mock_detect


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_batch_is_rejected(self):
        with self.assertRaises(ValueError):
            Coordinator([])

    async def test_more_workers_than_tasks_with_synthetic_sighting(self):
        images = [("fixture-0000.ppm", fixture())]
        coordinator = Coordinator(images, min_workers=3, run_timeout=5)
        port = await coordinator.start()
        workers = [asyncio.create_task(run_worker("127.0.0.1", port, str(i), .01,
                                                  synthetic_sightings=True)) for i in range(3)]
        try:
            report = await coordinator.finish()
            self.assertEqual(report["metrics"]["completed"], 1)
            self.assertIsNotNone(report["metrics"]["first_synthetic_sighting_s"])
            self.assertEqual(len(report["results"][0]["detections"]), 1)
            self.assertTrue(report["results"][0]["synthetic"])
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def test_mock_sightings_are_opt_in_and_fixture_only(self):
        self.assertEqual(await mock_detect(fixture(), "fixture-0000.ppm", 0), [])
        with self.assertRaises(ValueError):
            await mock_detect(b"real-image-placeholder", "image.jpg", 0, True)

    async def test_transfer_and_reconnect(self):
        coordinator = Coordinator([(f"{i}.ppm", fixture()) for i in range(12)], run_timeout=8)
        port = await coordinator.start()
        workers = [asyncio.create_task(run_worker("127.0.0.1", port, "a", .03, True)),
                   asyncio.create_task(run_worker("127.0.0.1", port, "b", .1))]
        try:
            report = await coordinator.finish()
            self.assertEqual(report["metrics"]["completed"], 12)
            self.assertEqual(report["metrics"]["failed"], 0)
            self.assertIsNone(report["metrics"]["first_synthetic_sighting_s"])
            self.assertGreaterEqual(report["metrics"]["requeues"], 1)
            self.assertEqual(len({r["task_id"] for r in report["results"]}), 12)
            self.assertEqual(report["metrics"]["image_bytes_sent"], 13*len(fixture()))
            self.assertGreaterEqual(sum(e["event"] == "connected" and e["worker_id"] == "a"
                                        for e in report["events"]), 2)
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def test_heartbeat_does_not_extend_task_deadline(self):
        coordinator = Coordinator([("x.ppm", fixture())], min_workers=1,
                                  task_timeout=.3, run_timeout=3, max_attempts=1)
        port = await coordinator.start()
        worker = asyncio.create_task(run_worker("127.0.0.1", port, "slow", 2))
        try:
            report = await coordinator.finish()
            self.assertEqual(report["metrics"]["failed"], 1)
            self.assertLess(report["metrics"]["batch_s"], 1.5)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def test_absent_workers_is_bounded(self):
        coordinator = Coordinator([("x.ppm", fixture())], run_timeout=.1)
        await coordinator.start()
        report = await coordinator.finish()
        self.assertEqual(report["metrics"]["failed"], 1)
        self.assertIsNone(report["metrics"]["batch_s"])

    async def test_missing_heartbeat_and_stale_result(self):
        coordinator = Coordinator([("x.ppm", fixture())], min_workers=1,
                                  heartbeat_timeout=.15, run_timeout=2, max_attempts=1)
        port = await coordinator.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await send(writer, {"type": "hello", "version": 1, "worker_id": "silent"})
        task, _, _ = await receive(reader)
        await send(writer, {"type": "result", "task_id": task["task_id"], "attempt_id": 0})
        report = await coordinator.finish()
        self.assertEqual(report["metrics"]["failed"], 1)
        self.assertTrue(any(e["event"] == "stale_result" for e in report["events"]))
        writer.close()
        await writer.wait_closed()

    async def test_fragmented_frame_and_oversize_rejection(self):
        reader = asyncio.StreamReader()
        encoded = b'{"payload_bytes":3,"type":"test"}'
        packet = struct.pack("!I", len(encoded)) + encoded + b"abc"
        async def fragmented():
            for byte in packet:
                reader.feed_data(bytes([byte]))
                await asyncio.sleep(0)
        feeding = asyncio.create_task(fragmented())
        _, payload, size = await receive(reader)
        await feeding
        self.assertEqual(payload, b"abc")
        self.assertEqual(size, len(packet))
        bad = asyncio.StreamReader()
        bad.feed_data(struct.pack("!I", MAX_HEADER+1))
        with self.assertRaises(ValueError):
            await receive(bad)


if __name__ == "__main__":
    unittest.main()

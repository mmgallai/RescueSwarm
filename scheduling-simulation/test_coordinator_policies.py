"""Coordinator acceptance tests using real loopback TCP sockets."""
import asyncio
import unittest
from network import Coordinator, fixture, run_worker, send, receive, handoff_records, validate_detections


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    async def batch(self, policy, delays, disconnect=False, timeout=3):
        c = Coordinator([(str(i), fixture()) for i in range(12)], min_workers=len(delays),
                        policy=policy, task_timeout=timeout, run_timeout=8)
        port = await c.start()
        workers = [asyncio.create_task(run_worker("127.0.0.1", port, name, delay,
                   disconnect_once=disconnect and name == "a", reconnect=False))
                   for name, delay in reversed(list(delays.items()))]
        try:
            report = await c.finish()
            self.assertEqual(report["metrics"]["completed"], 12)
            self.assertEqual(report["metrics"]["failed"], 0)
            self.assertEqual(len({r["task_id"] for r in report["results"]}), 12)
            return report
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def test_round_robin_fixed_sorted_roster(self):
        r = await self.batch("round_robin", {"a": .01, "b": .05})
        self.assertEqual(r["config"]["initial_roster"], ["a", "b"])
        for result in r["results"]:
            self.assertEqual(result["worker_id"], ["a", "b"][result["task_id"] % 2])

    async def test_next_available_balances_unequal_workers(self):
        r = await self.batch("next_available", {"a": .01, "b": .1})
        counts = r["metrics"]["tasks_per_worker"]
        self.assertGreater(counts["a"], counts["b"])

    async def test_single(self):
        r = await self.batch("single", {"a": .01})
        self.assertEqual(r["metrics"]["tasks_per_worker"], {"a": 12})

    async def test_round_robin_lost_owner_does_not_strand_tasks(self):
        r = await self.batch("round_robin", {"a": .01, "b": .03}, disconnect=True)
        self.assertEqual(r["metrics"]["requeues"], 1)
        self.assertEqual(r["results"][0]["attempt_id"], 2)

    async def test_stalled_worker_with_heartbeats_reassigned(self):
        r = await self.batch("round_robin", {"a": 2, "b": .02}, timeout=.4)
        self.assertEqual(r["metrics"]["requeues"], 1)
        self.assertEqual(r["results"][0]["attempt_id"], 2)

    async def test_slow_healthy_worker_keeps_task(self):
        r = await self.batch("round_robin", {"a": .25, "b": .01}, timeout=1)
        self.assertEqual(r["metrics"]["requeues"], 0)

    async def test_duplicate_and_late_attempt_are_ignored(self):
        c = Coordinator([("a", fixture()), ("b", fixture())], min_workers=1, run_timeout=3)
        port = await c.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await send(writer, {"type": "hello", "version": 1, "worker_id": "a"})
        first, _, _ = await receive(reader)
        def result(task):
            return {"type": "result", **{k: task[k] for k in ("task_id", "attempt_id", "image_id")},
                    "status": "success", "detections": [], "processing_ms": 1}
        await send(writer, result(first))
        second, _, _ = await receive(reader)
        await send(writer, result(first))
        await send(writer, {**result(second), "attempt_id": 0})
        await send(writer, result(second))
        report = await c.finish()
        writer.close()
        await writer.wait_closed()
        self.assertEqual(report["metrics"]["ignored_results"], 2)
        exported = handoff_records(report, {})
        self.assertEqual(len(exported), 2)
        self.assertIsNone(exported[0]["camera_telemetry"])
        self.assertIsNone(exported[0]["synthetic"])

    async def test_invalid_detection_retries_on_survivor(self):
        c = Coordinator([("a", fixture())], min_workers=2, policy="round_robin", run_timeout=3)
        port = await c.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await send(writer, {"type": "hello", "version": 1, "worker_id": "a"})
        worker = asyncio.create_task(run_worker("127.0.0.1", port, "b", .01, reconnect=False))
        task, _, _ = await receive(reader)
        await send(writer, {"type": "result", "task_id": 0, "attempt_id": task["attempt_id"],
                           "image_id": "a", "status": "success", "processing_ms": 1,
                           "detections": [{"box_xyxy": [0, 0, 10, 10], "label": "person", "confidence": 2}]})
        report = await c.finish()
        writer.close()
        await writer.wait_closed()
        await worker
        self.assertEqual(report["metrics"]["completed"], 1)
        self.assertEqual(report["results"][0]["attempt_id"], 2)

    def test_schema_rejects_nonfinite_and_out_of_bounds(self):
        for box in ([0, 0, float("nan"), 5], [0, 0, 30, 5], [2, 0, 1, 5]):
            with self.assertRaises(ValueError):
                validate_detections({"image_size": {"width": 20, "height": 20},
                    "detections": [{"label": "person", "confidence": .9, "box_xyxy": box}]})

    async def test_reconnected_worker_cannot_complete_old_attempt(self):
        c = Coordinator([("a", fixture())], min_workers=1, run_timeout=3)
        port = await c.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await send(writer, {"type": "hello", "version": 1, "worker_id": "a"})
        first, _, _ = await receive(reader)
        writer.close()
        await writer.wait_closed()
        for _ in range(100):
            if c.attempts[0] == 1 and not c.connections:
                break
            await asyncio.sleep(.01)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await send(writer, {"type": "hello", "version": 1, "worker_id": "a"})
        second, _, _ = await receive(reader)
        self.assertEqual(second["attempt_id"], 2)
        for task in (first, second):
            await send(writer, {"type": "result", "task_id": 0, "attempt_id": task["attempt_id"],
                               "image_id": "a", "status": "success", "processing_ms": 1, "detections": []})
        report = await c.finish()
        writer.close()
        await writer.wait_closed()
        self.assertEqual(report["metrics"]["ignored_results"], 1)
        self.assertEqual(report["results"][0]["attempt_id"], 2)

    async def test_duplicate_worker_name_does_not_evict_original(self):
        c = Coordinator([("a", fixture())], min_workers=1, run_timeout=3)
        port = await c.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        hello = {"type": "hello", "version": 1, "worker_id": "a"}
        await send(writer, hello)
        task, _, _ = await receive(reader)
        other_reader, other_writer = await asyncio.open_connection("127.0.0.1", port)
        await send(other_writer, hello)
        self.assertEqual(await asyncio.wait_for(other_reader.read(), 1), b"")
        self.assertIn("a", c.connections)
        other_writer.close()
        await other_writer.wait_closed()
        await send(writer, {"type": "result", "task_id": 0, "attempt_id": task["attempt_id"],
                           "image_id": "a", "status": "success", "processing_ms": 1, "detections": []})
        report = await c.finish()
        writer.close()
        await writer.wait_closed()
        self.assertEqual(report["metrics"]["completed"], 1)


if __name__ == "__main__":
    unittest.main()

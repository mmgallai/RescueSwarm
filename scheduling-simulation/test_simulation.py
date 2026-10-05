"""Coordinator correctness checks. Created with assistance from OpenAI Codex."""
import unittest
from simulation import is_current, run_simulation


class SimulationTests(unittest.TestCase):
    def test_local_baseline_has_no_upload_cost(self):
        report = self.run_case(policy="local", image_bytes=1_000_000, bandwidth_mbps=.01)
        self.assert_complete(report)
        self.assertEqual(report["metrics"]["modeled_image_bytes"], 0)
        self.assertEqual(report["metrics"]["modeled_upload_airtime_s"], 0)

    def test_empty_batch_is_rejected(self):
        with self.assertRaises(ValueError):
            run_simulation(tasks=0)

    def test_more_workers_than_tasks(self):
        for policy in ("round_robin", "next_available"):
            report = self.run_case(tasks=1, speeds=(1, 1, 1), policy=policy)
            self.assertEqual(report["metrics"]["completed"], 1)
            self.assertEqual(report["metrics"]["failed"], 0)

    def run_case(self, **overrides):
        config = dict(tasks=8, compute_s=0.01, image_bytes=1000)
        config.update(overrides)
        return run_simulation(**config)

    def assert_complete(self, report):
        self.assertEqual(report["metrics"]["completed"], 8)
        self.assertEqual(report["metrics"]["failed"], 0)
        self.assertEqual([r["task_id"] for r in report["results"]], list(range(8)))

    def test_baselines_and_balancing(self):
        for policy in ("single", "round_robin", "next_available"):
            with self.subTest(policy=policy):
                report = self.run_case(policy=policy)
                self.assert_complete(report)
                if policy == "round_robin":
                    self.assertEqual(report["metrics"]["tasks_per_worker"], {"0": 4, "1": 4})

    def test_disconnect_reassigns_with_new_attempt(self):
        report = self.run_case(crash_worker=0)
        self.assert_complete(report)
        self.assertEqual(report["results"][0]["attempt_id"], 2)
        self.assertEqual(report["results"][0]["worker_id"], 1)
        self.assertEqual(report["metrics"]["modeled_image_bytes"], 9000)

    def test_stalled_worker_times_out(self):
        # Leave room for process scheduling on shared CI runners. The injected
        # hung worker never completes, regardless of this deadline's duration.
        report = self.run_case(hang_worker=0, task_timeout_s=2)
        self.assert_complete(report)
        self.assertTrue(any(e.get("reason") == "task timeout" and e.get("worker_id") == 0
                            for e in report["events"]))

    def test_no_workers_finishes_with_explicit_failures(self):
        report = self.run_case(speeds=(1,), crash_worker=0)
        self.assertEqual(report["metrics"]["failed"], 8)
        self.assertEqual(report["metrics"]["completed"], 0)

    def test_attempt_limit(self):
        report = self.run_case(crash_worker=0, max_attempts=1)
        self.assertEqual(report["metrics"]["failed"], 1)
        self.assertEqual(report["metrics"]["completed"], 7)

    def test_reject_old_and_duplicate_results(self):
        result = {"task_id": 1, "attempt_id": 1}
        self.assertFalse(is_current(result, {"task_id": 1, "attempt_id": 2}))
        self.assertFalse(is_current(result, None))
        self.assertTrue(is_current(result, result))


if __name__ == "__main__":
    unittest.main()

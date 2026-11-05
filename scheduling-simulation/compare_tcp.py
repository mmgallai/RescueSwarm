"""Repeated mock scheduling measurements with separate processes over loopback TCP."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=Path("results/tcp-comparison-20261004"))
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--tasks", type=int, default=20)
    args = p.parse_args()
    if args.repeats < 1 or args.tasks < 1:
        p.error("repeats and tasks must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    policies = ["single", "round_robin", "next_available"]
    for profile, delays in {"equal": [.05, .05], "mixed": [.05, .15]}.items():
        for repeat in range(args.repeats):
            for policy in policies[repeat % 3:]+policies[:repeat % 3]:
                output = args.output/f"{profile}-{policy}-{repeat+1}.json"
                command = [sys.executable, str(Path(__file__).with_name("network.py")), "demo",
                           "--port", "0", "--policy", policy, "--tasks", str(args.tasks),
                           "--synthetic-sightings", "--output", str(output), "--worker-delays",
                           *map(str, delays[:1] if policy == "single" else delays)]
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=80)
                report = json.loads(output.read_text())
                m = report["metrics"]
                assert m["completed"] == args.tasks and m["failed"] == 0
                assert len({r["task_id"] for r in report["results"]}) == args.tasks
                rows.append({"profile": profile, "policy": policy, "repeat": repeat+1,
                             **{k: m[k] for k in ("batch_s", "first_result_s", "first_synthetic_sighting_s",
                                  "application_tx_bytes", "application_rx_bytes", "requeues")}})
    with (args.output/"runs.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# TCP scheduling comparison", "",
             "Measured on one Windows laptop using separate Python worker processes and loopback TCP.",
             "Mock processing uses sleep, not inference. Synthetic detections are test fixtures.",
             "Equal workers: 50/50 ms. Mixed workers: 50/150 ms. Single uses the 50 ms worker.",
             f"Each batch uses {args.tasks} identical-size images; {args.repeats} repetitions per configuration.",
             "Policy execution order rotates between repetitions. Startup wait is excluded from batch time.",
             "", "| Profile | Policy | Mean batch seconds | Sample SD |", "|---|---|---:|---:|"]
    for profile in ("equal", "mixed"):
        for policy in policies:
            times = [r["batch_s"] for r in rows if r["profile"] == profile and r["policy"] == policy]
            lines.append(f"| {profile} | {policy} | {statistics.mean(times):.3f} | {statistics.stdev(times) if len(times)>1 else 0:.3f} |")
    lines += ["", "Raw JSON contains per-worker counts, event timelines and accepted results. JSONL files are teammate handoffs.",
              "Byte totals include application framing and retries, but exclude TCP/IP and Wi-Fi headers.",
              "First synthetic sighting is not time to a correct real detection. No claim about phone speed or physical Wi-Fi follows from this test."]
    (args.output/"REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

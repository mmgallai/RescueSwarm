"""Run a YOLO26n worker that connects to the RescueSwarm coordinator over TCP.

Start the coordinator first (scheduling-simulation/network.py on the coordinator branch), e.g.
    python network.py coordinator --host 0.0.0.0 --workers 2 --images <folder>
then, on each worker machine:
    python scripts/tcp_worker.py --host <coordinator IP> --worker-id laptop-1
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from rescueswarm.detector import DEFAULT_IMGSZ, PersonDetector
from rescueswarm.tcp_worker import run_tcp_worker
from rescueswarm.worker import Worker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker-id", required=True, help="unique name for this worker")
    parser.add_argument("--weights", default="yolo26n.pt")
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--no-reconnect", action="store_true", help="exit when the connection ends")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    detector = PersonDetector(args.weights, imgsz=args.imgsz, conf=args.conf)
    detector.warmup()  # load the model before connecting, so the first task isn't slow
    try:
        asyncio.run(run_tcp_worker(args.host, args.port, args.worker_id, Worker(detector),
                                   reconnect=not args.no_reconnect))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

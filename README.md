# RescueSwarm
Distributed smartphone computing for drone-based search and rescue without internet access.

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Dataset

We use [SAR-DAG_raycast](https://repository.inf.uniri.hr/object/infri:1071). The repository
requires a CAPTCHA, so download the zip in a browser from
https://repository.inf.uniri.hr/object/infri:1071/FILE0, then unpack it into `data/sar-dag/`:

```bash
python scripts/prepare_dataset.py ~/Downloads/<downloaded-file>.zip
```

## Run the detector locally

Runs dataset images through one worker on this machine (no coordinator needed) and prints
each result plus timing. The YOLO26n weights download automatically on first use.

```bash
python scripts/run_local.py --flight vinograd
```

## Connect workers to the coordinator

The worker speaks the coordinator's TCP v1 protocol (see `scheduling-simulation/README.md` on
the `mohamed/python-coordinator` branch). Start the coordinator, then one worker per machine:

```bash
python network.py coordinator --host 0.0.0.0 --workers 2 --images <folder>   # coordinator branch
python scripts/tcp_worker.py --host <coordinator IP> --worker-id laptop-1
```

## Export the model for the iOS app

`coremltools` needs Python 3.12 and PyTorch 2.7, so the export uses its own environment.
It writes `models/yolo26n-1280.mlpackage` and checks it against the PyTorch detector.

```bash
/opt/homebrew/bin/python3.12 -m venv .venv-export
.venv-export/bin/pip install -e . coremltools "torch==2.7.0" "torchvision==0.22.0"
.venv-export/bin/python scripts/export_coreml.py
```

## Tests

```bash
pytest
```

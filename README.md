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

## Tests

```bash
pytest
```

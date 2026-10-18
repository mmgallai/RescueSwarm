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

## Tests

```bash
pytest
```

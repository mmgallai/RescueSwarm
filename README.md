# RescueSwarm
Distributed smartphone computing for drone-based search and rescue without internet access.

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the tests:

```bash
pytest
```

## Geolocation

See [GEOLOCATION.md](GEOLOCATION.md) for the input contract, offline terrain handling, Swift package integration and regression tests.

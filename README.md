# RescueSwarm
Distributed smartphone computing for drone-based search and rescue without internet access.

## Integrated iPhone app

Open `rescue-swarm-ios/RescueSwarm.xcodeproj`. The integration branch connects the
Swift coordinator, Core ML person detector and geolocation package. See
[the integration guide](rescue-swarm-ios/INTEGRATION.md) for image telemetry import,
saved sightings, assumptions and physical-device verification.

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

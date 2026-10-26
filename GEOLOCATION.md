# Geolocation contract

The Python and Swift implementations estimate a person sighting and format CoT XML.
They do not send it to TAK or attach it to the app automatically.

## Inputs and assumptions

- Successful worker result with image dimensions and person boxes in full-image, upright pixels. For tiled detection, first map boxes back to the original image.
- Camera latitude/longitude, horizontal/vertical FOV, and camera heading clockwise from north (not aircraft heading unless they coincide).
- `altitude_m` / `altitudeMeters` is height above terrain directly beneath the camera (AGL). GPS/sea-level altitude and height relative to takeoff are not interchangeable with AGL.
- Nadir camera only: pitch -90 degrees, roll 0. The optional pitch/roll arguments reject unsupported attitudes. Defaults are assumptions, not telemetry verification. A tilted SAR-DAG image must not be passed as nadir.
- The ground anchor is box bottom-center. This is an approximation that needs validation for overhead views, prone people and imperfect detections.
- Local projection is bounded to at most 10 km along the ray. Terrain search samples at 1–5 m intervals for at most 2,000 steps, then refines the first sampled intersection to a 1 cm distance bracket. This is numerical precision, not real-world GPS accuracy; narrow terrain features between samples can be missed.

## Terrain and height references

Flat-ground mode is the offline default. There is no `srtm` import or automatic download. Supply an elevation function backed by your own cached map to enable terrain mode.

Provider values must use one reference: `msl` (default) or `hae`. MSL means height above mean sea level. HAE means height above the ellipsoid. If using MSL, supply the local geoid offset to convert: **HAE = MSL + geoid offset**. One scalar offset assumes negligible geoid variation over this local area. Without that offset, horizontal position can still be estimated, but the exported HAE stays unknown. For flat ground, a known absolute ground HAE may be supplied explicitly.

Unavailable elevation at the camera falls back to flat ground with a warning; the CoT remarks name the assumption. Invalid non-finite elevations, unavailable terrain along the ray, unresolved terrain discontinuities, and absence of an intersection are errors, not successful sightings. Do not publish a marker when geolocation fails.

Unknown HAE and unmeasured horizontal/vertical error use `9999999.0`, as shown in the [official TAK CoT examples](https://github.com/deptofdefense/AndroidTacticalAssaultKit-CIV/blob/main/takcot/examples/Drawing%20Shapes%20-%20Telestration.cot). No measured accuracy claim is made.

## Sighting identity

An omitted UID creates a new UUID for each call. For retries/updates of the same sighting, the coordinator must retain and reuse an explicit UID. Distinct people must have distinct UIDs. A run ID + image ID + detection index can identify an image sighting, but does not track the same person across images.

## Swift integration

Add `swift/` as a local Swift package and depend on `RescueSwarmGeolocation`. The standalone package has no detector or networking dependency. It accepts the existing result JSON from Evi's worker; unknown extra fields are ignored:

```swift
import RescueSwarmGeolocation

let result = try JSONDecoder().decode(
    RescueSwarmGeolocation.DetectionResult.self, from: acceptedResultJSON)
let xml = try geolocatePerson(result,
    cameraLatitude: telemetryLatitude,
    cameraLongitude: telemetryLongitude,
    altitudeMeters: verifiedAGL,
    horizontalFOVDegrees: horizontalFOV,
    verticalFOVDegrees: verticalFOV,
    headingDegrees: cameraHeading,
    cameraPitchDegrees: cameraPitch,
    cameraRollDegrees: cameraRoll,
    uid: retainedSightingUID)
```

Call for each detection index after the coordinator has accepted the result. Run terrain lookups off the main actor. The coordinator still needs the image-to-telemetry mapping and a configured TAK transport. This change does not invent telemetry or send network messages.

## Tests

From repository root:

```text
python -m pip install pytest
python -m pytest
cd swift
swift test
```

The Python geometry tests require no detector installation. Swift tests cover geometry, heights, identity, error paths and decoding a worker result. Tests ran on Windows/Python and Linux ARM64/Swift 6.0.3. iOS integration and TAK ingestion still need device testing.

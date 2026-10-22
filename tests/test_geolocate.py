import datetime
import warnings
from xml.etree import ElementTree as ET

import pytest

import rescueswarm.geolocate as geolocate
from rescueswarm.geolocate import geolocate_person
from rescueswarm.messages import Detection, DetectionResult, DetectionTask


def result_with_box(box):
    task = DetectionTask(1, 1, "frame.jpg", b"image", "unused")
    return DetectionResult.success(task, [Detection(box, 0.9)], 1.0, "test", (640, 480))


def parse_cot_point(cot_xml: str):
    """Helper to extract latitude, longitude, and HAE from CoT XML."""
    root = ET.fromstring(cot_xml)
    point = root.find("point")
    lat = float(point.get("lat"))
    lon = float(point.get("lon"))
    hae = float(point.get("hae"))
    return lat, lon, hae


def test_centered_person_box_maps_to_camera_location_flat():
    result = result_with_box((300, 200, 340, 240))

    # Explicitly pass a flat 0m elevation function to test base geolocation
    cot_xml = geolocate_person(
        result,
        camera_latitude=37.0,
        camera_longitude=-122.0,
        altitude_m=100,
        horizontal_fov_deg=60,
        vertical_fov_deg=45,
        elevation_fn=lambda lat, lon: 0.0,
    )

    lat, lon, hae = parse_cot_point(cot_xml)
    assert lat == pytest.approx(37.0)
    assert lon == pytest.approx(-122.0)
    assert hae == pytest.approx(0.0)
    assert "90.0%" in cot_xml


def test_heading_rotates_image_right_toward_south_when_facing_east():
    result = result_with_box((460, 200, 500, 240))

    cot_xml = geolocate_person(
        result,
        camera_latitude=0.0,
        camera_longitude=0.0,
        altitude_m=100,
        horizontal_fov_deg=90,
        vertical_fov_deg=60,
        heading_deg=90,
        elevation_fn=None,
    )

    latitude, longitude, _ = parse_cot_point(cot_xml)
    assert latitude < 0
    assert longitude == pytest.approx(0.0)


def test_none_elevation_function_uses_flat_ground_without_warning():
    result = result_with_box((460, 200, 500, 240))

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        cot_xml = geolocate_person(
            result,
            camera_latitude=0.0,
            camera_longitude=0.0,
            altitude_m=100,
            horizontal_fov_deg=90,
            vertical_fov_deg=60,
            elevation_fn=None,
        )

    latitude, longitude, hae = parse_cot_point(cot_xml)
    assert latitude == pytest.approx(0.0)
    assert longitude > 0.0
    assert hae == pytest.approx(0.0)
    assert caught_warnings == []


def test_wire_message_uses_selected_detection_and_confidence():
    message = result_with_box((300, 200, 340, 240)).to_wire()
    message["detections"].append({
        "label": "person",
        "confidence": 0.75,
        "box_xyxy": [460, 200, 500, 240],
    })

    cot_xml = geolocate_person(
        message,
        camera_latitude=0.0,
        camera_longitude=0.0,
        altitude_m=100,
        horizontal_fov_deg=90,
        vertical_fov_deg=60,
        detection_index=1,
        elevation_fn=None,
    )

    _, longitude, _ = parse_cot_point(cot_xml)
    root = ET.fromstring(cot_xml)
    assert longitude > 0
    assert root.find("detail/contact").get("callsign") == "Detected Person (0.75)"
    assert "75.0%" in root.findtext("detail/remarks")


def test_cot_event_contains_uid_and_valid_stale_time():
    result = result_with_box((300, 200, 340, 240))

    cot_xml = geolocate_person(
        result,
        camera_latitude=37.0,
        camera_longitude=-122.0,
        altitude_m=100,
        horizontal_fov_deg=60,
        vertical_fov_deg=45,
        elevation_fn=None,
        uid="person-42",
        stale_duration_sec=30,
    )

    root = ET.fromstring(cot_xml)
    event_time = datetime.datetime.fromisoformat(root.get("time").replace("Z", "+00:00"))
    stale_time = datetime.datetime.fromisoformat(root.get("stale").replace("Z", "+00:00"))
    assert root.tag == "event"
    assert root.get("version") == "2.0"
    assert root.get("uid") == "person-42"
    assert stale_time - event_time == datetime.timedelta(seconds=30)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"camera_latitude": 91}, "camera_latitude"),
        ({"camera_longitude": 181}, "camera_longitude"),
        ({"altitude_m": 0}, "altitude_m"),
        ({"horizontal_fov_deg": 180}, "horizontal_fov_deg"),
        ({"vertical_fov_deg": -1}, "vertical_fov_deg"),
        ({"heading_deg": float("nan")}, "heading_deg"),
    ],
)
def test_geolocation_rejects_invalid_camera_parameters(overrides, error):
    result = result_with_box((300, 200, 340, 240))
    parameters = {
        "camera_latitude": 37.0,
        "camera_longitude": -122.0,
        "altitude_m": 100,
        "horizontal_fov_deg": 60,
        "vertical_fov_deg": 45,
        "elevation_fn": None,
    }

    with pytest.raises(ValueError, match=error):
        geolocate_person(result, **(parameters | overrides))


def test_geolocation_rejects_failure_result():
    task = DetectionTask(1, 1, "frame.jpg", b"image", "unused")
    result = DetectionResult.failure(task, "decode failed", 1.0, "test")

    with pytest.raises(ValueError, match="successful detection result"):
        geolocate_person(
            result,
            camera_latitude=37.0,
            camera_longitude=-122.0,
            altitude_m=100,
            horizontal_fov_deg=60,
            vertical_fov_deg=45,
        )


def test_geolocation_with_elevated_plateau():
    result = result_with_box((300, 200, 340, 240))

    # Mock an elevated plateau at 200 meters above sea level
    def plateau_elevation(lat, lon):
        return 200.0

    cot_xml = geolocate_person(
        result,
        camera_latitude=37.0,
        camera_longitude=-122.0,
        altitude_m=100,  # Drone is 100m above this plateau
        horizontal_fov_deg=60,
        vertical_fov_deg=45,
        elevation_fn=plateau_elevation,
    )

    _, _, hae = parse_cot_point(cot_xml)
    # HAE should match the terrain height where the ray intercepted
    assert hae == pytest.approx(200.0, abs=5.0)


def test_geolocation_with_sloping_terrain_shifts_target():
    result = result_with_box((460, 200, 500, 240))  # Right of center (projects east)

    # Mock a terrain slope that rises to 50m further east (relative to camera lon 0.0)
    def sloping_elevation(lat, lon):
        return 50.0 if lon > 0.0002 else 0.0

    cot_xml_flat = geolocate_person(
        result,
        camera_latitude=0.0,
        camera_longitude=0.0,
        altitude_m=100,
        horizontal_fov_deg=90,
        vertical_fov_deg=60,
        elevation_fn=lambda lat, lon: 0.0,
    )

    cot_xml_slope = geolocate_person(
        result,
        camera_latitude=0.0,
        camera_longitude=0.0,
        altitude_m=100,
        horizontal_fov_deg=90,
        vertical_fov_deg=60,
        elevation_fn=sloping_elevation,
    )

    lat_flat, lon_flat, _ = parse_cot_point(cot_xml_flat)
    lat_slope, lon_slope, hae_slope = parse_cot_point(cot_xml_slope)

    # Because the terrain rises toward the east, the ray intersects the ground 
    # sooner, resulting in a different intersection point and lower longitude shift
    assert hae_slope == pytest.approx(50.0, abs=10.0)
    assert lon_slope < lon_flat

def test_geolocation_rejects_missing_detections():
    message = result_with_box((300, 200, 340, 240)).to_wire()
    message["detections"] = []

    with pytest.raises(ValueError, match="out of range"):
        geolocate_person(
            message,
            camera_latitude=37.0,
            camera_longitude=-122.0,
            altitude_m=100,
            horizontal_fov_deg=60,
            vertical_fov_deg=45,
        )


def test_default_elevation_initializes_and_caches_srtm_data(monkeypatch):
    class ElevationData:
        def __init__(self):
            self.lookups = []

        def get_altitude(self, latitude, longitude):
            self.lookups.append((latitude, longitude))
            return 123

    data = ElevationData()
    initialize_calls = []

    def create_collection():
        initialize_calls.append(True)
        return data

    monkeypatch.setattr(geolocate, "_DEFAULT_SRTM_DATA", None)
    monkeypatch.setattr(geolocate.srtm, "Srtm1HeightMapCollection", create_collection)

    assert geolocate._default_elevation_fn(37.5, -122.25) == 123.0
    assert geolocate._default_elevation_fn(38.0, -123.0) == 123.0
    assert len(initialize_calls) == 1
    assert data.lookups == [(37.5, -122.25), (38.0, -123.0)]


def test_default_elevation_returns_zero_when_srtm_initialization_fails(monkeypatch):
    def fail_to_initialize():
        raise OSError("elevation data unavailable")

    monkeypatch.setattr(geolocate, "_DEFAULT_SRTM_DATA", None)
    monkeypatch.setattr(geolocate.srtm, "Srtm1HeightMapCollection", fail_to_initialize)

    assert geolocate._default_elevation_fn(37.5, -122.25) is None
    assert geolocate._DEFAULT_SRTM_DATA is None


def test_default_elevation_returns_zero_when_tile_has_no_elevation(monkeypatch):
    class EmptyElevationData:
        def get_altitude(self, latitude, longitude):
            return None

    monkeypatch.setattr(geolocate, "_DEFAULT_SRTM_DATA", EmptyElevationData())

    assert geolocate._default_elevation_fn(37.5, -122.25) is None
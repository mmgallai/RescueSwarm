"""Estimate ground locations from drone images and format as Cursor on Target (CoT) XML."""
from __future__ import annotations

import datetime
import math
import warnings
import uuid
from collections.abc import Callable
from xml.etree import ElementTree as ET

from .messages import DetectionResult, SUCCESS

EARTH_RADIUS_M = 6_371_000.0

# CoT uses this value for unknown height/error. No implicit terrain downloads.
COT_UNKNOWN = 9999999.0


def geolocate_person(
    message: DetectionResult | dict,
    *,
    camera_latitude: float,
    camera_longitude: float,
    altitude_m: float,
    horizontal_fov_deg: float,
    vertical_fov_deg: float,
    heading_deg: float = 0.0,
    detection_index: int = 0,
    elevation_fn: Callable[[float, float], float | None] | None = None,
    terrain_datum: str = "msl",
    geoid_offset_m: float | None = None,
    flat_ground_hae_m: float | None = None,
    camera_pitch_deg: float = -90.0,
    camera_roll_deg: float = 0.0,
    uid: str | None = None,
    stale_duration_sec: int = 60,
) -> str:
    """Estimate a detection's ground position and return a Cursor on Target (CoT) XML event string.

    Nadir camera only; altitude_m is AGL above terrain directly below the camera.
    Provider heights must share terrain_datum ("msl" or "hae"). For local MSL
    conversion, HAE = MSL + geoid_offset_m. Unknown heights are not fabricated.
    Default generates a new sighting ID; pass the same explicit UID for updates.
    The anchor is bottom-center of the box, an assumption requiring field validation.
    """
    latitude = float(camera_latitude)
    longitude = float(camera_longitude)
    altitude = float(altitude_m)
    horizontal_fov = float(horizontal_fov_deg)
    vertical_fov = float(vertical_fov_deg)
    heading = float(heading_deg)

    # Input validation
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("camera_latitude must be finite and in [-90, 90]")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("camera_longitude must be finite and in [-180, 180]")
    if not math.isfinite(altitude) or altitude <= 0:
        raise ValueError("altitude_m must be finite and positive")
    if not math.isfinite(horizontal_fov) or not 0 < horizontal_fov < 180:
        raise ValueError("horizontal_fov_deg must be in (0, 180)")
    if not math.isfinite(vertical_fov) or not 0 < vertical_fov < 180:
        raise ValueError("vertical_fov_deg must be in (0, 180)")
    if not math.isfinite(heading):
        raise ValueError("heading_deg must be finite")

    if not (math.isfinite(camera_pitch_deg) and math.isfinite(camera_roll_deg)
            and abs(camera_pitch_deg + 90) < 1e-6 and abs(camera_roll_deg) < 1e-6):
        raise ValueError("only nadir camera pitch=-90 and roll=0 are supported")
    if terrain_datum not in ("msl", "hae"):
        raise ValueError("terrain_datum must be msl or hae")
    for value in (geoid_offset_m, flat_ground_hae_m):
        if value is not None and not math.isfinite(value):
            raise ValueError("height conversion values must be finite")
    if uid is not None and (not isinstance(uid, str) or not uid.strip()):
        raise ValueError("uid must be a nonempty string")
    if not isinstance(stale_duration_sec, int) or not 0 < stale_duration_sec <= 86400:
        raise ValueError("stale duration must be between 1 and 86400 seconds")
    uid = uid if uid is not None else "rescueswarm-" + str(uuid.uuid4())
    longitude_scale = math.cos(math.radians(latitude))
    if abs(longitude_scale) < 1e-6:
        raise ValueError("camera latitude is too close to a pole for this local projection")

    # Extract message fields
    if isinstance(message, DetectionResult):
        status = message.status
        image_size = message.image_size
        detections = message.detections
    else:
        status = message.get("status")
        dimensions = message.get("image_size")
        image_size = (dimensions.get("width"), dimensions.get("height")) if dimensions else None
        detections = message.get("detections", [])

    if status != SUCCESS:
        raise ValueError("message must contain a successful detection result")
    if image_size is None:
        raise ValueError("message must include image dimensions")
    if detection_index < 0 or detection_index >= len(detections):
        raise ValueError(f"detection_index {detection_index} is out of range")

    width, height = image_size
    detection = detections[detection_index]
    if isinstance(message, DetectionResult):
        x1, y1, x2, y2 = detection.box_xyxy
        confidence = detection.confidence
    else:
        x1, y1, x2, y2 = (float(value) for value in detection["box_xyxy"])
        confidence = float(detection["confidence"])

    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("image dimensions must be positive")

    label = detection.label if isinstance(message, DetectionResult) else detection.get("label")
    if label != "person" or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("invalid person label or confidence")
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("box must be finite, within image, and have positive area")

    # Pixel offset calculation
    pixel_x = (x1 + x2) / 2
    pixel_y = y2

    tan_h = math.tan(math.radians(horizontal_fov) / 2)
    tan_v = math.tan(math.radians(vertical_fov) / 2)
    
    ray_right = (pixel_x / width - 0.5) * 2 * tan_h
    ray_up = (0.5 - pixel_y / height) * 2 * tan_v

    heading_rad = math.radians(heading)
    east_unit = ray_right * math.cos(heading_rad) + ray_up * math.sin(heading_rad)
    north_unit = -ray_right * math.sin(heading_rad) + ray_up * math.cos(heading_rad)
    down_unit = 1.0

    ray_len = math.sqrt(east_unit**2 + north_unit**2 + down_unit**2)
    dir_east = east_unit / ray_len
    dir_north = north_unit / ray_len
    dir_down = down_unit / ray_len

    def project(distance):
        lat = latitude + math.degrees(distance * dir_north / EARTH_RADIUS_M)
        lon = longitude + math.degrees(distance * dir_east / (EARTH_RADIUS_M * longitude_scale))
        if not -90 <= lat <= 90:
            raise ValueError("projection crosses a pole")
        return lat, (lon + 180) % 360 - 180

    ground = None
    if elevation_fn is not None:
        try:
            ground = elevation_fn(latitude, longitude)
        except Exception as error:
            warnings.warn(f"Elevation lookup failed: {error}. Falling back to flat-ground assumption.", UserWarning)
        else:
            if ground is None:
                warnings.warn("Elevation data unavailable. Falling back to flat-ground assumption.", UserWarning)
        if ground is not None and not math.isfinite(ground):
            raise ValueError("terrain elevation must be finite")

    if ground is None:
        distance = altitude / dir_down
        if distance > 10000:
            raise ValueError("projection exceeds local 10 km range")
        target_latitude, target_longitude = project(distance)
        target_hae = flat_ground_hae_m if flat_ground_hae_m is not None else COT_UNKNOWN
        method = "flat-ground assumption"
    else:
        camera_altitude = ground + altitude
        def sample(distance):
            lat, lon = project(distance)
            terrain = elevation_fn(lat, lon)
            if terrain is None or not math.isfinite(terrain):
                raise ValueError("terrain unavailable or invalid along ray")
            return camera_altitude - distance * dir_down - terrain

        step = max(1.0, min(5.0, altitude / 20.0))
        low = 0.0
        high = None
        for i in range(1, 2001):
            candidate = i * step
            if sample(candidate) <= 0:
                high = candidate
                break
            low = candidate
        if high is None:
            raise ValueError("no terrain intersection within bounded search")
        # Refine the first sampled sign change to a <=1 cm distance bracket.
        while high - low > 0.01:
            middle = (low + high) / 2
            if sample(middle) > 0:
                low = middle
            else:
                high = middle
        distance = (low + high) / 2
        if abs(sample(distance)) > 0.1:
            raise ValueError("terrain intersection unresolved at discontinuity")
        target_latitude, target_longitude = project(distance)
        hit_height = camera_altitude - distance * dir_down
        if terrain_datum == "hae":
            target_hae = hit_height
        elif geoid_offset_m is not None:
            target_hae = hit_height + geoid_offset_m
        else:
            target_hae = COT_UNKNOWN
        method = "terrain intersection"

    if not math.isfinite(target_hae):
        raise ValueError("converted HAE must be finite")

    # --- Construct Cursor on Target (CoT) XML ---
    now = datetime.datetime.now(datetime.timezone.utc)
    stale = now + datetime.timedelta(seconds=stale_duration_sec)

    # Format timestamps in CoT ISO 8601 standard
    time_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Root event element
    # Type 'a-u-G' represents an Unknown Ground track (or 'a-f-G-U-C' for friendly combat unit / rescue)
    event = ET.Element(
        "event",
        version="2.0",
        uid=uid,
        type="a-u-G",  
        time=time_str,
        start=time_str,
        stale=stale_str,
        how="m-g",  
    )

    # Point element: HAE only, or the CoT unknown-height sentinel.
    ET.SubElement(
        event,
        "point",
        lat=f"{target_latitude:.6f}",
        lon=f"{target_longitude:.6f}",
        hae=f"{target_hae:.1f}",
        ce=str(COT_UNKNOWN),
        le=str(COT_UNKNOWN),
    )

    # Detail element for supplementary metadata (confidence, callsign, remarks)
    detail = ET.SubElement(event, "detail")
    
    # Optional contact metadata
    ET.SubElement(detail, "contact", callsign=f"Detected Person ({confidence:.2f})")
    
    # Remarks with detection confidence details
    remarks = ET.SubElement(detail, "remarks")
    remarks.text = f"Rescueswarm Vision Detection. Confidence: {confidence * 100:.1f}%. {method}; nadir camera. " + ("Height unknown." if target_hae == COT_UNKNOWN else "Height is HAE.")

    return ET.tostring(event, encoding="utf-8", method="xml").decode("utf-8")
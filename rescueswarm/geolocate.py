"""Estimate ground locations from drone images and format as Cursor on Target (CoT) XML."""
from __future__ import annotations

import datetime
import math
from collections.abc import Callable
from xml.etree import ElementTree as ET

from .messages import DetectionResult, SUCCESS

EARTH_RADIUS_M = 6_371_000.0

import srtm

_DEFAULT_SRTM_DATA = None

def _default_elevation_fn(lat: float, lon: float) -> float:
    """Default elevation provider using srtm.py with graceful fallbacks."""
    global _DEFAULT_SRTM_DATA
    if _DEFAULT_SRTM_DATA is None:
        try:
            _DEFAULT_SRTM_DATA = srtm.Srtm1HeightMapCollection()
        except Exception:
            return 0.0  # Fallback to sea level if offline/uninitialized
            
    elevation = _DEFAULT_SRTM_DATA.get_altitude(lat, lon)
    return float(elevation) if elevation is not None else 0.0

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
    elevation_fn: Callable[[float, float], float] = _default_elevation_fn,
    uid: str = "rescueswarm-target-01",
    stale_duration_sec: int = 60,
) -> str:
    """Estimate a detection's ground position and return a Cursor on Target (CoT) XML event string.

    Supports optional terrain ray-marching if elevation_fn is provided.
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

    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")

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

    if elevation_fn is None:
        # Flat ground projection
        right_m = ray_right * altitude
        up_m = ray_up * altitude
        east_m = right_m * math.cos(heading_rad) + up_m * math.sin(heading_rad)
        north_m = -right_m * math.sin(heading_rad) + up_m * math.cos(heading_rad)
        target_latitude = latitude + math.degrees(north_m / EARTH_RADIUS_M)
        longitude_scale = math.cos(math.radians(latitude))
        if abs(longitude_scale) < 1e-12:
            raise ValueError("camera latitude is too close to a pole for this local projection")
        target_longitude = longitude + math.degrees(east_m / (EARTH_RADIUS_M * longitude_scale))
        target_hae = 0.0  # Height above ellipsoid / ground level reference
    else:
        # Terrain ray-casting projection
        drone_ground_elevation = elevation_fn(latitude, longitude)
        camera_alt_msl = drone_ground_elevation + altitude
        
        current_alt_msl = camera_alt_msl
        current_lat = latitude
        current_lon = longitude
        
        max_steps = 100
        step_distance_m = altitude / 20.0
        
        for _ in range(max_steps):
            terrain_alt = elevation_fn(current_lat, current_lon)
            if current_alt_msl <= terrain_alt:
                break
            
            current_alt_msl -= step_distance_m * dir_down
            total_east_m = (camera_alt_msl - current_alt_msl) * (dir_east / dir_down)
            total_north_m = (camera_alt_msl - current_alt_msl) * (dir_north / dir_down)
            
            current_lat = latitude + math.degrees(total_north_m / EARTH_RADIUS_M)
            longitude_scale = math.cos(math.radians(latitude))
            current_lon = longitude + math.degrees(total_east_m / (EARTH_RADIUS_M * longitude_scale))
            
        target_latitude = current_lat
        target_longitude = current_lon
        target_hae = current_alt_msl

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

    # Point element (latitude, longitude, Height Above Ellipsoid/MSL, Circular Error, Linear Error)
    ET.SubElement(
        event,
        "point",
        lat=f"{target_latitude:.6f}",
        lon=f"{target_longitude:.6f}",
        hae=f"{target_hae:.1f}",
        ce="999.0",
        le="999.0",
    )

    # Detail element for supplementary metadata (confidence, callsign, remarks)
    detail = ET.SubElement(event, "detail")
    
    # Optional contact metadata
    ET.SubElement(detail, "contact", callsign=f"Detected Person ({confidence:.2f})")
    
    # Remarks with detection confidence details
    remarks = ET.SubElement(detail, "remarks")
    remarks.text = f"Rescueswarm Vision Detection. Confidence: {confidence * 100:.1f}%"

    return ET.tostring(event, encoding="utf-8", method="xml").decode("utf-8")
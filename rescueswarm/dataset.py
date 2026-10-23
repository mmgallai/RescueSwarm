"""Load SAR-DAG_raycast frames: image path, ground-truth person boxes and camera telemetry.

Layout (after scripts/prepare_dataset.py), under drone_data/:

    flights/<flight>/REC/DJI_0123.JPG   raw drone image
    flights/<flight>/GT/DJI_0123.txt    YOLO label, present only when a person is visible
    CSVs/<flight>.csv                   one row per image with telemetry; images where the
                                        authors' detector fired several times repeat the row
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data" / "sar-dag" / "SAR-DAG_raycast" / "drone_data"

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in original-image pixels


@dataclass(frozen=True)
class Telemetry:
    """Camera pose and parameters recorded when the image was taken."""

    time: datetime
    latitude: float
    longitude: float
    absolute_altitude_m: float
    relative_altitude_m: float  # height above the take-off point
    flight_pitch_deg: float
    flight_yaw_deg: float
    flight_roll_deg: float
    gimbal_pitch_deg: float
    gimbal_yaw_deg: float
    gimbal_roll_deg: float
    fov_deg: float
    focal_length_mm: float
    drone_model: str
    camera_model: str

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> Telemetry:
        return cls(
            time=datetime.fromisoformat(row["Time"]),
            latitude=float(row["GPS_N"]),
            longitude=float(row["GPS_E"]),
            absolute_altitude_m=float(row["Absolute_Altitude"]),
            relative_altitude_m=float(row["Relative_Altitude"]),
            flight_pitch_deg=float(row["Flight_Pitch_Degree"]),
            flight_yaw_deg=float(row["Flight_Yaw_Degree"]),
            flight_roll_deg=float(row["Flight_Roll_Degree"]),
            gimbal_pitch_deg=float(row["Gimbal_Pitch_Degree"]),
            gimbal_yaw_deg=float(row["Gimbal_Yaw_Degree"]),
            gimbal_roll_deg=float(row["Gimbal_Roll_Degree"]),
            fov_deg=float(row["FOV"]),
            focal_length_mm=float(row["Focal_Lenght"]),  # sic: the dataset's spelling
            drone_model=row["Drone_Model"],
            camera_model=row["Camera_Model"],
        )


@dataclass(frozen=True)
class Frame:
    """One drone image with everything we know about it."""

    flight: str
    image_id: str  # "<flight>/<file name>", unique across the whole dataset
    image_path: Path
    width: int
    height: int
    gt_boxes: tuple[Box, ...]  # empty when no person is in the image
    telemetry: Telemetry

    @property
    def has_person(self) -> bool:
        return bool(self.gt_boxes)


def read_yolo_boxes(label_path: Path, width: int, height: int) -> tuple[Box, ...]:
    """Convert a YOLO label file (class cx cy w h, normalized) to pixel xyxy boxes clipped to the image."""
    boxes = []
    for line in label_path.read_text().splitlines():
        if not line.strip():
            continue
        _, cx, cy, w, h = map(float, line.split())
        x1, x2 = (cx - w / 2) * width, (cx + w / 2) * width
        y1, y2 = (cy - h / 2) * height, (cy + h / 2) * height
        boxes.append((max(0.0, x1), max(0.0, y1), min(float(width), x2), min(float(height), y2)))
    return tuple(boxes)


def list_flights(root: Path = DEFAULT_ROOT) -> list[str]:
    return sorted(p.name for p in (root / "flights").iterdir() if p.is_dir())


def load_flight(flight: str, root: Path = DEFAULT_ROOT) -> list[Frame]:
    """All frames of one flight, ordered by capture time."""
    flight_dir = root / "flights" / flight
    rows: dict[str, dict[str, str]] = {}
    with open(root / "CSVs" / f"{flight}.csv", newline="") as f:
        for row in csv.DictReader(f):
            rows.setdefault(row["File_Name"], row)  # duplicates differ only in the authors' detections

    frames = []
    for file_name, row in rows.items():
        width, height = int(row["Resolution_X"]), int(row["Resolution_Y"])
        label_path = flight_dir / "GT" / f"{Path(file_name).stem}.txt"
        gt_boxes = read_yolo_boxes(label_path, width, height) if label_path.exists() else ()
        frames.append(Frame(flight=flight, image_id=f"{flight}/{file_name}",
                            image_path=flight_dir / "REC" / file_name, width=width, height=height,
                            gt_boxes=gt_boxes, telemetry=Telemetry.from_csv_row(row)))
    return sorted(frames, key=lambda fr: fr.telemetry.time)


def load_dataset(root: Path = DEFAULT_ROOT, flights: list[str] | None = None) -> list[Frame]:
    """Frames from the given flights (default: all of them)."""
    return [frame for flight in (flights or list_flights(root)) for frame in load_flight(flight, root)]

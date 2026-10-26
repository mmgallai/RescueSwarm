"""Draw SAR-DAG ground-truth person boxes on sample images to check the data by eye.

Each preview shows the whole photo (shrunk) next to a zoomed crop around each person,
because people are only ~1% of the frame width at drone altitude.

    python scripts/show_ground_truth.py                    # one person image per flight
    python scripts/show_ground_truth.py --flight polje --count 5
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from rescueswarm.dataset import Box, Frame, list_flights, load_flight

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "runs" / "ground_truth"
GREEN = (0, 255, 0)  # OpenCV colors are BGR


def crop_window(image: np.ndarray, box: Box, margin: float = 3.0, min_side: int = 128) -> tuple[int, int, int]:
    """(left, top, side) of a square centered on the box, `margin` times its larger side, inside the image."""
    x1, y1, x2, y2 = box
    height, width = image.shape[:2]
    side = min(max(int(max(x2 - x1, y2 - y1) * margin), min_side), width, height)
    cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
    left = min(max(0, cx - side // 2), width - side)
    top = min(max(0, cy - side // 2), height - side)
    return left, top, side


def draw_box(image: np.ndarray, box: Box, scale: float, left: int = 0, top: int = 0) -> None:
    """Draw `box` (original-image pixels) on a panel that was cropped at (left, top) and scaled."""
    x1, y1, x2, y2 = box
    p1 = (round((x1 - left) * scale), round((y1 - top) * scale))
    p2 = (round((x2 - left) * scale), round((y2 - top) * scale))
    cv2.rectangle(image, p1, p2, GREEN, 2)


def render_preview(image: np.ndarray, boxes: tuple[Box, ...], label: str, height: int = 800) -> np.ndarray:
    """Shrunk full image with boxes, followed by one zoomed crop per box, all `height` pixels tall.

    Boxes are drawn after resizing so a thin outline never hides a small person.
    """
    scale = height / image.shape[0]
    full = cv2.resize(image, (int(image.shape[1] * scale), height), interpolation=cv2.INTER_AREA)
    for box in boxes:
        draw_box(full, box, scale)
    panels = [full]

    for box in boxes:
        left, top, side = crop_window(image, box)
        zoom = height / side
        crop = cv2.resize(image[top:top + side, left:left + side], (height, height),
                          interpolation=cv2.INTER_NEAREST)
        draw_box(crop, box, zoom, left, top)
        panels.append(crop)

    preview = np.hstack(panels)
    cv2.putText(preview, label, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, GREEN, 3)
    return preview


def pick_frames(flights: list[str], count: int) -> list[Frame]:
    """The first `count` frames containing a person from each flight."""
    return [f for flight in flights for f in [fr for fr in load_flight(flight) if fr.has_person][:count]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flight", action="append", help="flight name (repeatable; default: all flights)")
    parser.add_argument("--count", type=int, default=1, help="person images per flight")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for frame in pick_frames(args.flight or list_flights(), args.count):
        image = cv2.imread(str(frame.image_path))
        if image is None:
            print(f"could not read {frame.image_path}")
            continue
        label = f"{frame.image_id}  alt {frame.telemetry.relative_altitude_m:.0f} m"
        out_path = args.out / f"{frame.image_id.replace('/', '__')}.jpg"
        cv2.imwrite(str(out_path), render_preview(image, frame.gt_boxes, label))
        print(out_path)


if __name__ == "__main__":
    main()

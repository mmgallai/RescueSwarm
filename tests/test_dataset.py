import csv

import pytest

from rescueswarm.dataset import DEFAULT_ROOT, load_dataset, load_flight, read_yolo_boxes

HEADER = ["Time", "File_Name", "GPS_N", "GPS_E", "Absolute_Altitude", "Relative_Altitude",
          "Flight_Pitch_Degree", "Flight_Yaw_Degree", "Flight_Roll_Degree", "Gimbal_Pitch_Degree",
          "Gimbal_Yaw_Degree", "Gimbal_Roll_Degree", "Resolution_X", "Resolution_Y", "FOV",
          "Focal_Lenght", "Drone_Model", "Camera_Model"]


def write_flight(root, flight, rows, labels):
    """Create a tiny fake flight: CSV rows, empty images and YOLO label files."""
    (root / "CSVs").mkdir(parents=True, exist_ok=True)
    for sub in ("REC", "GT"):
        (root / "flights" / flight / sub).mkdir(parents=True, exist_ok=True)
    with open(root / "CSVs" / f"{flight}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for time, name in rows:
            writer.writerow([time, name, "45.47", "16.71", "-17.6", "28.7", "-3.0", "-83.6", "1.2",
                             "-51.5", "-82.8", "0.0", "1000", "500", "84", "8.8", "Phantom4A", "FC6310"])
            (root / "flights" / flight / "REC" / name).write_bytes(b"")
    for stem, text in labels.items():
        (root / "flights" / flight / "GT" / f"{stem}.txt").write_text(text)


def test_yolo_label_converted_to_pixels(tmp_path):
    label = tmp_path / "a.txt"
    label.write_text("0 0.5 0.5 0.1 0.2\n")
    assert read_yolo_boxes(label, 1000, 500) == ((450.0, 200.0, 550.0, 300.0),)


def test_yolo_box_past_image_edge_is_clipped(tmp_path):
    label = tmp_path / "a.txt"
    label.write_text("0 0.05 0.01 0.2 0.1\n")  # extends left of x=0 and above y=0
    (box,) = read_yolo_boxes(label, 1000, 500)
    assert box == pytest.approx((0.0, 0.0, 150.0, 30.0))


def test_load_flight_joins_images_labels_and_telemetry(tmp_path):
    write_flight(tmp_path, "polje", [("2022-01-14 14:49:00.010", "DJI_0002.JPG"),
                                     ("2022-01-14 14:48:56.010", "DJI_0001.JPG"),
                                     ("2022-01-14 14:49:00.010", "DJI_0002.JPG")],  # duplicate row
                 labels={"DJI_0002": "0 0.5 0.5 0.1 0.2"})
    frames = load_flight("polje", tmp_path)

    assert [f.image_id for f in frames] == ["polje/DJI_0001.JPG", "polje/DJI_0002.JPG"]  # time order, deduped
    no_person, person = frames
    assert not no_person.has_person
    assert person.gt_boxes == ((450.0, 200.0, 550.0, 300.0),)
    assert (person.width, person.height) == (1000, 500)
    assert person.image_path == tmp_path / "flights" / "polje" / "REC" / "DJI_0002.JPG"
    assert person.telemetry.relative_altitude_m == 28.7
    assert person.telemetry.gimbal_pitch_deg == -51.5


def test_load_dataset_combines_flights(tmp_path):
    write_flight(tmp_path, "a", [("2022-01-14 10:00:00", "DJI_0001.JPG")], {})
    write_flight(tmp_path, "b", [("2022-01-14 11:00:00", "DJI_0001.JPG")], {})
    assert [f.image_id for f in load_dataset(tmp_path)] == ["a/DJI_0001.JPG", "b/DJI_0001.JPG"]
    assert [f.image_id for f in load_dataset(tmp_path, ["b"])] == ["b/DJI_0001.JPG"]


@pytest.mark.skipif(not DEFAULT_ROOT.exists(), reason="SAR-DAG not downloaded (see README)")
def test_real_dataset_loads_completely():
    frames = load_dataset()
    assert len(frames) == 227
    assert sum(f.has_person for f in frames) == 134
    assert len({f.image_id for f in frames}) == len(frames)
    for f in frames:
        assert f.image_path.exists()
        for x1, y1, x2, y2 in f.gt_boxes:
            assert 0 <= x1 < x2 <= f.width and 0 <= y1 < y2 <= f.height

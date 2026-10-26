import numpy as np
import pytest

from rescueswarm.coreml_reference import PAD_VALUE, Letterbox, decode, letterbox


def test_wide_photo_is_padded_top_and_bottom():
    box = Letterbox.fit(5472, 3648, 1280)  # SAR-DAG photo
    assert box.scale == pytest.approx(1280 / 5472)
    assert (box.resized_width, box.resized_height) == (1280, 853)
    assert (box.left, box.top) == (0, 213)  # (1280 - 853) // 2


def test_tall_photo_is_padded_left_and_right():
    box = Letterbox.fit(3000, 4000, 1280)
    assert (box.resized_width, box.resized_height) == (960, 1280)
    assert (box.left, box.top) == (160, 0)


def test_mapping_undoes_scale_and_padding():
    box = Letterbox.fit(5472, 3648, 1280)
    assert box.to_original(0, 213) == (0, 0)  # top-left of the photo inside the square
    x, y = box.to_original(1280, 213 + 1280 * 3648 / 5472)
    assert (x, y) == (pytest.approx(5472), pytest.approx(3648))


def test_letterbox_image_layout():
    image = np.full((100, 200, 3), 255, np.uint8)  # white 200x100
    canvas, box = letterbox(image, 64)
    assert canvas.shape == (64, 64, 3)
    assert (box.top, box.resized_height) == (16, 32)
    assert canvas[0, 0].tolist() == [PAD_VALUE] * 3      # padding
    assert canvas[32, 32].tolist() == [255, 255, 255]    # photo


def scores(person, other=0.0):
    row = np.zeros(80)
    row[0], row[2] = person, other  # class 2 = car
    return row


def test_decode_maps_person_box_to_original_pixels():
    box = Letterbox.fit(5472, 3648, 1280)
    # A box covering the whole photo area inside the square (rows 213 to 1066).
    coords = np.array([[0.5, (213 + 853 / 2) / 1280, 1.0, 853 / 1280]])
    (det,) = decode(coords, np.array([scores(0.9)]), box, 5472, 3648, conf=0.25)
    # 3648 rows shrink to 853.3, rounded to 853, so edges can be ~1.5 original pixels off.
    assert det.box_xyxy == pytest.approx((0, 0, 5472, 3648), abs=2)
    assert det.confidence == pytest.approx(0.9)


def test_decode_drops_other_classes_and_low_confidence():
    box = Letterbox.fit(640, 640, 640)
    coords = np.array([[0.5, 0.5, 0.1, 0.1]] * 3)
    confs = np.array([scores(0.9), scores(0.1), scores(0.3, other=0.8)])  # person, weak person, car
    dets = decode(coords, confs, box, 640, 640, conf=0.25)
    assert [d.confidence for d in dets] == [pytest.approx(0.9)]


def test_decode_clips_boxes_that_reach_into_padding():
    box = Letterbox.fit(5472, 3648, 1280)
    coords = np.array([[0.5, 213 / 1280, 0.1, 0.1]])  # centered on the photo's top edge
    (det,) = decode(coords, np.array([scores(0.9)]), box, 5472, 3648, conf=0.25)
    assert det.box_xyxy[1] == 0

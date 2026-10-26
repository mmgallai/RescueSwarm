import importlib.util
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "show_ground_truth.py"
spec = importlib.util.spec_from_file_location("show_ground_truth", SCRIPT)
show_ground_truth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(show_ground_truth)


def test_crop_is_centered_on_the_box():
    image = np.zeros((1000, 2000, 3), np.uint8)
    # 50x100 person centered at (1000, 500): side = 3 * 100 = 300
    assert show_ground_truth.crop_window(image, (975, 450, 1025, 550)) == (850, 350, 300)


def test_tiny_box_gets_minimum_crop_size():
    image = np.zeros((1000, 2000, 3), np.uint8)
    assert show_ground_truth.crop_window(image, (995, 490, 1005, 510))[2] == 128


def test_crop_near_edge_stays_inside_image():
    image = np.zeros((1000, 2000, 3), np.uint8)
    assert show_ground_truth.crop_window(image, (0, 0, 50, 100)) == (0, 0, 300)
    assert show_ground_truth.crop_window(image, (1950, 900, 2000, 1000)) == (1700, 700, 300)


def test_box_drawn_on_zoomed_crop_lands_in_the_right_place():
    panel = np.zeros((300, 300, 3), np.uint8)
    # box (110,120)-(120,125) in a crop starting at (100,100), zoomed 10x -> (100,200)-(200,250)
    show_ground_truth.draw_box(panel, (110, 120, 120, 125), scale=10, left=100, top=100)
    assert panel[200, 100].tolist() == list(show_ground_truth.GREEN)  # row y=200, column x=100


def test_preview_has_full_image_plus_one_square_crop_per_box():
    image = np.zeros((500, 1000, 3), np.uint8)
    boxes = ((100, 100, 120, 140), (600, 300, 630, 360))
    preview = show_ground_truth.render_preview(image, boxes, "test", height=200)
    assert preview.shape == (200, 400 + 2 * 200, 3)  # 1000x500 shrunk to 400x200, then two 200x200 crops

"""Decisions of the sorting pipeline that do not need the arm, a camera or a GPU."""

import numpy as np
import pytest
import torch

from sort_pipeline import CLASSES, Detector, iou, max_deviation

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def pose(**degrees):
    return {f"{j}.pos": float(degrees.get(j, 0)) for j in JOINTS}


def test_iou():
    assert iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0
    assert iou([0, 0, 10, 10], [5, 0, 15, 10]) == pytest.approx(50 / 150)


def test_gripper_does_not_count_as_leaving_home():
    home = pose()
    assert max_deviation(pose(gripper=80), home) == 0
    assert max_deviation(pose(elbow_flex=-25, gripper=80), home) == 25


class FakeYolo:
    """Stands in for ultralytics.YOLO: returns fixed boxes."""

    names = {0: "metal", 1: "plastic", 2: "other"}

    def __init__(self, boxes):  # (class id, confidence, [x0, y0, x1, y1])
        self.boxes = boxes

    def predict(self, image, **kwargs):
        result = type("Result", (), {})()
        result.boxes = type("Boxes", (), {
            "cls": torch.tensor([b[0] for b in self.boxes], dtype=torch.float),
            "conf": torch.tensor([b[1] for b in self.boxes]),
            "xyxy": torch.tensor([b[2] for b in self.boxes], dtype=torch.float),
        })()
        return [result]


def detector(boxes, ignore_regions=((0, 40, 135, 320),)):
    d = Detector.__new__(Detector)  # skip loading real weights
    d.model, d.conf, d.device, d.ignore_regions = FakeYolo(boxes), 0.5, "cpu", list(ignore_regions)
    return d


def test_items_in_a_bin_and_unknown_classes_are_ignored():
    frame = np.zeros((480, 640, 3), np.uint8)
    found = detector([
        (0, 0.9, [20, 100, 100, 200]),    # metal inside the left bin: already sorted
        (1, 0.7, [250, 150, 350, 250]),   # plastic on the table
        (2, 0.95, [400, 350, 450, 400]),  # "other" is not a pipeline class
    ])(frame)
    assert [d["class"] for d in found] == ["plastic"]
    assert all(d["class"] in CLASSES for d in found)


def test_most_confident_detection_comes_first():
    frame = np.zeros((480, 640, 3), np.uint8)
    found = detector([(1, 0.6, [250, 150, 350, 250]), (0, 0.8, [300, 300, 380, 380])], ignore_regions=())(frame)
    assert [d["class"] for d in found] == ["metal", "plastic"]


def test_ignore_regions_scale_with_the_image_size():
    frame = np.zeros((960, 1280, 3), np.uint8)  # 2x the 640x480 the regions are given in
    found = detector([(0, 0.9, [40, 200, 200, 400])])(frame)  # centre (120, 300) -> (60, 150) at 640x480
    assert found == []

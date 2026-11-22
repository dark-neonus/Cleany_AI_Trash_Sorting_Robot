"""The capture tool's logic (scripts/common/pose_capture.py)."""

import pytest
import yaml
from box_logic import JOINT_KEYS, load_poses
from pose_capture import CaptureSession, report, steady_pose
from test_pose_catalog import CAPTURED, pose


def test_a_capture_is_written_at_once_in_catalog_order_and_loads_in_the_pipeline(tmp_path):
    path = tmp_path / "poses.yaml"
    s = CaptureSession(path)
    assert s.next_missing() == "home"
    for name in ("plastic_bin", "home", "metal_bin", "hover", "transit"):
        s.capture(name, CAPTURED[name])
    assert list(yaml.safe_load(path.read_text())["poses"]) == ["home", "hover", "transit", "metal_bin", "plastic_bin"]
    assert load_poses(path)["hover"] == CAPTURED["hover"]  # the pipeline's own loader accepts it
    assert s.next_missing() is None  # tray_low is optional: never asked for


def test_old_files_are_read_as_new_names_and_backed_up_on_the_first_save(tmp_path):
    path = tmp_path / "poses.yaml"
    old = {"home": CAPTURED["home"], "centre": CAPTURED["transit"], "grasp": CAPTURED["tray_low"],
           "tray_release": pose(0, -105, 98, 24, gripper=99)}
    path.write_text(yaml.safe_dump({"poses": old}))
    s = CaptureSession(path)
    assert set(s.poses) == {"home", "transit", "tray_low"} and s.notes
    assert yaml.safe_load(path.read_text())["poses"].keys() == old.keys()  # reading changes nothing
    s.capture("hover", CAPTURED["hover"])
    assert set(yaml.safe_load(path.read_text())["poses"]) == {"home", "hover", "tray_low", "transit"}
    assert yaml.safe_load((tmp_path / "poses.yaml.bak").read_text())["poses"].keys() == old.keys()
    s.capture("home", CAPTURED["home"])  # a second save does not overwrite the backup
    assert "tray_release" in (tmp_path / "poses.yaml.bak").read_text()


def test_clear_and_findings(tmp_path):
    s = CaptureSession(tmp_path / "poses.yaml")
    s.capture("home", CAPTURED["home"])
    found = s.capture("transit", CAPTURED["home"])  # the arm was not moved
    assert found and found[0].level == "error"
    s.clear("transit")
    assert "transit" not in s.poses and s.findings("transit") == []


def reading(t, **over):
    return t, {**CAPTURED["hover"], **over}


def test_steady_pose_is_the_mean_of_a_still_arm():
    samples = [reading(i * 0.05, **{"shoulder_pan.pos": 10.0 + (i % 2) * 0.2}) for i in range(20)]
    got, why = steady_pose(samples, now=0.95)
    assert why == "" and got["shoulder_pan.pos"] == pytest.approx(10.1, abs=0.06) and set(got) == set(JOINT_KEYS)


def test_steady_pose_refuses_a_moving_arm_and_missing_readings():
    moving = [reading(i * 0.05, **{"elbow_flex.pos": i * 1.0}) for i in range(20)]
    got, why = steady_pose(moving, now=0.95)
    assert got is None and "still moving" in why and "elbow flex" in why.replace("_", " ")
    assert steady_pose([reading(0.0)], now=0.0)[0] is None
    assert steady_pose([reading(0.0)] * 10, now=5.0)[0] is None  # stale readings
    gripper_only = [reading(i * 0.05, **{"gripper.pos": i * 5.0}) for i in range(20)]
    assert steady_pose(gripper_only, now=0.95)[0] is not None  # the gripper may move: its value is not used


def test_report_lists_state_and_what_each_feature_still_needs():
    text = report({"home": CAPTURED["home"], "hover": CAPTURED["home"]})
    assert "✗ 6 tray_low" in text and "not captured (optional)" in text
    assert "almost the same joints as 'home'" in text
    assert "needs transit, metal_bin, plastic_bin" in text
    assert report(CAPTURED).count("ready:") == 2

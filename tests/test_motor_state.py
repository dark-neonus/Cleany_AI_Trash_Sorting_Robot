"""Normalised positions (scripts/common/motor_state.py) against lerobot's own normalisation."""

import json
from pathlib import Path

import numpy as np
import pytest
from motor_state import JOINTS, STATE_NAMES, Normaliser, dataset_features, training_state

CALIBRATION = Path(__file__).parents[1] / "calibration"


def lerobot_bus(calibration: dict, mode_body):
    from lerobot.motors import Motor, MotorCalibration, MotorNormMode
    from lerobot.motors.feetech import FeetechMotorsBus

    motors = {j: Motor(i + 1, "sts3215", MotorNormMode.RANGE_0_100 if j == "gripper" else mode_body)
              for i, j in enumerate(JOINTS)}
    return FeetechMotorsBus("/dev/null", motors, {j: MotorCalibration(**calibration[j]) for j in JOINTS})


@pytest.mark.parametrize("arm", ["follower_arm", "leader_arm"])
def test_unit_matches_lerobot_range_mode_from_degrees(arm):
    """Degrees -> our unit equals lerobot's RANGE_M100_100 / 100 for the same raw reading."""
    from lerobot.motors import MotorNormMode

    calibration = json.loads((CALIBRATION / f"{arm}.json").read_text())
    degrees_bus = lerobot_bus(calibration, MotorNormMode.DEGREES)
    range_bus = lerobot_bus(calibration, MotorNormMode.RANGE_M100_100)
    norm = Normaliser.from_calibration(calibration)
    for i, joint in enumerate(JOINTS):
        c = calibration[joint]
        for raw in np.linspace(c["range_min"], c["range_max"], 7).round().astype(int):
            deg = degrees_bus._normalize({i + 1: int(raw)})[i + 1]
            expected = range_bus._normalize({i + 1: int(raw)})[i + 1] / 100
            got = norm.to_unit(joint, deg)
            if joint == "gripper":
                got = norm.to_unit(joint, range_bus._normalize({i + 1: int(raw)})[i + 1])  # 0-100 in both modes
            assert got == pytest.approx(expected, abs=1e-6), (joint, raw)


def test_degrees_round_trip_and_clipping():
    calibration = json.loads((CALIBRATION / "follower_arm.json").read_text())
    norm = Normaliser.from_calibration(calibration)
    joints = {"shoulder_pan.pos": 12.5, "shoulder_lift.pos": -40.0, "elbow_flex.pos": 30.0,
              "wrist_flex.pos": 5.0, "wrist_roll.pos": -90.0, "gripper.pos": 42.0}
    units = norm.positions(joints)
    assert np.all(units[:5] >= -1) and np.all(units[:5] <= 1) and units[5] == pytest.approx(0.42)
    back = norm.degrees(units)
    for k, v in joints.items():
        assert back[k] == pytest.approx(v, abs=1e-3)
    assert norm.to_unit("shoulder_pan", 1000.0) == 1.0  # beyond the calibrated range: clipped


def test_training_state_and_features():
    extras = {"current": np.array([0, 0, 0, 0, 0, 125.0]), "load": np.array([0, 0, 0, 0, 0, -500.0])}
    state = training_state(np.zeros(6, np.float32), extras, gripper_protection_current=250)
    assert state.tolist()[-2:] == [0.5, -0.5] and len(state) == len(STATE_NAMES)
    features = dataset_features({"front": (480, 640), "wrist": (360, 640)}, embedding_dim=384)
    policy_inputs = [k for k in features if k.startswith("observation")]
    assert policy_inputs == ["observation.state", "observation.images.front", "observation.images.wrist"]
    assert features["item.embedding"]["shape"] == (384,)

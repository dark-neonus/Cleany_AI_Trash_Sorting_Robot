"""Forward kinematics of the SO-101 (scripts/common/arm_kinematics.py)."""

import pytest
from arm_kinematics import SKELETON, forward, reach_cm, tool_pitch_deg
from box_logic import JOINT_KEYS

ZERO = dict.fromkeys(JOINT_KEYS, 0.0)


def test_at_all_zeros_the_upper_arm_is_up_and_the_forearm_forward():
    p = forward(ZERO)
    assert list(p) == list(SKELETON)
    assert p["elbow_flex"][2] > p["shoulder_lift"][2] + 10  # upper arm up
    assert p["wrist_flex"][0] - p["elbow_flex"][0] == pytest.approx(13.5, abs=0.5)  # forearm forward
    assert abs(p["wrist_flex"][2] - p["elbow_flex"][2]) < 1.5
    assert p["tcp"] == pytest.approx([39.1, 0, 22.6], abs=0.3)
    assert tool_pitch_deg(ZERO) == pytest.approx(4.7, abs=1)  # gripper roughly horizontal


def test_positive_pan_turns_the_arm_to_the_right():
    right = forward({**ZERO, "shoulder_pan.pos": 40})["tcp"]
    left = forward({**ZERO, "shoulder_pan.pos": -40})["tcp"]
    assert right[1] < -10 and left[1] > 10 and right[0] == pytest.approx(left[0], abs=0.01)
    assert reach_cm({**ZERO, "shoulder_pan.pos": 40}) == pytest.approx(reach_cm(ZERO), abs=0.1)


def test_keys_with_and_without_pos_suffix_are_the_same():
    plain = {k.removesuffix(".pos"): 10.0 for k in JOINT_KEYS}
    assert forward(plain)["tcp"] == pytest.approx(forward({k: 10.0 for k in JOINT_KEYS})["tcp"])


def test_shoulder_lift_forward_lowers_the_hand():
    up, down = forward(ZERO)["tcp"], forward({**ZERO, "shoulder_lift.pos": 40})["tcp"]
    assert down[2] < up[2] and down[0] > up[0] - 1
    assert tool_pitch_deg({**ZERO, "wrist_flex.pos": 60}) > 50  # wrist down: gripper points down

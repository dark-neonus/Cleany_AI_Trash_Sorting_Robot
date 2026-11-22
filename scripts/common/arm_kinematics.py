"""Forward kinematics of the SO-101: where the gripper is for a set of joint angles.

Used to draw the named poses in the workspace (pose_view.py) and to sanity-check a captured
pose (pose_catalog.py). Numpy only, no lerobot, no URDF file.

The chain is the official SO-101 "new calibration" model (TheRobotStudio/SO-ARM100,
Simulation/SO101/so101_new_calib.urdf, Apache-2.0): each joint's zero is the middle of its range,
which is exactly what lerobot's degrees mode reports, so the joint values of a pose
(config/poses.yaml) go in unchanged. At all zeros the upper arm points straight up and the
forearm straight forward.

Frame (centimetres): origin on the arm base, x forward (the way the arm points at shoulder_pan 0),
y to the left, z up. A positive shoulder_pan turns the arm to the right (towards -y): checked on
the box, where the metal bin (left) was captured at about -40 and the plastic bin (right) at +44.
"""

from __future__ import annotations

import math

import numpy as np

# joint, origin xyz (m), origin rpy (rad) in the parent frame; every joint turns about its own z
_CHAIN = (
    ("shoulder_pan", (0.0388353, -8.97657e-09, 0.0624), (3.14159, 4.18253e-17, -3.14159)),
    ("shoulder_lift", (-0.0303992, -0.0182778, -0.0542), (-1.5708, -1.5708, 0.0)),
    ("elbow_flex", (-0.11257, -0.028, 1.73763e-16), (-3.63608e-16, 8.74301e-16, 1.5708)),
    ("wrist_flex", (-0.1349, 0.0052, 3.62355e-17), (4.02456e-15, 8.67362e-16, -1.5708)),
    ("wrist_roll", (5.55112e-17, -0.0611, 0.0181), (1.5708, 0.0486795, 3.14159)),
)
# gripper_frame: the point between the fingertips, in the gripper link's frame
_TCP = ((-0.0079, -0.000218121, -0.0981274), (0.0, 3.14159, 0.0))

# The points of the arm, base to fingertips: what is drawn as the arm's skeleton
SKELETON = ("base", "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "tcp")


def _rotation(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch),
                              math.cos(yaw), math.sin(yaw))
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _transform(xyz, rotation: np.ndarray) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = rotation
    m[:3, 3] = xyz
    return m


def _about_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return _transform((0, 0, 0), np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]))


def forward(joints: dict) -> dict[str, np.ndarray]:
    """Points of the arm in cm for joint angles in degrees.

    joints: {"shoulder_pan": deg, ...} or {"shoulder_pan.pos": deg, ...} (a pose of poses.yaml).
    Returns {"base", "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "tcp"}
    -> (x, y, z). "tcp" is between the fingertips; the others are the joint centres."""
    angle = {k.removesuffix(".pos"): v for k, v in joints.items()}
    m = np.eye(4)
    points = {"base": m[:3, 3] * 100}
    for name, xyz, rpy in _CHAIN:
        m = m @ _transform(xyz, _rotation(*rpy)) @ _about_z(math.radians(angle[name]))
        points[name] = m[:3, 3] * 100
    tip = m @ _transform(_TCP[0], _rotation(*_TCP[1]))
    points["tcp"] = tip[:3, 3] * 100
    return points


def tool_pitch_deg(joints: dict) -> float:
    """How steeply the gripper points down: 0 = horizontal, 90 = straight down, negative = up."""
    p = forward(joints)
    v = p["tcp"] - p["wrist_roll"]
    return math.degrees(math.atan2(-v[2], math.hypot(v[0], v[1])))


def reach_cm(joints: dict) -> float:
    """Horizontal distance of the fingertips from the shoulder_pan axis (the arm swings about it,
    3.9 cm in front of the frame's origin)."""
    p = forward(joints)
    return float(math.hypot(*(p["tcp"][:2] - p["shoulder_pan"][:2])))

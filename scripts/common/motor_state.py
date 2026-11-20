"""What the SO-101 servos report, and positions normalised by each arm's calibration range.

The arms run in degrees (lerobot's default; the box pipeline's poses and thresholds are in
degrees). The pick dataset stores positions normalised instead (docs/pick-dataset.md):

    body joints  [-1, 1] over the arm's calibrated range (lerobot RANGE_M100_100 / 100)
    gripper      [0, 1]  (lerobot RANGE_0_100 / 100; it is already in that mode in degrees mode)

Each arm uses its own calibration: the follower's for observations, the leader's for actions, so
"gripper closed" is 0 on both although their raw ranges differ. A policy's output is turned back
into degrees with the leader's calibration, exactly what teleoperation sends the follower.

Extra registers (velocity, load, current, temperature, voltage) are stored in register units,
see the table in docs/pick-dataset.md. The training state adds the gripper's current and load,
scaled to about [-1, 1].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
RESOLUTION = 4096  # STS3215 ticks per turn
# Read-only registers recorded every frame, in register units (docs/pick-dataset.md)
EXTRA_REGISTERS = {
    "velocity": "Present_Velocity",  # ticks/s, signed
    "load": "Present_Load",  # 0.1 % PWM duty, signed
    "current": "Present_Current",  # about 6.5 mA per unit
    "temperature": "Present_Temperature",  # degrees C
    "voltage": "Present_Voltage",  # 0.1 V
}
LOAD_FULL_SCALE = 1000  # Present_Load at 100 % duty
STATE_NAMES = [f"{j}.pos" for j in JOINTS] + ["gripper.current", "gripper.load"]
ACTION_NAMES = [f"{j}.pos" for j in JOINTS]


@dataclass(frozen=True)
class JointRange:
    range_min: int
    range_max: int
    drive_mode: int = 0


class Normaliser:
    """Degrees (lerobot DEGREES mode; gripper 0-100) <-> normalised units for one arm.

    Mirrors lerobot's MotorsBus._normalize: DEGREES is (ticks - mid) * 360 / 4095 around the middle
    of the calibrated range; RANGE_M100_100 clips to the range and maps it to -100..100, negated
    for drive_mode 1."""

    def __init__(self, ranges: dict[str, JointRange]):
        self.ranges = ranges

    @classmethod
    def from_calibration(cls, calibration: dict) -> "Normaliser":
        """calibration: lerobot's {motor: MotorCalibration} or the calibration JSON as a dict."""
        def get(c, k):
            return c[k] if isinstance(c, dict) else getattr(c, k)
        return cls({j: JointRange(int(get(calibration[j], "range_min")), int(get(calibration[j], "range_max")),
                                  int(get(calibration[j], "drive_mode") or 0)) for j in JOINTS})

    def to_unit(self, joint: str, value: float) -> float:
        if joint == "gripper":
            return value / 100.0
        r = self.ranges[joint]
        mid = (r.range_min + r.range_max) / 2
        ticks = min(r.range_max, max(r.range_min, value * (RESOLUTION - 1) / 360 + mid))
        unit = (ticks - r.range_min) / (r.range_max - r.range_min) * 2 - 1
        return -unit if r.drive_mode else unit

    def to_degrees(self, joint: str, unit: float) -> float:
        if joint == "gripper":
            return unit * 100.0
        r = self.ranges[joint]
        unit = -unit if r.drive_mode else unit
        ticks = (min(1.0, max(-1.0, unit)) + 1) / 2 * (r.range_max - r.range_min) + r.range_min
        return (ticks - (r.range_min + r.range_max) / 2) * 360 / (RESOLUTION - 1)

    def positions(self, joints_deg: dict) -> np.ndarray:
        """{'<joint>.pos': degrees} -> normalised vector in JOINTS order."""
        return np.array([self.to_unit(j, joints_deg[f"{j}.pos"]) for j in JOINTS], dtype=np.float32)

    def degrees(self, units) -> dict:
        """Normalised vector in JOINTS order -> {'<joint>.pos': degrees}."""
        return {f"{j}.pos": self.to_degrees(j, float(u)) for j, u in zip(JOINTS, units)}


def read_extras(bus) -> dict[str, np.ndarray]:
    """One sync read per register (about 1 ms each), in register units, JOINTS order."""
    out = {}
    for name, register in EXTRA_REGISTERS.items():
        values = bus.sync_read(register, list(JOINTS), normalize=False)
        out[name] = np.array([values[j] for j in JOINTS], dtype=np.float32)
    return out


def training_state(positions: np.ndarray, extras: dict, gripper_protection_current: float) -> np.ndarray:
    """observation.state: 6 normalised positions, gripper current / its Protection_Current,
    gripper load / full scale. The current and load scales are to be checked on the arm."""
    g = JOINTS.index("gripper")
    return np.concatenate([positions, [extras["current"][g] / gripper_protection_current,
                                       extras["load"][g] / LOAD_FULL_SCALE]]).astype(np.float32)


def dataset_features(cameras: dict[str, tuple[int, int]], embedding_dim: int) -> dict:
    """LeRobot features of the pick dataset. cameras: {name: (height, width)}.

    Only `observation.*` and `action` reach a policy (lerobot's dataset_to_policy_features skips
    other keys): `motors.*` and `item.*` are recorded for later experiments, not trained on."""
    features = {
        "observation.state": {"dtype": "float32", "shape": (len(STATE_NAMES),), "names": STATE_NAMES},
        "action": {"dtype": "float32", "shape": (len(ACTION_NAMES),), "names": ACTION_NAMES},
    }
    for name, (h, w) in cameras.items():
        features[f"observation.images.{name}"] = {"dtype": "video", "shape": (h, w, 3),
                                                  "names": ["height", "width", "channels"]}
    for name in EXTRA_REGISTERS:
        features[f"motors.{name}"] = {"dtype": "float32", "shape": (len(JOINTS),), "names": list(JOINTS)}
    features["item.embedding"] = {"dtype": "float32", "shape": (embedding_dim,), "names": None}
    features["item.box"] = {"dtype": "float32", "shape": (4,), "names": ["x0", "y0", "x1", "y1"]}
    return features

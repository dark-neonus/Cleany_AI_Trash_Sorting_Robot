"""Run a lerobot command with cameras captured at their full field of view.

Usage:
    python lerobot_wide_fov.py <teleoperate|record|rollout|replay> [lerobot args...]

Low resolutions such as 640x480 are center crops of the sensor on our cameras.
This wrapper opens each camera in a full-FOV mode and downscales every frame to
the width/height from --robot.cameras, so the model and visualization still get
the configured resolution.

Full-FOV capture modes are passed as JSON in CAMERA_CAPTURE_MODES, keyed by device path:
    CAMERA_CAPTURE_MODES='{"/dev/v4l/by-id/...": [800, 600]}'
Cameras not listed are captured as usual.

Follower servo motion limits can be set with SERVO_ACCELERATION and
SERVO_MAX_VELOCITY_DEG, and replay playback speed with REPLAY_SPEED (see below).
Servo torque is switched on one servo at a time, TORQUE_STAGGER_S apart (default 0.5).
"""

import importlib
import json
import os
import sys
import time

import cv2

from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
from lerobot.motors.feetech.feetech import FeetechMotorsBus
from lerobot.robots.so_follower.so_follower import SOFollower

CAPTURE_MODES = {
    os.path.realpath(path): tuple(size)
    for path, size in json.loads(os.environ.get("CAMERA_CAPTURE_MODES", "{}")).items()
}


def _capture_mode(camera: OpenCVCamera) -> tuple[int, int] | None:
    return CAPTURE_MODES.get(os.path.realpath(str(camera.index_or_path)))


_original_validate_width_and_height = OpenCVCamera._validate_width_and_height
_original_read_from_hardware = OpenCVCamera._read_from_hardware


def _validate_width_and_height(self: OpenCVCamera) -> None:
    mode = _capture_mode(self)
    if mode is None:
        return _original_validate_width_and_height(self)

    # Set the hardware to the full-FOV mode, then restore the output size lerobot expects.
    output_size = (self.capture_width, self.capture_height)
    self.capture_width, self.capture_height = mode
    try:
        _original_validate_width_and_height(self)
    finally:
        self.capture_width, self.capture_height = output_size


def _read_from_hardware(self: OpenCVCamera):
    frame = _original_read_from_hardware(self)
    if _capture_mode(self) is None:
        return frame

    h, w = frame.shape[:2]
    if (w, h) != (self.capture_width, self.capture_height):
        frame = cv2.resize(frame, (self.capture_width, self.capture_height), interpolation=cv2.INTER_AREA)
    return frame


OpenCVCamera._validate_width_and_height = _validate_width_and_height
OpenCVCamera._read_from_hardware = _read_from_hardware


# Follower servo motion limits, applied after lerobot configures the motors (which sets
# Acceleration to the maximum, 254). Both registers live in servo RAM, so they reset on
# power cycle and on the next connect without these env vars.
#   SERVO_ACCELERATION:      0-254, in units of 100 steps/s^2 (254 = lerobot default)
#   SERVO_MAX_VELOCITY_DEG:  max joint speed in deg/s (0 = unlimited)
STEPS_PER_DEGREE = 4096 / 360
SERVO_ACCELERATION = os.environ.get("SERVO_ACCELERATION")
SERVO_MAX_VELOCITY_DEG = os.environ.get("SERVO_MAX_VELOCITY_DEG")

_original_follower_configure = SOFollower.configure


def _follower_configure(self: SOFollower) -> None:
    _original_follower_configure(self)
    for motor in self.bus.motors:
        if SERVO_ACCELERATION is not None:
            self.bus.write("Acceleration", motor, int(SERVO_ACCELERATION))
        if SERVO_MAX_VELOCITY_DEG is not None:
            self.bus.write("Goal_Velocity", motor, round(float(SERVO_MAX_VELOCITY_DEG) * STEPS_PER_DEGREE))
    print(f"Follower motion limits: acceleration={SERVO_ACCELERATION}, max_velocity={SERVO_MAX_VELOCITY_DEG} deg/s")


if SERVO_ACCELERATION is not None or SERVO_MAX_VELOCITY_DEG is not None:
    SOFollower.configure = _follower_configure


# Soft start: lerobot switches torque on for all servos back to back, so they all start
# pulling current at once. That spike can make a servo miss its reply ("There is no status
# packet") and abort the connect. Switch them on one at a time from servo 1 (base) to
# servo 6 (gripper), TORQUE_STAGGER_S apart, and retry each write a couple of times.
TORQUE_STAGGER_S = float(os.environ.get("TORQUE_STAGGER_S", "0.5"))

_original_enable_torque = FeetechMotorsBus.enable_torque


def _enable_torque_staggered(self: FeetechMotorsBus, motors=None, num_retry: int = 0) -> None:
    for i, motor in enumerate(self._get_motors_list(motors)):
        if i > 0:
            time.sleep(TORQUE_STAGGER_S)
        _original_enable_torque(self, motor, num_retry=max(num_retry, 2))


FeetechMotorsBus.enable_torque = _enable_torque_staggered

COMMANDS = {
    "teleoperate": "lerobot.scripts.lerobot_teleoperate",
    "record": "lerobot.scripts.lerobot_record",
    "rollout": "lerobot.scripts.lerobot_rollout",
    "replay": "lerobot.scripts.lerobot_replay",
}

# Replay playback speed: lerobot-replay paces frames by the dataset fps, so stretch each
# frame period by 1/REPLAY_SPEED (e.g. 0.5 = half speed). REPLAY_FPS is the recording's fps.
REPLAY_SPEED = os.environ.get("REPLAY_SPEED")
REPLAY_FPS = os.environ.get("REPLAY_FPS", "30")


def _slow_down_replay(module) -> None:
    extra_s = (1 / float(REPLAY_SPEED) - 1) / float(REPLAY_FPS)
    original_sleep = module.precise_sleep
    module.precise_sleep = lambda seconds: original_sleep(max(seconds + extra_s, 0.0))
    print(f"Replay speed: {REPLAY_SPEED}x")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"Usage: {sys.argv[0]} <{'|'.join(COMMANDS)}> [lerobot args...]")
    command = sys.argv.pop(1)
    module = importlib.import_module(COMMANDS[command])
    if command == "replay" and REPLAY_SPEED is not None:
        _slow_down_replay(module)
    module.main()

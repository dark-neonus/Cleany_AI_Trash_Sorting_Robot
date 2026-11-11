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
Servo torque is switched on one servo at a time, TORQUE_STAGGER_S apart (default 0.15).
Cameras are opened while the imports run (camera_preopen.py).
Every command gets a red emergency stop button (estop.py) that releases the follower's torque
(arm_estop.py). The trash drop panel (drop_panel.py) is shown too; DROP_PANEL=false turns only
the drop controls off.
"""

import importlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import camera_preopen

CAPTURE_MODES = {
    os.path.realpath(path): tuple(size)
    for path, size in json.loads(os.environ.get("CAMERA_CAPTURE_MODES", "{}")).items()
}

# Start opening the cameras now: the imports below take ~4.5 s, about as long as the front
# camera needs to deliver its first frame (see camera_preopen.py).
if __name__ == "__main__":
    camera_preopen.start(sys.argv[2:], CAPTURE_MODES)

import cv2  # noqa: E402

import screenshot  # noqa: E402
from lerobot.cameras.opencv.camera_opencv import OpenCVCamera  # noqa: E402
from lerobot.motors.feetech.feetech import FeetechMotorsBus  # noqa: E402
from lerobot.robots.so_follower.so_follower import SOFollower  # noqa: E402


def _capture_mode(camera: OpenCVCamera) -> tuple[int, int] | None:
    return CAPTURE_MODES.get(os.path.realpath(str(camera.index_or_path)))


_original_validate_width_and_height = OpenCVCamera._validate_width_and_height
_original_read_from_hardware = OpenCVCamera._read_from_hardware


def _validate_width_and_height(self: OpenCVCamera) -> None:
    mode = _capture_mode(self)
    # Set the hardware to the full-FOV mode, then restore the output size lerobot expects.
    output_size = (self.capture_width, self.capture_height)
    if mode is not None:
        self.capture_width, self.capture_height = mode
    try:
        # A pre-opened camera already streams at this size; writing it again restarts the stream.
        if getattr(self, "_preopened", False) and (self.capture_width, self.capture_height) == (
            int(round(self.videocapture.get(cv2.CAP_PROP_FRAME_WIDTH))),
            int(round(self.videocapture.get(cv2.CAP_PROP_FRAME_HEIGHT))),
        ):
            return
        _original_validate_width_and_height(self)
    finally:
        self.capture_width, self.capture_height = output_size


def _read_from_hardware(self: OpenCVCamera):
    frame = _original_read_from_hardware(self)
    if _capture_mode(self) is not None:
        h, w = frame.shape[:2]
        if (w, h) != (self.capture_width, self.capture_height):
            frame = cv2.resize(frame, (self.capture_width, self.capture_height), interpolation=cv2.INTER_AREA)
    screenshot.remember_frame(str(self.index_or_path), frame)  # for the panels' screenshot button
    return frame


_original_camera_connect = OpenCVCamera.connect


def _camera_connect(self: OpenCVCamera, warmup: bool = True) -> None:
    """OpenCVCamera.connect, using the camera camera_preopen.py already opened if there is one."""
    capture = camera_preopen.take(str(self.index_or_path))
    if capture is None:
        camera_preopen.wait_for_camera_config()
        return _original_camera_connect(self, warmup)
    cv2.setNumThreads(1)  # as lerobot's connect
    self.videocapture = capture
    self._preopened = True
    try:
        self._configure_capture_settings()
        self._start_read_thread()
        if warmup and self.warmup_s > 0:
            self.async_read(timeout_ms=self.warmup_s * 1000)
    except BaseException:
        self._cleanup_resources()
        self._reset_connection_settings()
        raise
    finally:
        self._preopened = False
    print(f"{self} connected (pre-opened).")


OpenCVCamera._validate_width_and_height = _validate_width_and_height
OpenCVCamera._read_from_hardware = _read_from_hardware
OpenCVCamera.connect = _camera_connect


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


# Connect the follower's cameras in parallel and without the fixed warmup: lerobot connects
# them one after another and each one keeps reading frames for its whole warmup_s. Exposure,
# gain and white balance are fixed, so a camera is ready as soon as its first frame arrives
# (the front camera needs ~2.5 s for that). CAMERA_FIRST_FRAME_TIMEOUT_S bounds the wait.
FIRST_FRAME_TIMEOUT_S = float(os.environ.get("CAMERA_FIRST_FRAME_TIMEOUT_S", "10"))
_original_follower_connect = SOFollower.connect


def _connect_camera(cam: OpenCVCamera) -> None:
    cam.connect(warmup=False)
    try:
        cam.async_read(timeout_ms=FIRST_FRAME_TIMEOUT_S * 1000)
    except BaseException:
        cam.disconnect()
        raise


def _follower_connect(self: SOFollower, calibrate: bool = True) -> None:
    # The motors are configured (staggered torque, ~1 s) while the cameras start, not after.
    cameras = list(self.cameras.values())
    with ThreadPoolExecutor(max_workers=max(len(cameras), 1)) as pool:
        futures = [pool.submit(_connect_camera, cam) for cam in cameras]
        configured = False
        try:
            self.bus.connect()
            if not self.is_calibrated and calibrate:
                self.calibrate()
            self.configure()
            configured = True
        finally:
            try:
                for future in futures:  # camera errors surface here
                    future.result()
            except BaseException:
                if configured:  # do not leave the arm stiff after a failed start
                    self.bus.disable_torque()
                raise
    print(f"{self} connected.")


SOFollower.connect = _follower_connect

# Soft start: lerobot switches torque on for all servos back to back, so they all start
# pulling current at once. That spike can make a servo miss its reply ("There is no status
# packet") and abort the connect. Switch them on one at a time from servo 1 (base) to
# servo 6 (gripper), TORQUE_STAGGER_S apart, and retry each write a couple of times.
TORQUE_STAGGER_S = float(os.environ.get("TORQUE_STAGGER_S", "0.15"))

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
    drop_enabled = os.environ.get("DROP_PANEL", "true") != "false"
    import arm_estop

    arm_estop.install()  # the red emergency stop button releases the follower's torque
    # Control panel window with countdown and End/Discard/Stop buttons (see record_panel.py).
    if command == "record" and os.environ.get("RECORD_PANEL", "true") != "false":
        import record_panel

        record_panel.install(module, title=os.environ.get("RECORD_PANEL_TITLE", "Cleany recorder"))
    # Trash drop controls: inside the recording panel when it is shown, else in their own window.
    elif drop_enabled:
        import drop_panel

        drop_panel.start_drop_panel()
    else:
        import estop

        estop.start_estop_window()
    module.main()

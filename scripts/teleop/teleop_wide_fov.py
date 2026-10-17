"""Run lerobot-teleoperate with cameras captured at their full field of view.

Low resolutions such as 640x480 are center crops of the sensor on our cameras.
This wrapper opens each camera in a full-FOV mode and downscales every frame to
the width/height from --robot.cameras, so the model and visualization still get
the configured resolution.

Full-FOV capture modes are passed as JSON in CAMERA_CAPTURE_MODES, keyed by device path:
    CAMERA_CAPTURE_MODES='{"/dev/v4l/by-id/...": [800, 600]}'
Cameras not listed are captured as usual.
"""

import json
import os

import cv2

from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
from lerobot.scripts.lerobot_teleoperate import main

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

if __name__ == "__main__":
    main()

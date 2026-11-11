"""Screenshot button for the control panels: saves the latest front and wrist camera frames.

lerobot_wide_fov.py calls remember_frame() for every frame an OpenCV camera reads, so the
saved images have exactly the resolution the cameras run at (after the full-FOV downscale).
Files go to recordings/screenshots/screenshot_YYYY_MM_DD_HHMMSS_<front|wrist>.png (a _2, _3, ...
suffix is added when the name is taken). Cameras are told apart by FRONT_CAMERA/WRIST_CAMERA
(device paths exported by config/hardware.sh).
"""

import datetime
import os
import threading
import tkinter as tk
from pathlib import Path

import cv2

SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "recordings" / "screenshots"

_NAMES = {os.path.realpath(path): name for name, path in
          (("front", os.environ.get("FRONT_CAMERA")), ("wrist", os.environ.get("WRIST_CAMERA"))) if path}
_frames: dict[str, object] = {}
_lock = threading.Lock()


def remember_frame(camera_path: str, frame) -> None:
    name = _NAMES.get(os.path.realpath(camera_path), os.path.basename(str(camera_path)))
    with _lock:
        _frames[name] = frame


def save_screenshots() -> str:
    """Write the latest frame of every camera; returns a short status text."""
    with _lock:
        frames = {name: frame.copy() for name, frame in _frames.items()}
    if not frames:
        return "No camera frames yet"
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y_%m_%d_%H%M%S")  # same for front and wrist
    saved = []
    for name, frame in sorted(frames.items()):
        path = SCREENSHOT_DIR / f"screenshot_{stamp}_{name}.png"
        n = 2
        while path.exists():
            path = SCREENSHOT_DIR / f"screenshot_{stamp}_{name}_{n}.png"
            n += 1
        cv2.imwrite(str(path), frame)  # frames are BGR, as read from the camera
        saved.append(f"{path.name} ({frame.shape[1]}x{frame.shape[0]})")
    return "Saved " + ", ".join(saved)


def add_screenshot_button(parent: tk.Misc) -> tk.Frame:
    frame = tk.Frame(parent)
    frame.pack(padx=16, pady=(0, 8), fill="x")
    status = tk.Label(frame, font=("Sans", 9), fg="#666666", wraplength=380, justify="left")

    def take() -> None:
        status.config(text=save_screenshots())

    tk.Button(frame, text="Screenshot (front + wrist)  📷", command=take).pack(fill="x")
    status.pack(anchor="w")
    return frame

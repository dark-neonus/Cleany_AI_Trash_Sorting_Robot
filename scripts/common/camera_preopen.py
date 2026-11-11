"""Open the OpenCV cameras while Python is still importing torch and lerobot.

A camera takes seconds to deliver its first frame (the front C270 ~3 s: ~0.7 s to open,
~2.3 s to the first frame), and the imports take ~4.5 s, so lerobot_wide_fov.py calls start()
before its heavy imports. Each camera from --robot.cameras is opened in a background thread
with the same fourcc/size/fps lerobot will ask for, and read once. take() then hands the open
camera to OpenCVCamera.connect, which skips the size write when it already matches: on V4L2,
setting width and height restarts the stream (~1 s).

A camera that fails to open here is left to lerobot, which opens it as usual and reports the
error. Only imports cv2, so it does not delay the heavy imports.

configure_cameras (config/hardware.sh) may run in the background; its PID is then in
CAMERA_CONFIG_PID and wait_for_camera_config() blocks until it finished, so the driver
settings are applied before a camera is opened.
"""

import json
import os
import threading
import time

import cv2

CONFIG_WAIT_TIMEOUT_S = 15

_threads: dict[str, threading.Thread] = {}
_captures: dict[str, cv2.VideoCapture] = {}
_lock = threading.Lock()


def _process_running(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"  # a zombie has finished
    except (OSError, IndexError):
        return False


def wait_for_camera_config() -> None:
    pid = os.environ.get("CAMERA_CONFIG_PID")
    if not pid:
        return
    deadline = time.monotonic() + CONFIG_WAIT_TIMEOUT_S
    while _process_running(int(pid)) and time.monotonic() < deadline:
        time.sleep(0.02)


def _cameras_arg(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg.startswith("--robot.cameras="):
            return arg.split("=", 1)[1]
        if arg == "--robot.cameras" and i + 1 < len(argv):
            return argv[i + 1]
    return None


def _open(key: str, camera: dict, size: tuple[int, int]) -> None:
    wait_for_camera_config()
    cap = cv2.VideoCapture(camera["index_or_path"], int(camera.get("backend", cv2.CAP_ANY)))
    try:
        if not cap.isOpened():
            raise ConnectionError
        if camera.get("fourcc"):
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*camera["fourcc"]))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        if camera.get("fps"):
            cap.set(cv2.CAP_PROP_FPS, float(camera["fps"]))
        ok, _ = cap.read()  # waits for the first frame
        if not ok:
            raise ConnectionError
    except Exception:
        cap.release()
        return
    with _lock:
        _captures[key] = cap


def start(argv: list[str], capture_modes: dict[str, tuple[int, int]]) -> None:
    """Start opening every OpenCV camera with a device path in --robot.cameras.

    capture_modes maps realpath -> full-FOV (width, height) capture size, as in lerobot_wide_fov.py.
    """
    try:
        cameras = json.loads(_cameras_arg(argv) or "{}")
    except json.JSONDecodeError:
        return  # lerobot reports the bad argument
    for camera in cameras.values():
        path = camera.get("index_or_path")
        if camera.get("type") != "opencv" or not isinstance(path, str) or not camera.get("width"):
            continue
        key = os.path.realpath(path)
        size = capture_modes.get(key, (camera["width"], camera["height"]))
        thread = threading.Thread(target=_open, args=(key, camera, size), daemon=True,
                                  name=f"preopen {os.path.basename(path)}")
        _threads[key] = thread
        thread.start()


def take(path: str) -> cv2.VideoCapture | None:
    """The pre-opened capture for path (waits for it to finish opening), or None."""
    key = os.path.realpath(path)
    thread = _threads.pop(key, None)
    if thread is None:
        return None
    thread.join()
    with _lock:
        return _captures.pop(key, None)

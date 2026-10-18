"""Find fixed (manual) camera settings that reproduce what auto mode picks right now.

Usage:
    python tune_cameras.py <device> <width> <height> [--gain N] [--wb-temp K] [--max-exposure N]

Auto exposure and auto white balance change with the light, so the image looks different
(and frames can take longer) from session to session and laptop to laptop. Run this under
the final box lighting. It lets auto mode settle and measures the image, then switches to
manual and searches, in order:
  1. white balance temperature giving the same blue/red balance as auto (kept on auto if no
     manual value gets close, as on our wrist camera)
  2. exposure time (gain fixed) giving the same brightness
  3. the digital brightness control, only if exposure hit its cap and the image is still dark
Progress goes to stderr; the final v4l2 control string goes to stdout (scripts/tools/
tune_cameras.sh stores it in scripts/config/camera_settings.sh).

Exposure is capped at one frame period at 30 fps (exposure_time_absolute is in 100 us
units, so 333 = 33.3 ms), otherwise the camera cannot keep 30 fps.
"""

import argparse
import subprocess
import sys
import time

import cv2
import numpy as np


def v4l2_set(device: str, **controls) -> None:
    args = ",".join(f"{k}={v}" for k, v in controls.items())
    subprocess.run(["v4l2-ctl", "-d", device, "-c", args], check=True)


def v4l2_get(device: str, control: str) -> int:
    out = subprocess.run(["v4l2-ctl", "-d", device, "-C", control], check=True, capture_output=True, text=True)
    return int(out.stdout.split(":")[1])


def control_range(device: str, control: str) -> tuple[int, int]:
    out = subprocess.run(["v4l2-ctl", "-d", device, "--list-ctrls"], check=True, capture_output=True, text=True)
    line = next(line for line in out.stdout.splitlines() if line.split()[:1] == [control])
    return int(line.split("min=")[1].split()[0]), int(line.split("max=")[1].split()[0])


def open_camera(device: str, width: int, height: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 30)
    return cap


def measure(cap: cv2.VideoCapture, settle_frames: int = 15, frames: int = 10) -> tuple[float, float]:
    """Mean brightness and blue/red ratio over a few frames (BGR)."""
    for _ in range(settle_frames):
        cap.read()
    means = np.mean([cap.read()[1].reshape(-1, 3).mean(axis=0) for _ in range(frames)], axis=0)
    return float(means.mean()), float(means[0] / max(means[2], 1e-3))


def search(device: str, cap: cv2.VideoCapture, control: str, lo: int, hi: int, target: float,
           increasing: bool, metric: int, step: int = 1) -> int:
    """Binary search the control value whose measure()[metric] is closest to target."""
    best = (lo, float("inf"))
    while lo <= hi:
        value = (lo + hi) // 2 // step * step
        v4l2_set(device, **{control: value})
        result = measure(cap)[metric]
        log(f"  {control} {value:5d} -> {result:.2f}")
        if abs(result - target) < best[1]:
            best = (value, abs(result - target))
        if (result < target) == increasing:
            lo = value + step
        else:
            hi = value - step
    v4l2_set(device, **{control: best[0]})
    return best[0]


def log(*args) -> None:
    print(*args, file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("device")
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("--gain", type=int, help="fixed gain (default: the camera's current value)")
    parser.add_argument("--wb-temp", type=int, help="fixed white balance in K (default: match auto)")
    parser.add_argument("--max-exposure", type=int, default=333, help="exposure cap, 100 us units")
    args = parser.parse_args()
    dev = args.device

    cap = open_camera(dev, args.width, args.height)
    v4l2_set(dev, auto_exposure=3, white_balance_automatic=1, brightness=128)
    time.sleep(3)
    target_brightness, target_balance = measure(cap, settle_frames=60)
    gain = args.gain if args.gain is not None else v4l2_get(dev, "gain")
    log(f"auto: brightness {target_brightness:.1f}/255, blue/red {target_balance:.2f}; using gain {gain}")

    v4l2_set(dev, auto_exposure=1, white_balance_automatic=0)
    exp_min, _ = control_range(dev, "exposure_time_absolute")
    v4l2_set(dev, gain=gain, exposure_time_absolute=min(args.max_exposure, 150))

    # Sweep rather than binary search: on some cameras (our wrist one) blue/red is not monotonic
    # in the temperature setting. If no setting gets close to auto, keep auto white balance.
    if args.wb_temp is None:
        wb_min, wb_max = control_range(dev, "white_balance_temperature")
        wb, wb_error = None, float("inf")
        for temp in range(max(wb_min, 2000), wb_max + 1, 250):
            v4l2_set(dev, white_balance_temperature=temp)
            balance = measure(cap)[1]
            log(f"  white_balance_temperature {temp:5d} -> {balance:.2f}")
            if abs(balance - target_balance) < wb_error:
                wb, wb_error = temp, abs(balance - target_balance)
        if wb_error > 0.1:
            log(f"no manual white balance gets close to auto (best {wb} K, off by {wb_error:.2f}): keeping auto")
            wb = None
            v4l2_set(dev, white_balance_automatic=1)
        else:
            v4l2_set(dev, white_balance_temperature=wb)
    else:
        wb = args.wb_temp
        v4l2_set(dev, white_balance_temperature=wb)

    exposure = search(dev, cap, "exposure_time_absolute", exp_min, args.max_exposure, target_brightness,
                      increasing=True, metric=0)
    brightness = 128
    if measure(cap)[0] < target_brightness - 10:
        log("exposure capped by 30 fps and still darker than auto: raising digital brightness")
        brightness = search(dev, cap, "brightness", 128, 255, target_brightness, increasing=True, metric=0)

    final_brightness, final_balance = measure(cap)
    cap.release()
    log(f"\nmanual: brightness {final_brightness:.1f} (auto {target_brightness:.1f}), "
          f"blue/red {final_balance:.2f} (auto {target_balance:.2f})")
    white_balance = "white_balance_automatic=1" if wb is None else (
        f"white_balance_automatic=0,white_balance_temperature={wb}")
    print(f"auto_exposure=1,exposure_time_absolute={exposure},gain={gain},brightness={brightness},{white_balance}")


if __name__ == "__main__":
    main()

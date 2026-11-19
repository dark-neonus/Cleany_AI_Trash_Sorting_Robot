"""Pure decisions of the box pipeline (scripts/run/box_pipeline.py): no arm, camera, GPU or window.

Everything here works on plain numbers, dicts and numpy images, so tests/test_box_pipeline.py can
check it without hardware. See docs/box-pipeline.md for how the pieces fit together.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
JOINT_KEYS = tuple(f"{j}.pos" for j in JOINTS)
GRIPPER = "gripper.pos"
# Named poses the pipeline moves between (captured with scripts/tools/capture_poses.sh).
REQUIRED_POSES = ("home", "hover", "centre", "metal_bin", "plastic_bin")
SORTABLE = ("metal", "plastic")


# --- config --------------------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def load_poses(path: Path, required=REQUIRED_POSES) -> dict[str, dict[str, float]]:
    """Named joint poses from config/poses.yaml. Fails if a required pose or joint is missing:
    the arm must never move to a guessed pose."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: capture the poses with scripts/tools/capture_poses.sh")
    poses = load_yaml(path).get("poses", {})
    missing = [name for name in required if name not in poses]
    if missing:
        raise KeyError(f"{path} has no pose {', '.join(missing)}: capture it with "
                       f"scripts/tools/capture_poses.sh {' '.join(missing)}")
    for name, pose in poses.items():
        absent = [k for k in JOINT_KEYS if k not in pose]
        if absent:
            raise KeyError(f"pose '{name}' in {path} lacks {', '.join(absent)}")
    return {name: {k: float(pose[k]) for k in JOINT_KEYS} for name, pose in poses.items()}


# --- motion --------------------------------------------------------------------------------------

def min_jerk(t: float) -> float:
    """Minimum-jerk profile 0..1: zero velocity and acceleration at both ends."""
    t = min(max(t, 0.0), 1.0)
    return t * t * t * (10 - 15 * t + 6 * t * t)


def move_duration(start: dict, target: dict, speed_deg_s: float, min_s: float) -> float:
    """Seconds for a joint move: the largest joint distance at speed_deg_s, at least min_s.
    A minimum-jerk move peaks at 1.875x its mean speed, so speed_deg_s is the mean."""
    distance = max((abs(target[k] - start[k]) for k in target if k in start), default=0.0)
    return max(distance / speed_deg_s, min_s)


def interpolate(start: dict, target: dict, s: float) -> dict:
    return {k: start[k] + (target[k] - start[k]) * s for k in target}


def trajectory(start: dict, target: dict, speed_deg_s: float, min_s: float, fps: float) -> list[dict]:
    """Joint targets, one per control step, from start to target along a minimum-jerk profile."""
    steps = max(1, math.ceil(move_duration(start, target, speed_deg_s, min_s) * fps))
    return [interpolate(start, target, min_jerk(i / steps)) for i in range(1, steps + 1)]


def max_joint_distance(a: dict, b: dict, include_gripper: bool = False) -> float:
    return max(abs(a[k] - b[k]) for k in JOINT_KEYS if k in a and k in b and (include_gripper or k != GRIPPER))


def hold_command(measured_gripper: float, squeeze_deg: float) -> float:
    """Gripper goal while carrying: a few degrees more closed than measured, not fully closed,
    so the servo holds the item by position instead of stalling against it the whole carry."""
    return measured_gripper - squeeze_deg


# --- grasp check ---------------------------------------------------------------------------------

@dataclass
class GraspCheck:
    """Did the grasp succeed? Two conditions, both for hold_s without a break:

    * blocked: the measured gripper position stays more than blocked_deg above the commanded one
      (the fingers were told to close further than they can: something is between them);
    * raised: lift_joint has come back at least lift_deg from the farthest it got from the hover
      pose during this attempt (the item has been lifted, not only grasped).

    Sign-free, so it does not depend on which way the joints are calibrated.
    """

    hover: dict
    blocked_deg: float = 4.0
    lift_joint: str = "shoulder_lift.pos"
    lift_deg: float = 8.0
    hold_s: float = 0.3
    farthest: float = 0.0
    ok_since: float | None = None

    def blocked(self, measured: dict, commanded: dict) -> bool:
        return measured[GRIPPER] - commanded[GRIPPER] > self.blocked_deg

    def raised(self, measured: dict) -> bool:
        away = abs(measured[self.lift_joint] - self.hover[self.lift_joint])
        self.farthest = max(self.farthest, away)
        return self.farthest - away >= self.lift_deg

    def update(self, now: float, measured: dict, commanded: dict) -> bool:
        """Feed one control step; True once both conditions have held for hold_s."""
        ok = self.raised(measured) and self.blocked(measured, commanded)
        if not ok:
            self.ok_since = None
            return False
        self.ok_since = now if self.ok_since is None else self.ok_since
        return now - self.ok_since >= self.hold_s


def slipped(measured_gripper: float, grasped_at: float, slip_deg: float) -> bool:
    """While carrying: the gripper closed further than where it closed on the item."""
    return measured_gripper < grasped_at - slip_deg


# --- image trigger and settle gate ---------------------------------------------------------------

def _gray(frame_rgb: np.ndarray, region) -> np.ndarray:
    h, w = frame_rgb.shape[:2]
    sx, sy = w / 640, h / 480  # regions are given for a 640x480 image
    x0, y0, x1, y1 = region
    crop = frame_rgb[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)].astype(np.float32)
    gray = crop @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    # 4x4 box blur by downsampling: removes sensor noise and JPEG blocks
    gh, gw = gray.shape[0] // 4 * 4, gray.shape[1] // 4 * 4
    return gray[:gh, :gw].reshape(gh // 4, 4, gw // 4, 4).mean(axis=(1, 3))


def changed_fraction(a: np.ndarray, b: np.ndarray, region, pixel_diff: float) -> float:
    """Share of the region whose brightness differs by more than pixel_diff between two frames."""
    return float(np.mean(np.abs(_gray(a, region) - _gray(b, region)) > pixel_diff))


@dataclass
class BackgroundTrigger:
    """Is something in the tray? Compares the front image with an empty-tray reference taken
    with the arm at home and the doors closed. Independent of what the item is, so it also sees
    items YOLO has never been trained on."""

    region: tuple
    pixel_diff: float = 25
    min_fraction: float = 0.004
    reference: np.ndarray | None = None

    def set_reference(self, frame_rgb: np.ndarray):
        self.reference = frame_rgb.copy()

    def fraction(self, frame_rgb: np.ndarray) -> float:
        return changed_fraction(self.reference, frame_rgb, self.region, self.pixel_diff)

    def occupied(self, frame_rgb: np.ndarray) -> bool:
        return self.fraction(frame_rgb) > self.min_fraction


@dataclass
class SettleGate:
    """Has the scene stopped moving? Frame-to-frame change below max_fraction for settle_s."""

    region: tuple
    pixel_diff: float = 25
    max_fraction: float = 0.002
    settle_s: float = 0.5
    previous: np.ndarray | None = None
    still_since: float | None = None

    def update(self, now: float, frame_rgb: np.ndarray) -> bool:
        moving = (self.previous is None or
                  changed_fraction(self.previous, frame_rgb, self.region, self.pixel_diff) > self.max_fraction)
        self.previous = frame_rgb
        if moving:
            self.still_since = None
            return False
        self.still_since = now if self.still_since is None else self.still_since
        return now - self.still_since >= self.settle_s


# --- items ---------------------------------------------------------------------------------------

def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Item:
    box: list[float]  # median box over the settled frames, 640x480-scaled like the frames
    boxes: list[list[float]] = field(default_factory=list)
    crops: list[np.ndarray] = field(default_factory=list)
    votes: list[tuple[str, float]] = field(default_factory=list)  # YOLO (class, confidence) per frame
    cls: str = "other"
    info: dict = field(default_factory=dict)


def group_detections(frames: list[list[dict]], min_iou: float = 0.3, min_share: float = 0.5) -> list[Item]:
    """Turn per-frame detections ({"box", "class", "conf", "crop"?}) of the settled frames into items.
    A detection joins the item whose median box overlaps it most; items seen in fewer than
    min_share of the frames are dropped (flicker)."""
    items: list[Item] = []
    for detections in frames:
        for d in detections:
            best = max(items, key=lambda it: iou(it.box, d["box"]), default=None)
            if best is None or iou(best.box, d["box"]) < min_iou:
                best = Item(box=list(d["box"]))
                items.append(best)
            best.boxes.append(list(d["box"]))
            best.box = np.median(np.array(best.boxes), axis=0).tolist()
            best.votes.append((d.get("class", "item"), d.get("conf", 0.0)))
            if d.get("crop") is not None:
                best.crops.append(d["crop"])
    return [it for it in items if len(it.boxes) >= min_share * max(len(frames), 1)]


def yolo_vote(item: Item, min_conf: float) -> str:
    """Class from YOLO alone (no DINO): the summed confidence per class; 'other' if the winner's
    mean confidence is below min_conf."""
    totals: dict[str, list[float]] = {}
    for cls, conf in item.votes:
        totals.setdefault(cls, []).append(conf)
    if not totals:
        return "other"
    cls, confs = max(totals.items(), key=lambda kv: sum(kv[1]))
    return cls if cls in SORTABLE and np.mean(confs) >= min_conf else "other"


def free_space(item: Item, items: list[Item]) -> float:
    """Distance in pixels from the item's box to the nearest other box (inf when alone)."""
    def gap(a, b):
        dx = max(b[0] - a[2], a[0] - b[2], 0.0)
        dy = max(b[1] - a[3], a[1] - b[3], 0.0)
        return math.hypot(dx, dy)
    return min((gap(item.box, o.box) for o in items if o is not item), default=math.inf)


def choose_target(items: list[Item], failed: list[tuple[list[float], int]], max_attempts: int,
                  max_overlap: float = 0.3) -> Item | None:
    """The sortable item with the most room around it. Skipped: items that overlap another one
    heavily (the fingers have no room) and items that already failed max_attempts times."""
    def attempts(item):
        return max((n for box, n in failed if iou(box, item.box) > 0.3), default=0)

    candidates = [it for it in items if it.cls in SORTABLE and attempts(it) < max_attempts
                  and all(iou(it.box, o.box) <= max_overlap for o in items if o is not it)]
    return max(candidates, key=lambda it: free_space(it, items), default=None)


def record_failure(failed: list[tuple[list[float], int]], box) -> int:
    """Count one failed attempt on the item at box; returns its number of failures so far."""
    for i, (old, n) in enumerate(failed):
        if iou(old, box) > 0.3:
            failed[i] = (list(box), n + 1)
            return n + 1
    failed.append((list(box), 1))
    return 1


def crop_box(frame_rgb: np.ndarray, box, pad: float = 0.15, min_px: int = 16) -> np.ndarray | None:
    """The box (640x480 coordinates) cut from the frame with pad of its size on each side."""
    h, w = frame_rgb.shape[:2]
    sx, sy = w / 640, h / 480
    x0, y0, x1, y1 = box
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    x0, x1 = int(max(0, (x0 - px) * sx)), int(min(w, (x1 + px) * sx))
    y0, y1 = int(max(0, (y0 - py) * sy)), int(min(h, (y1 + py) * sy))
    if x1 - x0 < min_px or y1 - y0 < min_px:
        return None
    return frame_rgb[y0:y1, x0:x1]

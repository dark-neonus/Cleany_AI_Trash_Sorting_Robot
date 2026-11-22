"""The logic of the pose capture tool (scripts/tools/capture_poses.py), without arm or window:
reading and writing config/poses.yaml, old names, the steadiness check, what is still missing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from box_logic import GRIPPER, JOINT_KEYS
from pose_catalog import BY_NAME, NAMES, NEEDED_FOR, Finding, check, joint_summary, migrate, missing_for, status

HEADER = ("# Named joint poses of the box (degrees; gripper 0-100), captured with scripts/tools/capture_poses.sh.\n"
          "# What each pose is: scripts/common/pose_catalog.py. How they look: assets/poses_workspace.svg\n"
          "# (scripts/tools/draw_poses.py). They only fit the arm calibration and box they were captured\n"
          "# with: capture them again after recalibrating or moving anything.\n")


def load(path: Path) -> dict:
    path = Path(path)
    return (yaml.safe_load(path.read_text()) or {}).get("poses", {}) if path.exists() else {}


def save(path: Path, poses: dict) -> None:
    Path(path).write_text(HEADER + yaml.safe_dump({"poses": poses}, sort_keys=False))


def steady_pose(samples: list[tuple[float, dict]], now: float, window_s: float = 0.4, min_samples: int = 5,
                max_spread_deg: float = 1.5) -> tuple[dict | None, str]:
    """The pose to store: the mean of the readings of the last window_s, if the arm held still.
    samples: [(time, joints)] newest last. Returns (pose, "") or (None, why not)."""
    recent = [j for t, j in samples if now - t <= window_s]
    if len(recent) < min_samples:
        return None, "No recent arm readings: is the arm connected?"
    for key in JOINT_KEYS:
        if key == GRIPPER:
            continue
        values = [j[key] for j in recent]
        if max(values) - min(values) > max_spread_deg:
            return None, f"The arm is still moving ({key.split('.')[0]} varies by {max(values) - min(values):.1f}°): hold it still and press again"
    return {k: round(sum(j[k] for j in recent) / len(recent), 2) for k in JOINT_KEYS}, ""


class CaptureSession:
    """config/poses.yaml as the tool edits it. Every capture is written at once, so stopping
    the tool loses nothing. A file with old pose names is read as the new names and rewritten
    under them on the first save (the old file is kept as <name>.bak)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        raw = load(self.path)
        self.poses, self.notes = migrate(raw)
        self.needs_backup = bool(self.notes)

    def save(self) -> None:
        if self.needs_backup and self.path.exists():
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            if not backup.exists():
                shutil.copy2(self.path, backup)
            self.needs_backup = False
        save(self.path, {n: self.poses[n] for n in NAMES if n in self.poses} |
             {n: p for n, p in self.poses.items() if n not in NAMES})

    def capture(self, name: str, pose: dict) -> list[Finding]:
        self.poses[name] = {k: round(float(pose[k]), 2) for k in JOINT_KEYS}
        self.save()
        return check(name, self.poses)

    def clear(self, name: str) -> None:
        self.poses.pop(name, None)
        self.save()

    def findings(self, name: str) -> list[Finding]:
        return check(name, self.poses) if name in self.poses else []

    def next_missing(self, after: str | None = None) -> str | None:
        """The next required pose without a capture, after `after` and wrapping around; None when
        all are there (optional poses are never asked for)."""
        start = NAMES.index(after) + 1 if after in NAMES else 0
        for name in NAMES[start:] + NAMES[:start]:
            if name not in self.poses and not BY_NAME[name].optional:
                return name
        return None


def report(poses: dict) -> str:
    """The state of the poses as text: what is captured, what looks wrong, what is still needed."""
    lines = []
    for number, (name, found) in enumerate(status(poses).items(), 1):
        mark = "✗" if found is None else ("⚠" if found else "✓")
        gap = "not captured" + (" (optional)" if BY_NAME[name].optional else "")
        lines.append(f"  {mark} {number} {name:12s} " + (gap if found is None else joint_summary(poses[name])))
        for f in found or []:
            lines.append(f"        {'!' if f.level == 'error' else '?'} {f.text}")
    for feature, what in NEEDED_FOR.items():
        missing = missing_for(feature, poses)
        lines.append(f"  {'needs ' + ', '.join(missing) if missing else 'ready'}: {what}")
    return "\n".join(lines)

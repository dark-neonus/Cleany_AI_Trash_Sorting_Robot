"""Capture the named joint poses of the box pipeline by moving the follower arm by hand.

Usage (through scripts/tools/capture_poses.sh, which fills in the port and calibration):
    python capture_poses.py --robot-port <port> --calibration-dir <dir> [names...]
    names: default home hover centre metal_bin plastic_bin grasp

The arm's torque is switched off: hold it, move it to the pose, press Enter. The joint values
are written to config/poses.yaml right away (other poses in the file are kept), so an
interrupted session loses nothing. Type s + Enter to skip a pose.

Poses:
  home         rest pose: every cycle starts and ends here; the doors only open in it
  hover        over the tray, gripper out of the wrist camera's view; the grasp starts here
  centre       between the tray and the bins, high enough to clear the walls with an item
  metal_bin    over the metal (left) bin
  plastic_bin  over the plastic (right) bin
  grasp        only for --grasp scripted: low over the tray centre, where a test item lies

The gripper value of a pose is ignored except for home (the pipeline sets the gripper itself).
--wrist <device> also saves a wrist-camera photo at hover to outputs/poses/hover_wrist.jpg:
check that all four tray corners are visible (docs/pipeline-proposal.md, Hover pose).
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from box_logic import JOINT_KEYS  # noqa: E402

DEFAULT_NAMES = ["home", "hover", "centre", "metal_bin", "plastic_bin", "grasp"]


def save(path: Path, poses: dict):
    header = ("# Named joint poses of the box pipeline (degrees; gripper 0-100), captured by hand with\n"
              "# scripts/tools/capture_poses.sh. They only fit the arm calibration and box they were\n"
              "# captured with: capture them again after recalibrating or moving anything.\n")
    path.write_text(header + yaml.safe_dump({"poses": poses}, sort_keys=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", default=DEFAULT_NAMES)
    parser.add_argument("--robot-port", required=True)
    parser.add_argument("--calibration-dir", required=True)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "config" / "poses.yaml")
    parser.add_argument("--wrist", help="wrist camera device: save a photo at hover")
    args = parser.parse_args()

    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    robot = SO101Follower(SO101FollowerConfig(port=args.robot_port, id="follower_arm",
                                              calibration_dir=Path(args.calibration_dir)))
    robot.connect()
    poses = (yaml.safe_load(args.output.read_text()) or {}).get("poses", {}) if args.output.exists() else {}
    try:
        input("The torque goes off next and the arm will sag: hold it, then press Enter. ")
        robot.bus.disable_torque()
        print("Torque is off: move the arm by hand.\n")
        for name in args.names:
            answer = input(f"Move the arm to '{name}', then press Enter (s + Enter: skip) ").strip().lower()
            if answer == "s":
                continue
            obs = robot.get_observation()
            poses[name] = {k: round(float(obs[k]), 2) for k in JOINT_KEYS}
            save(args.output, poses)
            print(f"  {name}: " + "  ".join(f"{k.split('.')[0]} {v:.1f}" for k, v in poses[name].items()))
            if name == "hover" and args.wrist:
                photo(args.wrist)
        print(f"\nSaved {args.output} ({', '.join(poses)}), {datetime.now():%H:%M}.")
        input("Put the arm in its rest pose and hold it, then press Enter: the torque stays off on exit.")
    finally:
        robot.disconnect()


def photo(device: str):
    import cv2

    out = PROJECT_ROOT / "outputs" / "poses" / "hover_wrist.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    camera = cv2.VideoCapture(device)
    for _ in range(10):  # let exposure settle
        ok, frame = camera.read()
    camera.release()
    if ok:
        cv2.imwrite(str(out), frame)
        print(f"  wrist photo: {out} (all four tray corners must be visible)")
    else:
        print("  wrist photo failed: camera gave no frame")


if __name__ == "__main__":
    main()

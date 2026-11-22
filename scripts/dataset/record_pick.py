"""Record the pick dataset: hover to item lifted, with the box pipeline's own perception and poses.

Usage (through scripts/dataset/record_pick.sh, which fills in the hardware config):
    python record_pick.py --yolo <weights> --robot-port <port> --leader-port <port>
                          --calibration-dir <dir> --cameras <json> [--door esp32|none]

The states are in scripts/run/pick_session.py, the panel in scripts/run/pick_panel.py, the
settings in config/pick_recording.yaml (and the shared config/box_pipeline.yaml), the poses in
config/poses.yaml. What is recorded and why: docs/pick-dataset.md.

Writes:
  data/cleany_pick/                LeRobot dataset (appended to when it exists)
  data/pick_yolo/                  labelled front frames for YOLO
  data/box_crops/<material>/       DINO gallery crops (scripts/tools/build_gallery.sh --crops)
  data/pick_records.jsonl          one line per kept episode or `other` item
  logs/pick/pick_<time>.jsonl      every event of the session
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT_ROOT / "scripts" / "common"), str(PROJECT_ROOT / "scripts" / "run")]
import arm_estop  # noqa: E402
import estop  # noqa: E402
from box_logic import REQUIRED_POSES, load_poses, load_yaml  # noqa: E402
from box_states import Clock, DoorSequencer, Hooks  # noqa: E402
from motor_state import JOINTS, Normaliser, dataset_features, read_extras, training_state  # noqa: E402
from pick_session import Commands, PickSession, PickStore, Status  # noqa: E402

# Importing lerobot_wide_fov patches lerobot as for every other run on the arm: full-FOV camera
# capture, follower speed limits (SERVO_* env vars), staggered torque-on.
import lerobot_wide_fov  # noqa: E402,F401

arm_estop.install()  # the red button in the panel releases the follower's torque


class EventLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.file = path, path.open("a")

    def __call__(self, event: str, **data):
        line = {"time": datetime.now().isoformat(timespec="milliseconds"), "event": event, **data}
        self.file.write(json.dumps(line, default=str) + "\n")
        self.file.flush()
        if event not in ("phase",):
            print(f"[pick] {event} {json.dumps(data, default=str)[:200]}", flush=True)


class Follower:
    """The follower as the session sees it: degrees and camera frames, register telemetry."""

    def __init__(self, robot):
        self.robot = robot

    def observe(self) -> dict:
        return self.robot.get_observation()

    def send(self, action: dict):
        self.robot.send_action(action)  # through arm_estop's guard

    def extras(self) -> dict:
        return read_extras(self.robot.bus)


class Leader:
    """The leader arm, driven by script or by hand. Torque on holds it where it is first."""

    def __init__(self, teleop):
        self.teleop, self.bus = teleop, teleop.bus
        self.torque = False

    def read(self) -> dict:
        return self.teleop.get_action()

    def command(self, degrees: dict):
        self.bus.sync_write("Goal_Position", {j: degrees[f"{j}.pos"] for j in JOINTS})

    def set_torque(self, on: bool):
        if on and not self.torque:
            self.bus.sync_write("Goal_Position", self.bus.sync_read("Present_Position"))
            self.bus.enable_torque()
        elif not on and self.torque:
            self.bus.disable_torque()
        self.torque = on


class DatasetRecorder:
    """Episodes of the LeRobot dataset; an episode stays in the buffer until save() or cancel()."""

    def __init__(self, dataset, follower_norm: Normaliser, leader_norm: Normaliser, protection_current: float,
                 cameras: list[str]):
        self.dataset, self.fn, self.ln, self.protection = dataset, follower_norm, leader_norm, protection_current
        self.cameras = cameras
        self.task, self.item = None, None

    def begin(self, task: str, item: dict):
        if self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()
        dim = self.dataset.features["item.embedding"]["shape"][0]
        embedding = item["embedding"] if item["embedding"] is not None else np.zeros(dim, np.float32)
        self.task = task
        self.item = {"item.embedding": np.asarray(embedding, np.float32),
                     "item.box": np.asarray(item["box"], np.float32)}

    def add(self, obs: dict, action: dict, extras: dict):
        positions = self.fn.positions(obs)
        frame = {"observation.state": training_state(positions, extras, self.protection),
                 "action": self.ln.positions(action),
                 **{f"observation.images.{c}": obs[c] for c in self.cameras},
                 **{f"motors.{k}": v for k, v in extras.items()},
                 **self.item, "task": self.task}
        self.dataset.add_frame(frame)

    def cancel(self):
        if self.dataset.has_pending_frames():
            self.dataset.clear_episode_buffer()

    def save(self) -> int:
        self.dataset.save_episode()
        return self.dataset.meta.total_episodes - 1


def open_dataset(cfg: dict, robot, embedding_dim: int):
    from lerobot.configs.video import RGBEncoderConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = PROJECT_ROOT / cfg["root"]
    cameras = {name: (cam.height, cam.width) for name, cam in robot.config.cameras.items()}
    features = dataset_features(cameras, embedding_dim)
    encoder = RGBEncoderConfig(vcodec=os.environ.get("VIDEO_CODEC", "h264_nvenc"),
                               crf=int(os.environ.get("VIDEO_QUALITY", "23")),
                               extra_options=json.loads(os.environ.get("VIDEO_EXTRA_OPTIONS", '{"bf": 0}')))
    common = dict(rgb_encoder=encoder, streaming_encoding=True, encoder_threads=2)
    if (root / "meta" / "info.json").exists():
        dataset = LeRobotDataset.resume(cfg["repo_id"], root=root, **common)
        mismatch = {k for k in features if k not in dataset.features or
                    tuple(dataset.features[k]["shape"]) != tuple(features[k]["shape"])}
        if mismatch:
            sys.exit(f"Error: {root} has different features ({sorted(mismatch)}): move it away or change dataset.root")
        print(f"Appending to {root} ({dataset.meta.total_episodes} episodes)")
    else:
        if root.exists() and any(root.iterdir()):
            moved = root.with_name(f"{root.name}.incomplete_{datetime.now():%Y%m%d_%H%M%S}")
            root.rename(moved)
            print(f"Moved an incomplete dataset (no meta/info.json) to {moved}")
        dataset = LeRobotDataset.create(cfg["repo_id"], cfg["fps"], features, root=root, robot_type="so101_follower",
                                        use_videos=True, **common)
        print(f"New dataset at {root}")
    return dataset, list(cameras)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "pick_recording.yaml")
    parser.add_argument("--yolo", required=True)
    parser.add_argument("--robot-port", required=True)
    parser.add_argument("--leader-port", required=True)
    parser.add_argument("--calibration-dir", required=True)
    parser.add_argument("--cameras", required=True, help="robot cameras as JSON, like --robot.cameras of lerobot")
    parser.add_argument("--door", choices=("esp32", "none"), default="esp32")
    parser.add_argument("--max-step", type=float, default=10)
    parser.add_argument("--device", default=None)
    args = parser.parse_args()

    import cv2
    import torch

    recording = load_yaml(args.config)
    config = load_yaml(PROJECT_ROOT / recording["box_pipeline"])
    config["motion"]["lag_deg"] = 0.8 * args.max_step  # paced motion: stay inside the follower's step limit
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        poses = load_poses(PROJECT_ROOT / config["poses"], REQUIRED_POSES)
    except (FileNotFoundError, KeyError) as error:
        sys.exit(f"Error: {error}")
    log = EventLog(PROJECT_ROOT / "logs" / "pick" / f"pick_{datetime.now():%Y%m%d_%H%M%S}.jsonl")

    from dino_classifier import Embedder, Gallery, decide
    from yolo_boxes import YoloBoxes

    detector = YoloBoxes(args.yolo, config["detector"]["conf"], device)
    c = config["classifier"]
    embedder = Embedder(c["backbone"], c.get("fallback_backbone"), device)
    gallery_path = PROJECT_ROOT / c["gallery"]
    gallery = Gallery.load(gallery_path) if gallery_path.exists() else None
    if gallery is not None and gallery.backbone != embedder.backbone:
        print(f"Gallery {gallery_path} was built with {gallery.backbone}, not {embedder.backbone}: DINO check off")
        gallery = None
    if gallery is None:
        print("No DINO gallery yet: items are not checked against your button (crops are saved to build one)")

    def check(vector):
        return None if gallery is None else decide(vector, gallery, c.get("k", 5), c["max_distance"], c["min_margin"])

    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig
    from lerobot.teleoperators.so_leader import SO101Leader, SO101LeaderConfig

    cameras = {name: OpenCVCameraConfig(**{k: v for k, v in cam.items() if k != "type"})
               for name, cam in json.loads(args.cameras).items()}
    calibration_dir = Path(args.calibration_dir)
    robot = SO101Follower(SO101FollowerConfig(port=args.robot_port, id="follower_arm", calibration_dir=calibration_dir,
                                              cameras=cameras, max_relative_target=args.max_step))
    teleop = SO101Leader(SO101LeaderConfig(port=args.leader_port, id="leader_arm", calibration_dir=calibration_dir))
    teleop.connect()
    robot.connect()
    dataset, camera_names = open_dataset(recording["dataset"], robot, embedder.model.config.hidden_size)
    protection = float(robot.bus.read("Protection_Current", "gripper", normalize=False))
    recorder = DatasetRecorder(dataset, Normaliser.from_calibration(robot.bus.calibration),
                               Normaliser.from_calibration(teleop.bus.calibration), protection, camera_names)

    door = None
    if args.door == "esp32":
        from drop_panel import get_controller

        d = config["door"]
        door = DoorSequencer(get_controller(), Clock(), d["open_timeout_s"], d["cycle_timeout_s"])

    store = PickStore(PROJECT_ROOT, recording["outputs"],
                      lambda path, rgb: cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)))
    status, commands, stop = Status(), Commands(), threading.Event()
    session = PickSession(Follower(robot), Leader(teleop), detector, embedder, check, door, recorder, store, poses,
                          config, recording, Hooks(log), commands, status, should_stop=stop.is_set,
                          paused=estop.is_active)
    errors = []

    def run_session():
        try:
            session.run()
        except Exception as error:  # noqa: BLE001
            errors.append(error)
            log("error", error=f"{error.__class__.__name__}: {error}")

    worker = threading.Thread(target=run_session, name="pick_session")
    worker.start()
    from pick_panel import run_panel

    try:
        run_panel(status, commands, stop.set, f"Cleany pick recorder · {recording['dataset']['repo_id']}",
                  config["trigger"]["tray_region"], recording["episode"]["warn_after_s"], worker.is_alive)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join()
        dataset.finalize()
        robot.disconnect()
        teleop.disconnect()
        log("end", counts=status.counts, session=status.session)
    print(f"\nKept this session: {status.session}. Totals: {status.counts}")
    print("Upload with: scripts/dataset/sync.sh push pick")
    if errors:
        raise errors[0]


if __name__ == "__main__":
    main()

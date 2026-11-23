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
  data/pick_records.jsonl          one line per kept episode or `other` item (with the session)
  logs/pick/pick_<time>.jsonl      every event of the session
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT_ROOT / "scripts" / "common"), str(PROJECT_ROOT / "scripts" / "run")]
import arm_estop  # noqa: E402
import clamp_log  # noqa: E402
import estop  # noqa: E402
from box_logic import REQUIRED_POSES, load_poses, load_yaml  # noqa: E402
from box_states import Clock, DoorSequencer, Hooks  # noqa: E402
from camera_feed import CameraFeed  # noqa: E402
from comm_retry import STATS as COMM  # noqa: E402
from comm_retry import retry  # noqa: E402
from item_registry import Registry, RegistryError  # noqa: E402
from leader_arm import Leader  # noqa: E402
from motor_state import Normaliser, read_extras  # noqa: E402
from pick_dataset import DatasetError, DatasetRecorder, open_dataset  # noqa: E402
from pick_session import Commands, PickSession, PickStore, Status  # noqa: E402

# Importing lerobot_wide_fov patches lerobot as for every other run on the arm: full-FOV camera
# capture, follower speed limits (SERVO_* env vars), staggered torque-on.
import lerobot_wide_fov  # noqa: E402,F401

arm_estop.install()  # the red button in the panel releases the follower's torque
clamps = clamp_log.install()  # the follower limits what it is told when it lags behind the leader: counted, not printed


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
        return retry(self.robot.get_observation)

    def send(self, action: dict):
        retry(self.robot.send_action, action)  # through arm_estop's guard

    def extras(self) -> dict:
        return retry(read_extras, self.robot.bus)


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

    import torch

    recording = load_yaml(args.config)
    config = load_yaml(PROJECT_ROOT / recording["box_pipeline"])
    config["motion"]["lag_deg"] = 0.8 * args.max_step  # paced motion: stay inside the follower's step limit
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        poses = load_poses(PROJECT_ROOT / config["poses"], REQUIRED_POSES)
    except (FileNotFoundError, KeyError) as error:
        sys.exit(f"Error: {error}")
    items = recording.get("items") or {}
    try:
        registry = Registry.load(PROJECT_ROOT / items["registry"] if items.get("registry") else None,
                                 PROJECT_ROOT / items["labels"] if items.get("labels") else None)
    except RegistryError as error:
        sys.exit(f"Error: {error}")
    held = sum(it.split == "test" for it in registry.items.values())
    print(f"Items: {len(registry.items)} in the registry ({held} held out: refused), {len(registry.labels)} labels")
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
    try:
        run(args, recording, config, poses, log, robot, teleop, detector, embedder, check, registry)
    finally:  # whatever happened: release the arms and cameras (an exit with their threads running aborts)
        for name, device in (("follower", robot), ("leader", teleop)):
            try:
                if device.is_connected:
                    device.disconnect()
            except Exception as error:  # noqa: BLE001
                log("shutdown_error", device=name, error=f"{error.__class__.__name__}: {error}")


def run(args, recording, config, poses, log, robot, teleop, detector, embedder, check, registry):
    import cv2

    cameras = {name: (cam.height, cam.width) for name, cam in robot.config.cameras.items()}
    root = PROJECT_ROOT / recording["dataset"]["root"]

    def reopen():
        return open_dataset(recording["dataset"], root, cameras, embedder.model.config.hidden_size, say=log_say)

    def log_say(text):
        print(text, flush=True)
        log("dataset", text=text)

    try:
        dataset = reopen()
    except DatasetError as error:
        sys.exit(f"Error: {error}")
    camera_names = list(cameras)
    protection = float(robot.bus.read("Protection_Current", "gripper", normalize=False))
    recorder = DatasetRecorder(dataset, Normaliser.from_calibration(robot.bus.calibration),
                               Normaliser.from_calibration(teleop.bus.calibration), protection, camera_names,
                               reopen=lambda: open_dataset(recording["dataset"], root, cameras,
                                                           embedder.model.config.hidden_size, say=lambda _: None))

    door = None
    if args.door == "esp32":
        from drop_panel import get_controller

        d = config["door"]
        door = DoorSequencer(get_controller(), Clock(), d["open_timeout_s"], d["cycle_timeout_s"])

    store = PickStore(PROJECT_ROOT, recording["outputs"],
                      lambda path, rgb: cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)))
    status, commands, stop = Status(), Commands(), threading.Event()
    session = PickSession(Follower(robot), Leader(teleop, recording["start"].get("leader_gripper_torque", 40)), detector, embedder, check, door, recorder, store, poses,
                          config, recording, Hooks(log), commands, status, should_stop=stop.is_set,
                          paused=estop.is_active, registry=registry)
    errors = []

    def run_session():
        try:
            session.run()
        except Exception as error:  # noqa: BLE001
            errors.append(error)
            log("error", error=f"{error.__class__.__name__}: {error}")

    feeds = {name: CameraFeed(name, robot.cameras[name]) for name in camera_names if name in robot.cameras}
    worker = threading.Thread(target=run_session, name="pick_session")
    worker.start()
    from pick_panel import run_panel

    try:
        run_panel(status, commands, stop.set, f"Cleany pick recorder · {recording['dataset']['repo_id']}",
                  config["trigger"]["tray_region"], recording["episode"]["warn_after_s"], worker.is_alive,
                  registry, feeds, recording["dataset"]["fps"])
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        log("shutdown", step="waiting for the session")
        worker.join()
        log("shutdown", step="finalizing the dataset")
        recorder.close()
        log("end", counts=status.counts, session=status.session)
    print(f"\nKept this session: {status.session}. Totals: {status.counts}")
    if clamps.count:
        print(f"{clamps.count} follower commands were limited by --max-step {args.max_step:g}: the follower lagged "
              f"behind the leader (a grasp: the fingers blocked by the item; a fast move: the arm). Their cause is "
              f"normal in teleoperation; a high count in a quiet episode is not.")
    if COMM.count:
        print(f"{COMM.count} arm bus calls needed a retry (a reply went missing once: {COMM.last}).")
    print("Upload with: scripts/dataset/sync.sh push pick")
    print("Label the items: scripts/tools/contact_sheet.sh (then the agent fills config/items.yaml and item_labels.yaml)")
    if errors:
        raise errors[0]


if __name__ == "__main__":
    main()

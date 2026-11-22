"""Box pipeline: background trigger, YOLO boxes + DINO material, one grasp model, scripted moves.

Usage (normally through scripts/run/run_box_pipeline.sh, which fills in the hardware config):
    python box_pipeline.py --robot-port <port> --calibration-dir <dir> --cameras <json> [options]
    python box_pipeline.py --dry-run --source <camera|video|image> [options]

The states are in box_states.py, the settings in config/box_pipeline.yaml, the named poses in
config/poses.yaml (scripts/tools/capture_poses.sh). See docs/box-pipeline.md.

--grasp scripted (default) moves to the captured `grasp` pose and closes the gripper: a fake
grasp to test everything around it. --grasp policy runs the pick model (grasp.model in the
config, or --grasp-model).

--dry-run needs no arm: a simulated arm follows every command at once, frames come from
--source, and the door is simulated unless --door esp32. The simulated gripper closes on an
item at 15 (so the grasp check passes) unless --dry-run-grasp-fails.

Stop with Ctrl+C or exit + Enter: the arm goes home first. The red emergency stop button
releases the arm's torque; once pressed again, the arm goes home and the pipeline goes on.
Events are printed and written to logs/pipeline/box_<timestamp>.jsonl.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# sort_pipeline patches lerobot (camera FOV, servo limits, emergency stop) and opens the
# emergency stop window, as for every other run on the arm
from sort_pipeline import Display, EventLog, FrameSource, Policy, watch_for_exit  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
import estop  # noqa: E402
from box_logic import GRIPPER, JOINT_KEYS, REQUIRED_POSES, load_poses, load_yaml, yolo_vote  # noqa: E402
from box_states import BoxPipeline, Clock, DoorSequencer, Hooks, ScriptedGrasper, Stop  # noqa: E402
from yolo_boxes import YoloBoxes  # noqa: E402


def make_classify(config: dict, device: str):
    c = config["classifier"]
    if c["type"] == "yolo":
        def classify(items):
            for item in items:
                item.cls = yolo_vote(item, c["yolo_min_conf"])
        return classify, "yolo"

    from dino_classifier import Classifier

    classifier = Classifier(c, device, PROJECT_ROOT)

    def classify(items):
        for item in items:
            decision = classifier.classify(item.crops)
            item.cls, item.info = decision.cls, {"distances": decision.distances, "why": decision.reason}
    return classify, classifier.embedder.backbone


class RobotArm:
    def __init__(self, robot):
        self.robot = robot

    def observe(self) -> dict:
        return self.robot.get_observation()

    def send(self, action: dict):
        self.robot.send_action(action)


class SimulatedArm:
    """--dry-run: the joints follow every command at once; the gripper stops at item_deg when
    it closes from open (it 'holds an item') until it is opened again."""

    def __init__(self, source: FrameSource, start: dict, item_deg: float | None):
        self.source, self.joints, self.item_deg = source, dict(start), item_deg
        self.holding = False

    def observe(self) -> dict:
        frame = self.source.read()
        if frame is None:
            raise Stop  # the video ended
        return {**self.joints, "front": frame}

    def send(self, action: dict):
        gripper = action[GRIPPER]
        if self.item_deg is not None:
            if self.joints[GRIPPER] > self.item_deg + 5 >= gripper:
                self.holding = True
            elif gripper > self.item_deg + 10:
                self.holding = False
        self.joints = {k: action[k] for k in JOINT_KEYS}
        if self.holding:
            self.joints[GRIPPER] = max(gripper, self.item_deg)


class SimulatedDoor:
    def __init__(self, log):
        self.log = log

    def wait_ready(self):
        pass

    def drop(self):
        self.log("door_simulated")
        time.sleep(0.5)


class PolicyGrasper:
    """The pick model, stepped like sort_pipeline.Policy, but returning the command so the state
    machine can send it and compare it with the measured gripper."""

    def __init__(self, policy: Policy):
        self.policy = policy

    def reset(self, start: dict):
        self.policy.reset()

    def action(self, obs: dict) -> dict:
        from lerobot.utils.feature_utils import build_dataset_frame

        p = self.policy
        frame = build_dataset_frame(p.features, p.robot_observation_processor(obs), prefix="observation")
        action = p.engine.get_action(frame)
        action_dict = {k: action[i].item() for i, k in enumerate(p.action_keys)}
        return p.robot_action_processor((action_dict, obs))


def dry_run_poses() -> dict:
    """Stand-in poses for --dry-run only, when config/poses.yaml is missing (nothing moves)."""
    base = dict.fromkeys(JOINT_KEYS, 0.0)
    return {"home": {**base, "shoulder_lift.pos": -100.0, "elbow_flex.pos": 95.0},
            "hover": {**base, "shoulder_lift.pos": -40.0, "elbow_flex.pos": 40.0},
            "tray_low": {**base, "shoulder_lift.pos": -10.0, "elbow_flex.pos": 20.0},
            "transit": {**base, "shoulder_lift.pos": -60.0, "elbow_flex.pos": 50.0},
            "metal_bin": {**base, "shoulder_pan.pos": -40.0, "shoulder_lift.pos": -50.0},
            "plastic_bin": {**base, "shoulder_pan.pos": 40.0, "shoulder_lift.pos": -50.0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config" / "box_pipeline.yaml")
    parser.add_argument("--yolo", required=True, help="YOLO weights (.pt): item boxes")
    parser.add_argument("--grasp", choices=("scripted", "policy"), default="scripted")
    parser.add_argument("--grasp-model", help="pick model (overrides grasp.model in the config)")
    parser.add_argument("--door", choices=("esp32", "none", "simulated"), default=None,
                        help="esp32 (default on the arm), simulated (default in --dry-run), or none: "
                             "items that cannot be sorted wait until you take them out")
    parser.add_argument("--display", action="store_true", help="show the front image and state in Rerun")
    parser.add_argument("--device", default=None)
    parser.add_argument("--robot-port")
    parser.add_argument("--calibration-dir")
    parser.add_argument("--cameras", help="robot cameras as JSON, like --robot.cameras of lerobot")
    parser.add_argument("--max-step", type=float, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", help="dry run: camera device, video or image")
    parser.add_argument("--dry-run-grasp-fails", action="store_true", help="dry run: the gripper closes on nothing")
    parser.add_argument("--record-dir", type=Path, help="record the cameras here and make showcase.mp4 at the end")
    args = parser.parse_args()

    import torch

    config = load_yaml(args.config)
    config["motion"]["lag_deg"] = 0.8 * args.max_step  # paced motion: stay inside the follower's step limit
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    log = EventLog(PROJECT_ROOT / "logs" / "pipeline" / f"box_{datetime.now():%Y%m%d_%H%M%S}.jsonl")

    # Poses first: on the arm, a missing pose stops here, before anything is loaded or moves
    required = REQUIRED_POSES + (("tray_low",) if args.grasp == "scripted" else ())
    poses_path = PROJECT_ROOT / config["poses"]
    try:
        poses = load_poses(poses_path, required)
    except (FileNotFoundError, KeyError) as error:
        if not args.dry_run:
            sys.exit(f"Error: {error}")
        print(f"Dry run: {error}. Using stand-in poses (nothing moves).")
        poses = dry_run_poses()

    grasp_model = args.grasp_model or config["grasp"].get("model")
    if args.grasp == "policy" and not grasp_model:
        sys.exit("Error: --grasp policy needs a pick model: --grasp-model <repo|folder> or grasp.model in the config")

    detector = YoloBoxes(args.yolo, config["detector"]["conf"], device)
    classify, classifier_name = make_classify(config, device)
    policy = Policy(grasp_model, config["grasp"]["task"], device) if args.grasp == "policy" else None
    log("start", dry_run=args.dry_run, device=device, yolo=args.yolo, classifier=classifier_name,
        grasp=args.grasp, grasp_model=grasp_model, poses=str(poses_path))

    robot, source = None, None
    door_mode = args.door or ("simulated" if args.dry_run else "esp32")
    if args.dry_run:
        if not args.source:
            sys.exit("--dry-run needs --source (camera device, video or image)")
        source = FrameSource(args.source)
        arm = SimulatedArm(source, poses["home"], None if args.dry_run_grasp_fails else 15.0)
    else:
        from lerobot.cameras.opencv import OpenCVCameraConfig
        from lerobot.processor import make_default_processors
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        cameras = {name: OpenCVCameraConfig(**{k: v for k, v in c.items() if k != "type"})
                   for name, c in json.loads(args.cameras).items()}
        robot = SO101Follower(SO101FollowerConfig(port=args.robot_port, id="follower_arm",
                                                  calibration_dir=Path(args.calibration_dir), cameras=cameras,
                                                  max_relative_target=args.max_step))
        robot.connect()
        if policy is not None:
            policy.attach(robot, make_default_processors())
        arm = RobotArm(robot)
        log("robot_connected")

    if door_mode == "esp32":
        from drop_panel import get_controller

        d = config["door"]
        door = DoorSequencer(get_controller(), Clock(), d["open_timeout_s"], d["cycle_timeout_s"])
    elif door_mode == "simulated":
        door = SimulatedDoor(log)
    else:
        door = None

    if args.grasp == "policy":
        grasper = PolicyGrasper(policy)
    else:
        grasper = ScriptedGrasper(poses, config["motion"])

    display = Display(args.display, [config["trigger"]["tray_region"]])
    recorder = None
    if args.record_dir is not None:
        from pipeline_recording import Recorder, render

        recorder = Recorder(args.record_dir, {"pipeline": "box", "dry_run": args.dry_run, "yolo": args.yolo,
                                              "classifier": classifier_name, "grasp": args.grasp,
                                              "grasp_model": grasp_model, "lock_seconds": None,
                                              "log_file": str(log.path)})

    def on_frame(obs, mode, detections=None, state=""):
        label = state.split()[0] if state else "WAIT"
        shown = [{k: d[k] for k in ("class", "conf", "box")} for d in detections or []]
        display.show(obs["front"], shown, state or mode)
        if recorder is not None:
            recorder.add(obs["front"], obs.get("wrist"), label if mode == "yolo" else f"{mode} {label}", shown)

    stop = threading.Event()
    threading.Thread(target=watch_for_exit, args=(stop,), daemon=True).start()
    print("Type exit + Enter (or Ctrl+C) to stop.", flush=True)

    pipeline = BoxPipeline(arm, detector, classify, grasper, door, poses, config, Hooks(log, on_frame),
                           should_stop=stop.is_set, paused=estop.is_active if robot is not None else lambda: False)
    try:
        pipeline.run()
    except (KeyboardInterrupt, Stop):
        log("stopped_by_user")
    except Exception as error:
        log("error", error=f"{error.__class__.__name__}: {error}")
        raise
    finally:
        if robot is not None and robot.is_connected:
            try:
                pipeline.shutdown()
            finally:
                robot.disconnect()
        if source is not None:
            source.close()
        if recorder is not None:
            recorder.close()
            log("recording_saved", dir=str(args.record_dir), frames=recorder.counts["front"])
        log("end", log_file=str(log.path))
    if recorder is not None:
        render(args.record_dir)


if __name__ == "__main__":
    main()

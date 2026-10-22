"""Sorting pipeline: YOLO picks the material, the matching ACT model moves the item.

Usage (normally through scripts/run/run_pipeline.sh, which fills in the hardware config):
    python sort_pipeline.py --plastic-model <repo|dir> --metal-model <repo|dir> --yolo <best.pt>
                            --robot-port <port> --calibration-dir <dir> --cameras <json> [options]
    python sort_pipeline.py --dry-run --source <camera path|video|image> --yolo <best.pt> ...

States (see "Model Pipeline" in the README):
  DETECT   YOLO runs on every front-camera frame. A class is locked when it has been the most
           confident detection (>= --conf) in every frame for --lock-seconds without a break.
           Detections whose centre lies in an --ignore-region (the bins) are skipped. Nothing
           locked: keep waiting.
  ACT      The model of the locked class drives the arm. YOLO is not consulted. The run ends
           when the arm has left its start pose (any joint > --leave-deg away), is back within
           --home-tolerance-deg and has not moved more than --still-deg for --home-still-s
           seconds (the ACT keeps running meanwhile, so it can still try again), or after
           --episode-time seconds.
  HOME     The arm is eased back to the exact start pose.
  Then DETECT again. If the same class is locked again at the same place (box overlap > 0.3),
  the previous attempt failed; after --max-attempts attempts that class is ignored until it
  has not been seen for 3 s (e.g. someone removed the item), so a stuck item does not loop.

The start pose is the arm's pose when the pipeline starts: put it in the rest pose the
datasets start and end in. There is no ESP32 drop mechanism and no "other" class yet.

--dry-run runs without the arm: frames come from --source, YOLO and the state machine run as
usual, and the ACT step only prints which model would run and waits --dry-run-act-s.
Events are printed and written to logs/pipeline/<timestamp>.jsonl.

--record-dir DIR saves the front and wrist cameras during the run and, after it ends, makes
DIR/showcase.mp4 with the YOLO boxes and the running model (see pipeline_recording.py).
Stop with Ctrl+C or by typing exit + Enter: the arm goes home, then the video is made.
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Importing lerobot_wide_fov patches lerobot: full-FOV camera capture, follower speed limits
# (SERVO_* env vars) and staggered torque-on, exactly as for teleop, recording and run_policy.sh.
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
import lerobot_wide_fov  # noqa: E402,F401

CLASSES = ("metal", "plastic")
# Interiors of the left (metal) and right (plastic) bins in the 640x480 front image of the
# current setup: items already sorted into them must not be picked again.
DEFAULT_IGNORE_REGIONS = ["0,40,135,320", "440,55,640,335"]


class EventLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a")
        self.path = path

    def __call__(self, event: str, **data):
        record = {"time": datetime.now().isoformat(timespec="milliseconds"), "event": event, **data}
        self.file.write(json.dumps(record) + "\n")
        self.file.flush()
        details = " ".join(f"{k}={v}" for k, v in data.items())
        print(f"[{record['time'][11:19]}] {event} {details}", flush=True)


class Detector:
    def __init__(self, weights: str, conf: float, device: str, ignore_regions: list[tuple[int, ...]]):
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.conf = conf
        self.device = device
        self.ignore_regions = ignore_regions

    def __call__(self, frame_rgb: np.ndarray) -> list[dict]:
        """Detections outside the ignore regions, most confident first."""
        h, w = frame_rgb.shape[:2]
        sx, sy = w / 640, h / 480  # ignore regions are given for a 640x480 image
        result = self.model.predict(cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR), conf=self.conf,
                                    device=self.device, verbose=False)[0]
        detections = []
        for cls, conf, box in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xyxy.tolist()):
            name = self.model.names[int(cls)]
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            ignored = any(x0 * sx <= cx <= x1 * sx and y0 * sy <= cy <= y1 * sy for x0, y0, x1, y1 in self.ignore_regions)
            if name in CLASSES and not ignored:
                detections.append({"class": name, "conf": round(conf, 2), "box": [round(v) for v in box]})
        return sorted(detections, key=lambda d: -d["conf"])


class Display:
    """Front image with boxes and the pipeline state in a Rerun viewer (--display)."""

    def __init__(self, enabled: bool, ignore_regions):
        self.enabled = enabled
        if enabled:
            import rerun as rr

            self.rr = rr
            rr.init("cleany_pipeline", spawn=True)
            rr.log("front/ignored", rr.Boxes2D(array=[list(r) for r in ignore_regions],
                                              array_format=rr.Box2DFormat.XYXY, colors=[(128, 128, 128)],
                                              labels=["bin"] * len(ignore_regions)), static=True)

    def show(self, frame_rgb, detections, state: str):
        if not self.enabled:
            return
        rr = self.rr
        rr.log("front/image", rr.Image(frame_rgb).compress(jpeg_quality=80))
        colors = {"metal": (60, 120, 255), "plastic": (60, 220, 60)}
        rr.log("front/detections", rr.Boxes2D(
            array=[d["box"] for d in detections], array_format=rr.Box2DFormat.XYXY,
            labels=[f"{d['class']} {d['conf']:.2f}" for d in detections],
            colors=[colors[d["class"]] for d in detections]))
        rr.log("state", rr.TextLog(state))


class Policy:
    """One ACT model with its pre/post-processors, stepped like lerobot-rollout --inference.type=sync."""

    def __init__(self, path: str, task: str, device: str):
        from lerobot.configs import PreTrainedConfig
        from lerobot.policies import get_policy_class, make_pre_post_processors

        config = PreTrainedConfig.from_pretrained(path)
        config.pretrained_path = path
        config.device = device
        self.config = config
        self.policy = get_policy_class(config.type).from_pretrained(path, config=config).to(device).eval()
        self.preprocessor, self.postprocessor = make_pre_post_processors(
            policy_cfg=config, pretrained_path=path,
            preprocessor_overrides={"device_processor": {"device": device}},
        )
        self.path, self.task, self.device = path, task, device

    def attach(self, robot, processors):
        """Map the robot's observations and actions to the model (needs the connected robot)."""
        from lerobot.datasets import aggregate_pipeline_dataset_features, create_initial_features
        from lerobot.rollout.context import _resolve_action_key_order
        from lerobot.rollout.inference.sync import SyncInferenceEngine
        from lerobot.utils.feature_utils import combine_feature_dicts

        teleop_action_processor, self.robot_action_processor, self.robot_observation_processor = processors
        obs_hw = {k: v for k, v in robot.observation_features.items() if isinstance(v, tuple) or k.endswith(".pos")}
        action_hw = {k: v for k, v in robot.action_features.items() if k.endswith(".pos")}
        self.features = combine_feature_dicts(
            aggregate_pipeline_dataset_features(pipeline=teleop_action_processor,
                                                initial_features=create_initial_features(action=action_hw)),
            aggregate_pipeline_dataset_features(pipeline=self.robot_observation_processor,
                                                initial_features=create_initial_features(observation=obs_hw)),
        )
        self.action_keys = _resolve_action_key_order(getattr(self.config, "action_feature_names", None),
                                                     list(action_hw))
        self.engine = SyncInferenceEngine(self.policy, self.preprocessor, self.postprocessor, self.features,
                                          self.action_keys, self.task, self.device, robot.name)

    def reset(self):
        self.engine.reset()

    def step(self, robot, obs: dict):
        from lerobot.utils.feature_utils import build_dataset_frame

        frame = build_dataset_frame(self.features, self.robot_observation_processor(obs), prefix="observation")
        action = self.engine.get_action(frame)
        action_dict = {k: action[i].item() for i, k in enumerate(self.action_keys)}
        robot.send_action(self.robot_action_processor((action_dict, obs)))


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def joint_pose(obs: dict) -> dict:
    return {k: v for k, v in obs.items() if k.endswith(".pos")}


def max_deviation(pose: dict, home: dict) -> float:
    """Largest joint distance from home in degrees, gripper excluded (it opens and closes anyway)."""
    return max(abs(pose[k] - home[k]) for k in home if not k.startswith("gripper"))


def ease_to(robot, target: dict, duration_s: float = 3.0, fps: int = 50, on_step=None):
    from lerobot.utils.robot_utils import precise_sleep

    start = joint_pose(robot.get_observation())
    steps = max(int(duration_s * fps), 1)
    for i in range(1, steps + 1):
        t = i / steps
        robot.send_action({k: start[k] * (1 - t) + target[k] * t for k in target})
        if on_step is not None:
            on_step()
        precise_sleep(1 / fps)


def watch_for_exit(stop: threading.Event):
    """Typing exit (or stop / q) + Enter in the terminal ends the run like Ctrl+C."""
    for line in sys.stdin:
        if line.strip().lower() in ("exit", "stop", "q", "quit"):
            print("Stopping: the arm goes home, then the run ends.", flush=True)
            stop.set()
            return


class FrameSource:
    """Front-camera frames (RGB) for --dry-run: a camera device, a video file or an image."""

    def __init__(self, source: str):
        self.image = None
        self.camera = None
        self.video = None
        if Path(source).suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
            self.image = cv2.cvtColor(cv2.imread(source), cv2.COLOR_BGR2RGB)
        elif Path(source).suffix.lower() in (".mp4", ".avi", ".mkv", ".mov"):
            self.video = cv2.VideoCapture(source)
        else:
            from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig

            self.camera = OpenCVCamera(OpenCVCameraConfig(index_or_path=source, fps=30, width=640, height=480,
                                                          fourcc="MJPG", warmup_s=3))
            self.camera.connect()

    def read(self) -> np.ndarray | None:
        if self.image is not None:
            time.sleep(1 / 30)
            return self.image
        if self.video is not None:
            ok, frame = self.video.read()
            if not ok:
                return None
            time.sleep(1 / 30)
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return self.camera.read()

    def close(self):
        if self.camera is not None:
            self.camera.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plastic-model", required=True)
    parser.add_argument("--metal-model", required=True)
    parser.add_argument("--plastic-task", default="Put the plastic item into the right hole")
    parser.add_argument("--metal-task", default="Put the metal item into the left hole")
    parser.add_argument("--yolo", required=True)
    parser.add_argument("--conf", type=float, default=0.5, help="min YOLO confidence to count a detection")
    parser.add_argument("--lock-seconds", type=float, default=5,
                        help="seconds the same class must win every frame before its ACT runs")
    parser.add_argument("--ignore-region", action="append", default=None, metavar="X0,Y0,X1,Y1",
                        help="skip detections centred in this box of the 640x480 front image (repeatable; "
                             "default: the two bins). 'none' disables it")
    parser.add_argument("--episode-time", type=float, default=40, help="max seconds per ACT run")
    parser.add_argument("--leave-deg", type=float, default=20)
    parser.add_argument("--home-tolerance-deg", type=float, default=12)
    parser.add_argument("--home-still-s", type=float, default=5,
                        help="seconds the arm must stay still at home before YOLO looks again")
    parser.add_argument("--still-deg", type=float, default=3, help="joint movement that still counts as still")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--device", default=None, help="cuda (default when available) or cpu")
    parser.add_argument("--display", action="store_true", help="show the front image and detections in Rerun")
    parser.add_argument("--robot-port")
    parser.add_argument("--calibration-dir")
    parser.add_argument("--cameras", help="robot cameras as JSON, like --robot.cameras of lerobot")
    parser.add_argument("--max-step", type=float, default=10, help="max joint change per control step (deg)")
    parser.add_argument("--dry-run", action="store_true", help="no arm: frames from --source, ACT runs are simulated")
    parser.add_argument("--source", help="dry run: camera device, video or image")
    parser.add_argument("--dry-run-act-s", type=float, default=3)
    parser.add_argument("--record-dir", type=Path, help="record the cameras here and make showcase.mp4 at the end")
    args = parser.parse_args()

    import torch

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    regions = args.ignore_region if args.ignore_region is not None else DEFAULT_IGNORE_REGIONS
    ignore_regions = [] if regions == ["none"] else [tuple(int(v) for v in r.split(",")) for r in regions]
    log = EventLog(PROJECT_ROOT / "logs" / "pipeline" / f"{datetime.now():%Y%m%d_%H%M%S}.jsonl")
    log("start", dry_run=args.dry_run, device=device, yolo=args.yolo, plastic=args.plastic_model,
        metal=args.metal_model, ignore_regions=ignore_regions)

    detector = Detector(args.yolo, args.conf, device, ignore_regions)
    display = Display(args.display, ignore_regions)

    robot = None
    source = None
    processors = None
    if args.dry_run:
        if not args.source:
            sys.exit("--dry-run needs --source (camera device, video or image)")
        source = FrameSource(args.source)
    else:
        from lerobot.cameras.opencv import OpenCVCameraConfig
        from lerobot.processor import make_default_processors
        from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

        cameras = {name: OpenCVCameraConfig(**cfg_json) for name, cfg_json in
                   ((n, {k: v for k, v in c.items() if k != "type"}) for n, c in json.loads(args.cameras).items())}
        robot = SO101Follower(SO101FollowerConfig(port=args.robot_port, id="follower_arm",
                                                  calibration_dir=Path(args.calibration_dir), cameras=cameras,
                                                  max_relative_target=args.max_step))
        processors = make_default_processors()

    # Models before hardware, so a bad model path fails without touching the arm
    policies = {"plastic": Policy(args.plastic_model, args.plastic_task, device),
                "metal": Policy(args.metal_model, args.metal_task, device)}
    log("models_loaded")
    if robot is not None:
        robot.connect()
        for policy in policies.values():
            policy.attach(robot, processors)
        home = joint_pose(robot.get_observation())
        log("robot_connected", home={k: round(v, 1) for k, v in home.items()})

    def read_front():
        if robot is None:
            return source.read(), None
        obs = robot.get_observation()
        return obs["front"], obs

    recorder = None
    if args.record_dir is not None:
        from pipeline_recording import Recorder, render

        recorder = Recorder(args.record_dir, {"dry_run": args.dry_run, "yolo": args.yolo,
                                              "plastic_model": args.plastic_model, "metal_model": args.metal_model,
                                              "lock_seconds": args.lock_seconds, "log_file": str(log.path)})
        log("recording", dir=str(args.record_dir))

    def record(front, wrist, mode, detections=None, lock=None):
        if recorder is not None and front is not None:
            recorder.add(front, wrist, mode, detections, lock)

    def record_cameras(mode):
        """Record the cameras' latest frames where no observation is read (easing home)."""
        if recorder is None:
            return
        try:
            wrist = robot.cameras["wrist"].read_latest() if "wrist" in robot.cameras else None
            record(robot.cameras["front"].read_latest(), wrist, mode)
        except (RuntimeError, TimeoutError):
            pass  # a missing frame in the video must never stop the arm going home

    # Started after robot.connect(), which may ask on the terminal about the calibration
    stop = threading.Event()
    threading.Thread(target=watch_for_exit, args=(stop,), daemon=True).start()
    print("Type exit + Enter (or Ctrl+C) to stop.", flush=True)

    mode = "yolo"  # what drives the arm: 'yolo' (nothing, YOLO watches) or the ACT's class
    streak_class, streak_since = None, 0.0
    last_run, failures = None, 0  # (class, box) of the item of the previous ACT run
    blocked = {}  # class -> time it was last seen while blocked
    try:
        while not stop.is_set():
            frame, obs = read_front()
            if frame is None:
                log("source_ended")
                break
            detections = detector(frame)
            now = time.monotonic()

            # Classes blocked after too many failed attempts come back once unseen for 3 s
            seen = {d["class"] for d in detections}
            for cls in list(blocked):
                if cls in seen:
                    blocked[cls] = now
                elif now - blocked[cls] > 3:
                    del blocked[cls]
                    log("unblocked", cls=cls)
            candidates = [d for d in detections if d["class"] not in blocked]
            # The same class must win every frame for --lock-seconds; any other result restarts it
            top = candidates[0]["class"] if candidates else None
            if top != streak_class:
                streak_class, streak_since = top, now
            held = now - streak_since if top else 0.0
            display.show(frame, detections, f"DETECT {top or '-'} {held:.1f}/{args.lock_seconds:g}s")
            record(frame, obs.get("wrist") if obs else None, "yolo", detections,
                   (top, round(held, 1)) if top else None)
            if top is None or held < args.lock_seconds:
                continue

            # Locked
            cls, item = top, candidates[0]
            # Same class at the same place as last time: the previous run did not move the item
            same_item = last_run is not None and last_run[0] == cls and iou(last_run[1], item["box"]) > 0.3
            failures = failures + 1 if same_item else 1
            if failures > args.max_attempts:
                blocked[cls] = now
                log("blocked", cls=cls, reason=f"{args.max_attempts} attempts did not move the item")
                last_run, failures, streak_class = None, 0, None
                continue
            last_run = (cls, item["box"])
            log("locked", cls=cls, conf=item["conf"], box=item["box"], attempt=failures)
            mode = cls

            if robot is None:
                log("act_simulated", cls=cls, model=policies[cls].path, seconds=args.dry_run_act_s)
                end = time.monotonic() + args.dry_run_act_s
                while time.monotonic() < end and not stop.is_set():
                    frame = source.read()
                    if frame is None:
                        break
                    display.show(frame, [], f"ACT {cls} (simulated)")
                    record(frame, None, cls)
            else:
                from lerobot.utils.robot_utils import precise_sleep

                policy = policies[cls]
                policy.reset()
                started, left, reason = time.monotonic(), False, "timeout"
                still_pose, still_since = None, 0.0  # pose and time the arm came to rest at home
                while time.monotonic() - started < args.episode_time:
                    if stop.is_set():
                        reason = "stopped"
                        break
                    tick = time.perf_counter()
                    obs = robot.get_observation()
                    policy.step(robot, obs)
                    pose = joint_pose(obs)
                    deviation = max_deviation(pose, home)
                    left = left or deviation > args.leave_deg
                    # Back home and still: the timer restarts whenever a joint moves > --still-deg
                    if left and deviation < args.home_tolerance_deg:
                        if still_pose is None or max_deviation(pose, still_pose) > args.still_deg:
                            still_pose, still_since = pose, time.monotonic()
                    else:
                        still_pose = None
                    still = time.monotonic() - still_since if still_pose is not None else 0.0
                    state = f"ACT {cls} {time.monotonic() - started:.0f}s dev {deviation:.0f}°"
                    if still_pose is not None:
                        state += f" home {still:.1f}/{args.home_still_s:g}s"
                    display.show(obs["front"], [], state)
                    record(obs["front"], obs.get("wrist"), cls)
                    if still >= args.home_still_s:
                        reason = "returned_home"
                        break
                    precise_sleep(max(0.0, 1 / args.fps - (time.perf_counter() - tick)))
                log("act_done", cls=cls, reason=reason, seconds=round(time.monotonic() - started, 1))
                ease_to(robot, home, on_step=lambda: record_cameras(cls))
                log("home")
            mode = "yolo"
            streak_class = None
    except KeyboardInterrupt:
        log("stopped_by_user", how="ctrl+c")
    finally:
        if stop.is_set():
            log("stopped_by_user", how="exit")
        if robot is not None and robot.is_connected:
            try:
                ease_to(robot, home, on_step=lambda: record_cameras(mode))
            finally:
                robot.disconnect()
        if source is not None:
            source.close()
        if recorder is not None:
            recorder.close()
            log("recording_saved", dir=str(args.record_dir), frames=recorder.counts["front"],
                dropped_frames=recorder.dropped)
        log("end", log_file=str(log.path))

    if recorder is not None:
        try:
            render(args.record_dir)
        except KeyboardInterrupt:
            print(f"Video not made. Make it later with: python scripts/run/pipeline_recording.py {args.record_dir}")


if __name__ == "__main__":
    main()

"""What the box pipeline (box_pipeline.py) needs around its state machine: the event log, the Rerun display,
the pick model stepped like lerobot-rollout, a frame source for --dry-run, and the stop-by-typing watcher.

Importing this module patches lerobot as for every other run on the arm (lerobot_wide_fov: full-FOV camera
capture, follower speed limits from the SERVO_* env vars, staggered torque-on) and installs the emergency
stop (arm_estop, estop window).
"""

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
import arm_estop  # noqa: E402
import estop  # noqa: E402
import lerobot_wide_fov  # noqa: E402,F401

arm_estop.install()  # the red emergency stop button releases the follower's torque
estop.start_estop_window()


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
        colors = {"metal": (60, 120, 255), "plastic": (60, 220, 60)}  # anything else: grey
        rr.log("front/detections", rr.Boxes2D(
            array=[d["box"] for d in detections], array_format=rr.Box2DFormat.XYXY,
            labels=[f"{d['class']} {d['conf']:.2f}" for d in detections],
            colors=[colors.get(d["class"], (160, 160, 160)) for d in detections]))
        rr.log("state", rr.TextLog(state))


class Policy:
    """One ACT model with its pre/post-processors, stepped like lerobot-rollout --inference.type=sync."""

    def __init__(self, path: str, task: str, device: str):
        from lerobot.configs import PreTrainedConfig
        from lerobot.policies import get_policy_class, make_pre_post_processors

        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "policies"))
        import lerobot_policy_act_dino  # noqa: F401  registers act_dino (ACT with a DINO encoder)

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

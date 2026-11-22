"""State machine of the box pipeline (docs/box-pipeline.md, proposal: docs/pipeline-proposal.md).

Math does what is predictable and models do what is not: the models only say what an item is
and grasp it; every other motion is a minimum-jerk move between named poses.

    WAIT      arm at home, doors closed: background difference against the empty tray
    SETTLE    wait until the image stops changing (timeout: the item keeps rolling -> DROP)
    CLASSIFY  detect every item over a few settled frames, classify each one, pick a target
    HOVER     move over the tray, gripper open
    GRASP     the grasper (policy or scripted) runs until the grasp check holds, or times out
    CARRY     transit pose, then the bin of the class, gripper held by position; slip -> HOME
    RELEASE   open the gripper over the bin
    HOME      back to the start pose, then SETTLE and CLASSIFY again (the scene has changed)
    DROP      arm at home: the ESP32 doors open and close; for `other`, failed and stuck items

All hardware comes in through small interfaces (see box_pipeline.py for the real ones and
tests/test_box_pipeline.py for fakes), so this module has no side effects on import.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from box_logic import (GRIPPER, JOINT_KEYS, BackgroundTrigger, GraspCheck, Item, SettleGate, choose_target,
                       crop_box, group_detections, hold_command, iou, max_joint_distance, record_failure,
                       slipped, trajectory)


class Stop(Exception):
    """The user asked to stop."""


class Paused(Exception):
    """The emergency stop was pressed during a motion."""


class DoorError(RuntimeError):
    pass


class Clock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float):
        if seconds > 0:
            time.sleep(seconds)


# --- door ----------------------------------------------------------------------------------------

class DoorSequencer:
    """One drop cycle on the ESP32 (scripts/common/drop_panel.py DropController).

    States (electronics/drop_firmware doorState()): OFF until the servos are attached at boot,
    OPENING / CLOSING while moving, PARTIAL while the doors move different ways or stand between
    the ends, STOPPED after STOP or an overload (latched: needs a person).

    OPEN is queued and only sent on the controller's next poll, so the status still says CLOSED
    for a moment: wait to see it leave CLOSED, then wait for CLOSED again."""

    def __init__(self, controller, clock: Clock, open_timeout_s=3.0, cycle_timeout_s=15.0, ready_timeout_s=30.0,
                 ready_hold_s=2.0, partial_s=1.0):
        self.controller, self.clock = controller, clock
        self.open_timeout_s, self.cycle_timeout_s, self.ready_timeout_s = open_timeout_s, cycle_timeout_s, ready_timeout_s
        self.ready_hold_s, self.partial_s = ready_hold_s, partial_s

    def _wait(self, condition, timeout_s, what, fatal=("STOPPED", "OFF"), hold_s=0.0):
        """Until condition holds for hold_s. PARTIAL is fatal only when it lasts partial_s."""
        end = self.clock.now() + timeout_s
        since, partial_since = None, None
        while self.clock.now() < end:
            now, status = self.clock.now(), self.controller.status
            if not status.connected:
                raise DoorError(f"drop mechanism disconnected while {what} ({status.message})")
            if status.state in fatal and status.state != "PARTIAL":
                raise DoorError(f"drop mechanism {status.state} while {what} ({status.message})")
            partial_since = (partial_since or now) if status.state == "PARTIAL" else None
            if "PARTIAL" in fatal and partial_since is not None and now - partial_since >= self.partial_s:
                raise DoorError(f"doors stuck half-way while {what} ({status.message})")
            since = (since if since is not None else now) if condition(status) else None
            if since is not None and now - since >= hold_s:
                return
            self.clock.sleep(0.05)
        raise DoorError(f"timeout ({timeout_s:g} s) while {what}, state {self.controller.status.state}")

    def wait_ready(self):
        """Connected and CLOSED for ready_hold_s, not calibrating. Opening the port can reset the
        C3: it reports OFF, then runs a door cycle with a zero measurement (CAL=1) after it."""
        end = self.clock.now() + self.ready_timeout_s
        while not self.controller.status.connected and self.clock.now() < end:
            self.clock.sleep(0.1)
        self._wait(lambda s: s.state == "CLOSED" and not s.calibrating, self.ready_timeout_s,
                   "waiting for CLOSED", fatal=("STOPPED",), hold_s=self.ready_hold_s)

    def drop(self):
        self.wait_ready()
        self.controller.send("OPEN")
        fatal = ("STOPPED", "OFF", "PARTIAL")
        self._wait(lambda s: s.state != "CLOSED", self.open_timeout_s, "opening", fatal)
        self._wait(lambda s: s.state == "CLOSED", self.cycle_timeout_s, "closing", fatal)


# --- graspers ------------------------------------------------------------------------------------

class ScriptedGrasper:
    """Fake grasp for testing the state machine without a model: lower to the `tray_low` pose,
    close the gripper, lift back to `hover`. Only grasps something placed under the `tray_low` pose."""

    def __init__(self, poses, motion: dict, close_to: float = 0.0):
        self.poses, self.motion, self.close_to = poses, motion, close_to
        self.plan: list[dict] = []

    def reset(self, start: dict):
        m = self.motion
        opened = {**self.poses["tray_low"], GRIPPER: m["gripper_open"]}
        closed = {**opened, GRIPPER: self.close_to}
        lifted = {**self.poses["hover"], GRIPPER: self.close_to}
        self.plan = (trajectory(start, opened, m["speed_deg_s"], m["min_move_s"], m["fps"])
                     + trajectory(opened, closed, m["speed_deg_s"], 0.8, m["fps"])
                     + [closed] * int(0.3 * m["fps"])
                     + trajectory(closed, lifted, m["speed_deg_s"], m["min_move_s"], m["fps"]))

    def action(self, obs: dict) -> dict:
        return self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]


# --- the state machine ---------------------------------------------------------------------------

@dataclass
class Hooks:
    """What the state machine reports to the outside (log, display, recording)."""

    log: callable
    frame: callable = lambda obs, mode, detections=None, state="": None


class BoxPipeline:
    def __init__(self, arm, detector, classify, grasper, door, poses: dict, config: dict, hooks: Hooks,
                 clock: Clock | None = None, should_stop=lambda: False, paused=lambda: False):
        """arm: observe() -> obs dict (joints + 'front' [+ 'wrist'] RGB), send(action dict).
        detector(frame) -> [{'box', 'class', 'conf'}]; classify(items) sets item.cls / item.info.
        grasper: reset(start pose), action(obs) -> joint command. door: DoorSequencer or None."""
        self.arm, self.yolo, self.classify, self.grasper, self.door = arm, detector, classify, grasper, door
        self.poses, self.cfg, self.hooks = poses, config, hooks
        self.clock = clock or Clock()
        self.should_stop, self.paused = should_stop, paused
        self.log = hooks.log
        t = config["trigger"]
        self.region = tuple(t["tray_region"])
        self.trigger = BackgroundTrigger(self.region, t["pixel_diff"], t["occupied_fraction"])
        self.command: dict | None = None
        self.failed: list = []  # (box, attempts) of items that were not picked
        self.target: Item | None = None
        self.drops_in_a_row = 0
        self.state = "START"

    # -- low level ------------------------------------------------------------------------------

    def check(self):
        if self.should_stop():
            raise Stop
        if self.paused():
            raise Paused

    def observe(self) -> dict:
        return self.arm.observe()

    def detector(self, frame) -> list[dict]:
        """Detections centred in the tray region: items already in a bin are not seen."""
        x0, y0, x1, y1 = self.region
        return [d for d in self.yolo(frame)
                if x0 <= (d["box"][0] + d["box"][2]) / 2 <= x1 and y0 <= (d["box"][1] + d["box"][3]) / 2 <= y1]

    def joints(self, obs: dict) -> dict:
        return {k: obs[k] for k in JOINT_KEYS}

    def send(self, command: dict):
        self.command = dict(command)
        self.arm.send(self.command)

    def tick(self, started: float):
        self.clock.sleep(1 / self.cfg["motion"]["fps"] - (self.clock.now() - started))

    def move_to(self, target: dict, mode: str, on_step=None):
        """Minimum-jerk move from where the arm is (gripper: from its last command)."""
        m = self.cfg["motion"]
        obs = self.observe()
        start = self.joints(obs)
        if self.command is not None:
            start[GRIPPER] = self.command[GRIPPER]
        for step in trajectory(start, target, m["speed_deg_s"], m["min_move_s"], m["fps"]):
            began = self.clock.now()
            self.check()
            self.send(step)
            obs = self.observe()
            self.hooks.frame(obs, mode, state=self.state)
            if on_step is not None and on_step(obs) is False:
                return False
            self.tick(began)
        return True

    def hold(self, seconds: float, mode: str):
        end = self.clock.now() + seconds
        while self.clock.now() < end:
            began = self.clock.now()
            self.check()
            self.send(self.command)
            self.hooks.frame(self.observe(), mode, state=self.state)
            self.tick(began)

    def front_frames(self, n: int | None = None):
        """Front frames at the control rate while the arm holds still (it keeps its command)."""
        count = 0
        while n is None or count < n:
            began = self.clock.now()
            self.check()
            if self.command is not None:
                self.send(self.command)
            obs = self.observe()
            yield obs
            count += 1
            self.tick(began)

    # -- states ---------------------------------------------------------------------------------

    def start(self):
        self.state = "START"
        if self.door is not None:
            self.log("door_wait")
            self.door.wait_ready()
        self.move_to(self.poses["home"], "yolo")
        # Reference after the door is closed and the arm is home: the tray must be empty now
        frames = list(self.front_frames(5))
        self.trigger.set_reference(frames[-1]["front"])
        self.log("ready", reference="taken")
        return "WAIT"

    def wait(self):
        every = self.cfg["trigger"].get("yolo_every_n", 5)
        for i, obs in enumerate(self.front_frames()):
            front = obs["front"]
            fraction = self.trigger.fraction(front)
            detections = self.detector(front) if i % every == 0 else []
            self.hooks.frame(obs, "yolo", detections, f"WAIT change {fraction:.3f}")
            if fraction > self.trigger.min_fraction or detections:
                self.log("triggered", changed=round(fraction, 4), detections=len(detections))
                return "SETTLE"

    def settle(self):
        t = self.cfg["trigger"]
        gate = SettleGate(self.region, t["pixel_diff"], t["still_fraction"], t["settle_s"])
        started = self.clock.now()
        for obs in self.front_frames():
            now = self.clock.now()
            settled = gate.update(now, obs["front"])
            self.hooks.frame(obs, "yolo", state=f"SETTLE {now - started:.1f}s")
            if settled:
                return "CLASSIFY"
            if now - started > t["settle_timeout_s"]:
                self.log("never_settled", seconds=round(now - started, 1))
                return "DROP"

    def classify_tray(self):
        t = self.cfg["trigger"]
        frames, last = [], None
        for obs in self.front_frames(t["classify_frames"]):
            detections = self.detector(obs["front"])
            for d in detections:
                d["crop"] = crop_box(obs["front"], d["box"], self.cfg["classifier"].get("crop_pad", 0.15))
            frames.append(detections)
            self.hooks.frame(obs, "yolo", detections, "CLASSIFY")
            last = obs["front"]
        items = group_detections(frames)
        self.classify(items)
        occupied = self.trigger.occupied(last)
        self.log("classified", occupied=occupied,
                 items=[{"cls": it.cls, "box": [round(v) for v in it.box], **it.info} for it in items])
        self.target = choose_target(items, self.failed, self.cfg["grasp"]["max_attempts"])
        if self.target is not None:
            self.drops_in_a_row = 0
            self.log("target", cls=self.target.cls, box=[round(v) for v in self.target.box])
            return "HOVER"
        if items or occupied:
            return "DROP"
        self.failed.clear()
        self.drops_in_a_row = 0
        return "WAIT"

    def hover(self):
        self.move_to({**self.poses["hover"], GRIPPER: self.cfg["motion"]["gripper_open"]}, self.target.cls)
        return "GRASP"

    def grasp(self):
        g = self.cfg["grasp"]
        cls = self.target.cls
        self.grasper.reset(self.joints(self.observe()) | {GRIPPER: self.command[GRIPPER]})
        check = GraspCheck(self.poses["hover"], g["blocked_deg"], g["lift_joint"], g["lift_deg"], g["hold_s"])
        started = self.clock.now()
        while self.clock.now() - started < g["timeout_s"]:
            began = self.clock.now()
            self.check()
            obs = self.observe()
            self.send(self.grasper.action(obs))
            ok = check.update(self.clock.now(), self.joints(obs), self.command)
            self.hooks.frame(obs, cls, state=f"GRASP {self.clock.now() - started:.1f}s")
            if ok:
                self.grasped_at = obs[GRIPPER]
                self.log("grasped", cls=cls, gripper=round(obs[GRIPPER], 1),
                         seconds=round(self.clock.now() - started, 1))
                return "CARRY"
            self.tick(began)
        attempts = record_failure(self.failed, self.target.box)
        self.log("grasp_failed", cls=cls, attempt=attempts, of=g["max_attempts"])
        # Let go of whatever is half-held, over the tray
        self.move_to({**self.joints(self.observe()), GRIPPER: self.cfg["motion"]["gripper_open"]}, cls)
        if attempts < g["max_attempts"]:
            return "HOVER"
        self.log("gave_up", cls=cls, box=[round(v) for v in self.target.box])
        return "HOME"

    def carry(self):
        g, cls = self.cfg["grasp"], self.target.cls
        holding = hold_command(self.grasped_at, g["squeeze_deg"])

        def watch(obs):
            if slipped(obs[GRIPPER], self.grasped_at, g["slip_deg"]):
                self.log("slipped", cls=cls, gripper=round(obs[GRIPPER], 1), grasped_at=round(self.grasped_at, 1))
                return False
            return True

        for pose in ("transit", f"{cls}_bin"):
            if not self.move_to({**self.poses[pose], GRIPPER: holding}, cls, on_step=watch):
                return "HOME"
        return "RELEASE"

    def release(self):
        m, cls = self.cfg["motion"], self.target.cls
        self.move_to({**self.joints(self.observe()), GRIPPER: m["gripper_open"]}, cls)
        self.hold(m["release_s"], cls)
        self.log("sorted", cls=cls)
        # A sorted item frees its place: forget failures recorded there
        self.failed = [(box, n) for box, n in self.failed if iou(box, self.target.box) <= 0.3]
        return "HOME"

    def home(self):
        self.move_to(self.poses["home"], "yolo")
        return "SETTLE"

    def drop(self):
        if max_joint_distance(self.joints(self.observe()), self.poses["home"]) > 5:
            self.move_to(self.poses["home"], "yolo")  # the doors only open with the arm at home
        self.drops_in_a_row += 1
        if self.door is None:
            self.log("clear_tray", reason="no drop mechanism: take the items out by hand")
            for obs in self.front_frames():
                self.hooks.frame(obs, "yolo", state="DROP: clear the tray by hand")
                if not self.trigger.occupied(obs["front"]):
                    break
        else:
            self.log("drop", in_a_row=self.drops_in_a_row)
            self.door.drop()
        self.failed.clear()
        if self.drops_in_a_row >= self.cfg["door"]["max_drops_in_a_row"]:
            # Still "occupied" after dropping everything: the empty-tray reference is stale
            # (light changed, tray moved). The doors just emptied the tray, so take a new one.
            frames = list(self.front_frames(5))
            self.trigger.set_reference(frames[-1]["front"])
            self.drops_in_a_row = 0
            self.log("reference_refreshed")
            return "WAIT"
        return "SETTLE"

    # -- loop -----------------------------------------------------------------------------------

    HANDLERS = {"WAIT": "wait", "SETTLE": "settle", "CLASSIFY": "classify_tray", "HOVER": "hover",
                "GRASP": "grasp", "CARRY": "carry", "RELEASE": "release", "HOME": "home", "DROP": "drop"}

    def run(self, max_states: int | None = None):
        """Run until stopped. max_states limits the number of state changes (tests)."""
        while True:
            try:
                self.state = self.start()
                break
            except Paused:
                self.wait_while_paused()
        count = 0
        while max_states is None or count < max_states:
            self.log("state", state=self.state)
            try:
                self.state = getattr(self, self.HANDLERS[self.state])()
            except Paused:
                self.state = self.wait_while_paused()
            count += 1

    def wait_while_paused(self):
        """Emergency stop: keep commanding the measured pose (the guard needs the calls to finish
        the release, and on resume the arm then stays where it was put), then go home."""
        self.log("estop", action="paused")
        while self.paused():
            if self.should_stop():
                raise Stop
            self.send(self.joints(self.observe()))
            self.clock.sleep(1 / self.cfg["motion"]["fps"])
        try:
            self.hold(2.5, "yolo")  # the guard blends the torque back in over ESTOP_RESUME_S (2 s)
        except Paused:  # pressed again while resuming
            return self.wait_while_paused()
        self.log("estop", action="resumed")
        return "HOME"

    def shutdown(self):
        """After a stop: back home, gripper as in the home pose. Errors here are reported, not raised."""
        try:
            self.should_stop = lambda: False
            self.paused = lambda: False
            self.move_to(self.poses["home"], "yolo")
        except Exception as error:  # noqa: BLE001
            self.log("shutdown_error", error=f"{error.__class__.__name__}: {error}")

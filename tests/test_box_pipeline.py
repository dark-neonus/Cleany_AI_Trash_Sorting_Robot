"""Box pipeline (scripts/run/box_states.py, scripts/common/box_logic.py, dino_classifier.decide)
without an arm, camera, door or GPU: fakes stand in for all of them."""

from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from box_logic import (GRIPPER, JOINT_KEYS, BackgroundTrigger, GraspCheck, Item, SettleGate, choose_target,
                       group_detections, load_poses, min_jerk, move_duration, record_failure, slipped, trajectory,
                       yolo_vote)
from box_states import BoxPipeline, DoorError, DoorSequencer, Hooks, ScriptedGrasper, Stop
from dino_classifier import Gallery, decide, normalise

CONFIG = yaml.safe_load(open(__import__("pathlib").Path(__file__).parents[1] / "config" / "box_pipeline.yaml"))


def pose(**degrees):
    return {k: float(degrees.get(k.split(".")[0], 0)) for k in JOINT_KEYS}


POSES = {"home": pose(shoulder_lift=-100, elbow_flex=95), "hover": pose(shoulder_lift=-40),
         "grasp": pose(shoulder_lift=-10), "centre": pose(shoulder_lift=-60),
         "metal_bin": pose(shoulder_pan=-40, shoulder_lift=-50), "plastic_bin": pose(shoulder_pan=40, shoulder_lift=-50)}


# --- motion and poses ----------------------------------------------------------------------------

def test_min_jerk_starts_and_ends_at_rest():
    assert min_jerk(0) == 0 and min_jerk(1) == 1 and min_jerk(0.5) == pytest.approx(0.5)
    assert min_jerk(0.01) < 0.001  # slow start


def test_move_takes_longer_for_longer_moves_and_ends_on_target():
    a, b = pose(), pose(shoulder_pan=90)
    assert move_duration(a, b, 45, 0.8) == pytest.approx(2.0)
    assert move_duration(a, pose(shoulder_pan=5), 45, 0.8) == 0.8
    path = trajectory(a, b, 45, 0.8, 30)
    assert len(path) == 60 and path[-1] == b


def test_missing_pose_file_or_pose_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_poses(tmp_path / "poses.yaml")
    path = tmp_path / "poses.yaml"
    path.write_text(yaml.safe_dump({"poses": {"home": POSES["home"]}}))
    with pytest.raises(KeyError, match="hover"):
        load_poses(path)
    path.write_text(yaml.safe_dump({"poses": POSES}))
    assert load_poses(path)["hover"] == POSES["hover"]


# --- grasp check ---------------------------------------------------------------------------------

def run_check(lift_path, measured_gripper, commanded_gripper=0.0, dt=0.1):
    check = GraspCheck(POSES["hover"], blocked_deg=4, lift_deg=8, hold_s=0.3)
    results = []
    for i, lift in enumerate(lift_path):
        measured = pose(shoulder_lift=lift, gripper=measured_gripper)
        results.append(check.update(i * dt, measured, pose(gripper=commanded_gripper)))
    return results


def test_grasp_holds_when_fingers_blocked_and_arm_raised():
    down_then_up = [-40, -25, -10, -10, -20, -30, -30, -30, -30, -30]
    assert run_check(down_then_up, measured_gripper=15)[-1] is True


def test_closing_on_nothing_is_not_a_grasp():
    down_then_up = [-40, -25, -10, -10, -20, -30, -30, -30, -30, -30]
    assert not any(run_check(down_then_up, measured_gripper=1))


def test_holding_but_not_lifted_is_not_a_grasp():
    assert not any(run_check([-40, -25, -10, -10, -10, -10, -10, -10], measured_gripper=15))


def test_slip_is_closing_past_the_grasp():
    assert not slipped(14, grasped_at=15, slip_deg=6)
    assert slipped(8, grasped_at=15, slip_deg=6)


# --- trigger and settle --------------------------------------------------------------------------

def tray(item_at=None, size=60, shade=200):
    frame = np.full((480, 640, 3), 90, dtype=np.uint8)
    if item_at is not None:
        x, y = item_at
        frame[y:y + size, x:x + size] = shade
    return frame


def test_background_trigger_sees_an_item_of_any_kind():
    trigger = BackgroundTrigger((0, 0, 640, 480))
    trigger.set_reference(tray())
    assert not trigger.occupied(tray())
    noisy = np.clip(tray().astype(int) + np.random.default_rng(0).integers(-8, 9, (480, 640, 3)), 0, 255)
    assert not trigger.occupied(noisy.astype(np.uint8))
    assert trigger.occupied(tray((300, 200)))


def test_settle_waits_until_the_item_stops():
    gate = SettleGate((0, 0, 640, 480), settle_s=0.5)
    t, results = 0.0, []
    for x in (100, 140, 180, 200, 200, 200, 200, 200, 200, 200):  # rolls, then stops
        results.append(gate.update(t, tray((x, 200))))
        t += 0.125  # exact in binary
    # still from the 5th frame (t=0.5); settled 0.5 s later, at the 9th
    assert results.index(True) == 8 and not any(results[:8])


# --- items and target ----------------------------------------------------------------------------

def det(box, cls="metal", conf=0.9):
    return {"box": box, "class": cls, "conf": conf}


def test_detections_over_frames_become_items_and_flicker_is_dropped():
    frames = [[det([100, 100, 160, 160]), det([400, 100, 450, 150], "plastic")],
              [det([102, 101, 161, 160]), det([401, 100, 451, 151], "plastic")],
              [det([101, 100, 160, 161]), det([300, 300, 320, 320])],  # one-frame ghost
              [det([100, 99, 160, 160]), det([400, 101, 450, 150], "plastic")]]
    items = group_detections(frames)
    assert len(items) == 2
    assert items[0].box == pytest.approx([100.5, 100, 160, 160])
    assert yolo_vote(items[1], 0.6) == "plastic"
    assert yolo_vote(Item(box=[0, 0, 1, 1], votes=[("metal", 0.4)]), 0.6) == "other"


def test_target_is_the_freest_sortable_item_not_failed_or_overlapping():
    a = Item(box=[0, 0, 50, 50], cls="metal")
    b = Item(box=[60, 0, 110, 50], cls="plastic")  # 10 px from a
    c = Item(box=[400, 400, 450, 450], cls="plastic")  # far from everything
    other = Item(box=[200, 0, 250, 50], cls="other")
    assert choose_target([a, b, c, other], [], 3) is c
    failed = []
    for _ in range(3):
        record_failure(failed, c.box)
    assert choose_target([a, b, c, other], failed, 3) in (a, b)
    overlapping = Item(box=[10, 10, 60, 60], cls="metal")
    assert choose_target([a, overlapping], [], 3) is None
    assert choose_target([other], [], 3) is None


# --- classifier rule -----------------------------------------------------------------------------

def gallery():
    rng = np.random.default_rng(0)
    metal_dir, plastic_dir = np.eye(16)[0], np.eye(16)[1]
    emb = normalise(np.concatenate([metal_dir + 0.05 * rng.normal(size=(10, 16)),
                                    plastic_dir + 0.05 * rng.normal(size=(10, 16))]))
    return Gallery(emb, np.array(["metal"] * 10 + ["plastic"] * 10), np.arange(20).astype(str), "test")


def test_decide_known_unknown_and_ambiguous():
    g = gallery()
    assert decide(np.eye(16)[0], g, k=3, max_distance=0.3, min_margin=0.05).cls == "metal"
    assert decide(np.eye(16)[1], g, k=3, max_distance=0.3, min_margin=0.05).cls == "plastic"
    unknown = decide(np.eye(16)[5], g, k=3, max_distance=0.3, min_margin=0.05)
    assert unknown.cls == "other" and "unlike" in unknown.reason
    between = decide(np.eye(16)[0] + np.eye(16)[1], g, k=3, max_distance=0.6, min_margin=0.05)
    assert between.cls == "other" and "too close" in between.reason


# --- door ----------------------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.001)


class FakeController:
    """States the ESP32 reports, one per poll, after OPEN was sent."""

    def __init__(self, after_open=("CLOSED", "OPENING", "OPEN", "CLOSING", "CLOSED")):
        self.after_open = list(after_open)
        self.sent = []
        self._state = "CLOSED"

    @property
    def status(self):
        if self.sent and self.after_open:
            self._state = self.after_open.pop(0)
        return SimpleNamespace(connected=True, state=self._state, calibrating=False, message="")

    def send(self, command):
        self.sent.append(command)


def test_door_cycle_waits_for_open_then_closed():
    controller = FakeController()
    DoorSequencer(controller, FakeClock()).drop()
    assert controller.sent == ["OPEN"] and controller._state == "CLOSED"


def test_door_fault_and_timeout_raise():
    with pytest.raises(DoorError, match="STOPPED"):
        DoorSequencer(FakeController(("OPENING", "STOPPED")), FakeClock()).drop()
    with pytest.raises(DoorError, match="timeout"):
        DoorSequencer(FakeController(("CLOSED",) * 10_000), FakeClock(), open_timeout_s=1).drop()


# --- whole state machine -------------------------------------------------------------------------

class World:
    """A tray with items, a simulated arm that follows commands, and a door that empties the tray."""

    def __init__(self, items, grasp_works=True):
        # (class, (x, y)); they arrive after start-up, once the empty-tray reference is taken
        self.arriving, self.items, self.observed = list(items), [], 0
        self.joints = dict(POSES["home"])
        self.holding = False
        self.grasp_works = grasp_works
        self.events = []
        self.drops = 0

    # arm
    def observe(self):
        self.observed += 1
        if self.observed == 100:
            self.items = list(self.arriving)
        frame = tray()
        for _, (x, y) in self.items:
            frame[y:y + 60, x:x + 60] = 200
        return {**self.joints, "front": frame}

    def send(self, action):
        if self.grasp_works and self.items and self.joints[GRIPPER] > 20 >= action[GRIPPER]:
            self.holding = True
        elif action[GRIPPER] > 30:
            self.holding = False
        self.joints = dict(action)
        if self.holding:
            self.joints[GRIPPER] = max(action[GRIPPER], 15)

    # perception
    def detector(self, frame):
        return [det([x, y, x + 60, y + 60], cls) for cls, (x, y) in self.items]

    def classify(self, items):
        for item in items:
            item.cls = next(cls for cls, (x, y) in self.items if abs(item.box[0] - x) < 5)

    # door
    def wait_ready(self):
        pass

    def drop(self):
        self.drops += 1
        self.items.clear()

    def log(self, event, **data):
        self.events.append((event, data))
        if event == "sorted":
            self.items = [it for it in self.items if it[0] != data["cls"]][:]  # the item left the tray

    def run(self, seconds):
        """Run the pipeline for this many simulated seconds (WAIT never ends by itself)."""
        clock = FakeClock()
        pipeline = BoxPipeline(self, self.detector, self.classify, ScriptedGrasper(POSES, CONFIG["motion"]), self,
                               POSES, CONFIG, Hooks(self.log), clock=clock, should_stop=lambda: clock.t > seconds)
        with pytest.raises(Stop):
            pipeline.run()
        return pipeline

    def names(self):
        return [e for e, _ in self.events]


def test_metal_item_is_sorted_into_the_metal_bin():
    world = World([("metal", (300, 200))])
    world.run(seconds=60)
    names = world.names()
    assert names.index("triggered") < names.index("grasped") < names.index("sorted")
    assert ("sorted", {"cls": "metal"}) in world.events
    assert world.items == [] and world.drops == 0
    assert world.joints == POSES["home"]  # home again, gripper as in the home pose


def test_other_item_goes_through_the_door_with_the_arm_at_home():
    world = World([("other", (300, 200))])
    world.run(seconds=60)
    assert world.drops == 1 and "grasped" not in world.names()


def test_failed_grasps_end_in_the_mixed_bin():
    world = World([("plastic", (300, 200))], grasp_works=False)
    world.run(seconds=120)
    failures = [d["attempt"] for e, d in world.events if e == "grasp_failed"]
    assert failures == [1, 2, 3]
    assert "gave_up" in world.names() and world.drops == 1


def test_stop_request_ends_the_run():
    world = World([])
    clock = FakeClock()
    pipeline = BoxPipeline(world, world.detector, world.classify, ScriptedGrasper(POSES, CONFIG["motion"]), world,
                           POSES, CONFIG, Hooks(world.log), clock=clock, should_stop=lambda: clock.t > 3)
    with pytest.raises(Stop):
        pipeline.run()


class Statuses:
    """A controller that reports a fixed sequence of (state, calibrating), one per poll."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.sent = []

    @property
    def status(self):
        state, cal = self.sequence.pop(0) if len(self.sequence) > 1 else self.sequence[0]
        return SimpleNamespace(connected=True, state=state, calibrating=cal, message="")

    def send(self, command):
        self.sent.append(command)


def test_door_ready_waits_out_the_boot_cycle():
    # boot: OFF, a CLOSED blip, then the start-up cycle with its zero measurement
    boot = ([("OFF", False)] * 5 + [("CLOSED", False)] * 2 + [("OPENING", True)] * 5 + [("OPEN", True)] * 5
            + [("CLOSING", True)] * 5 + [("CLOSED", True)] * 20 + [("CLOSED", False)])
    clock = FakeClock()
    DoorSequencer(Statuses(boot), clock, ready_hold_s=2.0).wait_ready()
    assert clock.t >= 2.0 + 0.05 * (len(boot) - 1) - 1e-6  # the CLOSED blip did not count


def test_door_tolerates_a_short_partial_but_not_a_stuck_one():
    cycle = [("CLOSED", False)] * 50 + [("OPENING", False), ("PARTIAL", False), ("OPEN", False),
                                       ("CLOSING", False), ("CLOSED", False)]
    DoorSequencer(Statuses(cycle), FakeClock(), ready_hold_s=0.1).drop()
    stuck = [("CLOSED", False)] * 50 + [("OPENING", False)] + [("PARTIAL", False)] * 100
    with pytest.raises(DoorError, match="half-way"):
        DoorSequencer(Statuses(stuck), FakeClock(), ready_hold_s=0.1).drop()


def test_item_in_a_bin_is_not_picked():
    config = {**CONFIG, "trigger": {**CONFIG["trigger"], "tray_region": [150, 0, 500, 480]}}
    world = World([("metal", (20, 200))])  # centre x=50: in the left bin, outside the tray
    clock = FakeClock()
    pipeline = BoxPipeline(world, world.detector, world.classify, ScriptedGrasper(POSES, CONFIG["motion"]), world,
                           POSES, config, Hooks(world.log), clock=clock, should_stop=lambda: clock.t > 30)
    with pytest.raises(Stop):
        pipeline.run()
    assert "target" not in world.names() and "triggered" not in world.names()


def test_emergency_stop_mid_carry_then_resume_goes_home_and_goes_on():
    world = World([("metal", (300, 200))])
    clock = FakeClock()
    presses = []  # (from, to) simulated seconds the button is down

    def paused():
        if not presses and "grasped" in world.names():
            presses.extend([(clock.t, clock.t + 2), (clock.t + 3.0, clock.t + 4)])  # second press while resuming
        return any(a <= clock.t < b for a, b in presses)

    pipeline = BoxPipeline(world, world.detector, world.classify, ScriptedGrasper(POSES, CONFIG["motion"]), world,
                           POSES, CONFIG, Hooks(world.log), clock=clock, should_stop=lambda: clock.t > 90,
                           paused=paused)
    with pytest.raises(Stop):
        pipeline.run()
    actions = [d["action"] for e, d in world.events if e == "estop"]
    assert actions == ["paused", "paused", "resumed"]
    after = world.names()[world.names().index("estop"):]
    assert "state" in after and world.joints == POSES["home"]

"""Pick recording session (scripts/run/pick_session.py) without arms, cameras, doors or GPU."""

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from box_logic import GRIPPER, JOINT_KEYS
from box_states import Hooks
from dino_classifier import Decision
from pick_session import Commands, PickSession, PickStore, Status, changed_box, safe_name

ROOT = Path(__file__).parents[1]
CONFIG = yaml.safe_load((ROOT / "config" / "box_pipeline.yaml").read_text())
RECORDING = yaml.safe_load((ROOT / "config" / "pick_recording.yaml").read_text())


def pose(**degrees):
    return {k: float(degrees.get(k.split(".")[0], 0)) for k in JOINT_KEYS}


POSES = {"home": pose(shoulder_lift=-100, elbow_flex=95), "hover": pose(shoulder_lift=-40),
         "transit": pose(shoulder_lift=-60),
         "metal_bin": pose(shoulder_pan=-40, shoulder_lift=-50), "plastic_bin": pose(shoulder_pan=40, shoulder_lift=-50)}


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 1 / 30)


def tray(items=()):
    frame = np.full((480, 640, 3), 90, dtype=np.uint8)
    for x, y in items:
        frame[y:y + 60, x:x + 60] = 200
    return frame


class World:
    """Tray, follower, leader with a person's hand on it, doors, dataset recorder and button presses.

    presses: [(phase, command or 'stop', item position or None)], each sent once the session enters
    that phase. human: 'grasp' (lower, close, lift), 'idle' (never grasps) during RECORDING."""

    def __init__(self, presses, human="grasp", dino=None, estop_at=None):
        self.clock = FakeClock()
        self.presses, self.human, self.dino, self.estop_at = list(presses), human, dino, estop_at
        self.items, self.drops, self.stop = [], 0, False
        self.follower = dict(POSES["home"])
        self.holding = False
        self.leader = pose(shoulder_pan=10)  # starts away from the follower
        self.leader_torque, self.released_at = False, None
        self.phase, self.phase_since = None, 0.0
        self.episodes = {"begun": 0, "frames": 0, "saved": 0, "cancelled": 0}
        self.commands = Commands()
        self.events = []

    # follower
    def observe(self):
        return {**self.follower, "front": tray(self.items), "wrist": np.zeros((360, 640, 3), np.uint8)}

    def send(self, action):
        low = -70 <= self.follower["shoulder_lift.pos"] <= -50  # lowered onto the tray
        if self.items and low and self.follower[GRIPPER] > 20 >= action[GRIPPER]:
            self.holding = True
        elif action[GRIPPER] > 30:
            self.holding = False
        self.follower = dict(action)
        if self.holding:
            self.follower[GRIPPER] = max(action[GRIPPER], 15)

    def extras(self):
        return {k: np.zeros(6, np.float32) for k in ("velocity", "load", "current", "temperature", "voltage")}

    # leader
    def read(self):
        if self.leader_torque:
            pushed = self.phase == "ARMED" and self.clock.t - self.phase_since > 1.5
            return {**self.leader, "shoulder_pan.pos": self.leader["shoulder_pan.pos"] + (5 if pushed else 0)}
        if self.phase == "RECORDING" and self.human == "grasp":
            t = self.clock.t - self.released_at
            hover = POSES["hover"]["shoulder_lift.pos"]
            lift = hover - 20 * min(t, 1) + 15 * min(max(t - 2, 0), 1)
            grip = 60 if t < 1 else 0
            self.leader = {**self.leader, "shoulder_lift.pos": lift, GRIPPER: grip}
        return dict(self.leader)

    def command(self, degrees):
        assert self.leader_torque, "commanded the leader with its torque off"
        self.leader = dict(degrees)

    def set_torque(self, on):
        self.leader_torque = on
        if not on:
            self.released_at = self.clock.t

    # perception
    def detector(self, frame):
        return [{"box": [x, y, x + 60, y + 60], "class": "item", "conf": 0.9} for x, y in self.items]

    def embed(self, crops):
        return np.ones((len(crops), 4), np.float32) / 2

    def decide(self, vector):
        return None if self.dino is None else Decision(self.dino, {}, "test")

    # door
    def drop(self):
        self.drops += 1
        self.items.clear()

    # dataset
    def begin(self, task, item):
        assert item["embedding"].shape == (4,) and len(item["box"]) == 4
        self.episodes["begun"] += 1

    def add(self, obs, action, extras):
        self.episodes["frames"] += 1

    def cancel(self):
        self.episodes["cancelled"] += 1

    def save(self):
        self.episodes["saved"] += 1
        return self.episodes["saved"] - 1

    # session events: drive the button presses and the emergency stop
    def log(self, event, **data):
        self.events.append((event, data))
        if event == "phase":
            self.phase, self.phase_since = data["phase"], self.clock.t
            if self.presses and self.presses[0][0] == data["phase"]:
                _, command, item = self.presses.pop(0)
                if item is not None:
                    self.items.append(item)
                if command == "stop":
                    self.stop = True
                else:
                    self.commands.put(command)

    def paused(self):
        return self.estop_at is not None and self.estop_at <= self.clock.t < self.estop_at + 1

    def run(self, tmp_path, recording=RECORDING):
        store = PickStore(tmp_path, recording["outputs"], lambda path, rgb: Path(path).write_bytes(b"jpg"))
        self.status = Status()
        session = PickSession(self, self, self.detector, self.embed, self.decide, self, self, store, POSES, CONFIG,
                              recording, Hooks(self.log), self.commands, self.status, clock=self.clock,
                              should_stop=lambda: self.stop or self.clock.t > 600, paused=self.paused)
        session.run()
        return store

    def kept(self, store):
        return [json.loads(line) for line in store.records.read_text().splitlines()] if store.records.exists() else []


def test_metal_episode_is_recorded_from_hover_until_lifted(tmp_path):
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], dino="metal")
    store = world.run(tmp_path)
    assert world.episodes["begun"] == 1 and world.episodes["saved"] == 1 and world.episodes["frames"] > 30
    [record] = world.kept(store)
    assert record["material"] == "metal" and record["kind"] == "episode" and record["ended"] == "lifted"
    assert record["seconds"] < 10 and record["episode"] == 0
    assert record["label_from"] == "tray_change"
    labels = list((store.yolo / "labels").glob("pick_*.txt"))
    assert len(labels) == 1 and labels[0].read_text().startswith("0 ")  # class metal
    assert list((store.yolo / "labels").glob("empty_*.txt"))  # negative frame of the empty tray
    assert len(list((store.crops / "metal").glob("item_*.jpg"))) == 1
    assert world.drops == 1  # only at setup: the item went back onto the tray
    assert world.follower == POSES["home"] and not world.leader_torque


def test_discard_drops_the_episode_and_its_files(tmp_path):
    world = World([("READY", "plastic", (300, 200)), ("READY", "discard", None), ("READY", "stop", None)])
    store = world.run(tmp_path)
    assert world.episodes["cancelled"] == 1 and world.episodes["saved"] == 0
    assert world.kept(store) == [] and not list((store.yolo / "labels").glob("pick_*"))
    assert not list((store.crops / "plastic").glob("*.jpg"))


def test_other_item_is_classified_and_dropped_without_an_episode(tmp_path):
    world = World([("READY", "other", (300, 200)), ("READY", "stop", None)])
    store = world.run(tmp_path)
    assert world.drops == 2 and world.episodes["begun"] == 0
    [record] = world.kept(store)
    assert record["kind"] == "other" and record["material"] == "other"


def test_an_episode_without_a_grasp_ends_at_the_timeout_with_a_warning(tmp_path):
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], human="idle")
    store = world.run(tmp_path)
    [record] = world.kept(store)
    assert record["ended"] == "timeout" and record["seconds"] == pytest.approx(20, abs=0.2)
    assert "timeout" in world.status.warning


def test_without_leader_hold_the_episode_starts_on_space(tmp_path):
    recording = {**RECORDING, "start": {**RECORDING["start"], "leader_hold": False}}
    world = World([("READY", "metal", (300, 200)), ("ARMED", "start", None), ("READY", "stop", None)])
    store = world.run(tmp_path, recording)
    assert world.kept(store)[0]["ended"] == "lifted"


def test_emergency_stop_while_recording_discards_the_episode(tmp_path):
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)])
    # the emergency stop comes 0.5 s into the recording
    original = world.log

    def log(event, **data):
        original(event, **data)
        if event == "phase" and data["phase"] == "RECORDING":
            world.estop_at = world.clock.t + 0.5
    world.log = log
    store = world.run(tmp_path)
    assert world.episodes["cancelled"] == 1 and world.episodes["saved"] == 0 and world.kept(store) == []
    assert "Emergency stop" in world.status.warning


def test_changed_box_finds_the_item_and_ignores_noise():
    empty = tray()
    box = changed_box(empty, tray([(300, 200)]), (0, 0, 640, 480), 25)
    assert box == pytest.approx([300, 200, 360, 260], abs=4)
    noisy = empty.copy()
    noisy[100:104, 100:104] = 255  # one blurred cell
    assert changed_box(empty, noisy, (0, 0, 640, 480), 25) is None


def test_item_names_are_safe_gallery_prefixes():
    assert safe_name("Red Bull_can 2") == "red-bull-can-2" and safe_name("  ") == "item"


def test_pick_other_records_a_generic_episode_kept_out_of_the_gallery_classes(tmp_path):
    world = World([("READY", "generic", (300, 200)), ("READY", "stop", None)])
    store = world.run(tmp_path)
    [record] = world.kept(store)
    assert record["material"] == "generic" and record["kind"] == "episode" and record["ended"] == "lifted"
    assert record["session"] == store.session
    assert len(list((store.crops / "generic").glob("*.jpg"))) == 1  # build_gallery reads metal/plastic/other only
    assert list((store.yolo / "labels").glob("pick_*.txt"))[0].read_text().startswith("3 ")
    assert world.drops == 1 and world.status.counts["generic"] == 1


def test_held_out_items_and_a_wrong_class_are_refused(tmp_path):
    from item_registry import Item, Registry

    reg = Registry({"m01": Item("m01", "metal", "hell-classic"),
                    "m-peach": Item("m-peach", "metal", "redbull-peach", "test", names=["redbull-peach"])})
    world = World([("READY", "metal", (300, 200)), ("READY", "plastic", None), ("READY", "stop", None)])
    world.commands.item = "Redbull Peach 2"
    store = PickStore(tmp_path, RECORDING["outputs"], lambda path, rgb: Path(path).write_bytes(b"jpg"))
    world.status = Status()
    session = PickSession(world, world, world.detector, world.embed, world.decide, world, world, store, POSES,
                          CONFIG, RECORDING, Hooks(world.log), world.commands, world.status, clock=world.clock,
                          should_stop=lambda: world.clock.t > 5, registry=reg)
    session.run()
    assert world.episodes["begun"] == 0 and world.kept(store) == []
    assert "held out" in " ".join(str(d) for e, d in world.events if e == "warning")
    world.commands.item = "m01"
    assert "a metal item" in session.refuse("plastic") and session.refuse("metal") is None
    assert session.refuse("other") is None  # anything may go through Other


def test_the_panel_shows_progress_and_the_least_recorded_item(tmp_path):
    from item_registry import Item, Registry

    reg = Registry({"m01": Item("m01", "metal", "hell-classic", brand="Hell"), "m02": Item("m02", "metal", "x")})
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], dino="metal")
    world.commands.item = "m01"
    store = PickStore(tmp_path, RECORDING["outputs"], lambda path, rgb: Path(path).write_bytes(b"jpg"))
    world.status = Status()
    PickSession(world, world, world.detector, world.embed, world.decide, world, world, store, POSES, CONFIG, RECORDING,
                Hooks(world.log), world.commands, world.status, clock=world.clock,
                should_stop=lambda: world.stop, registry=reg).run()
    s = world.status
    assert s.item_counts == {"m01": 1} and s.suggest["metal"].startswith("m02")
    assert s.target_phase == "pilot" and s.targets["pilot"]["metal"] == 23


def test_the_recording_rate_is_published_for_the_panel(tmp_path):
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], dino="metal")
    world.run(tmp_path)
    assert world.status.rec_fps == pytest.approx(30, abs=3)  # the fake clock ticks at 30 fps


class Stiff(World):
    """A leader whose gripper cannot be driven (a 12 V servo on 5 V): it stays where the person left it."""

    def __init__(self, *a, trigger=0, stop_after=None, **k):
        super().__init__(*a, **k)
        self.leader = {**self.leader, GRIPPER: trigger}
        self.stop_after = stop_after

    def command(self, degrees):
        super().command({**degrees, GRIPPER: self.leader[GRIPPER]})

    def read(self):
        if self.stop_after and self.phase == "ARMED" and self.clock.t - self.phase_since > self.stop_after:
            self.stop = True
        return super().read()


def test_the_episode_waits_until_the_person_opens_a_leader_gripper_the_script_cannot_drive(tmp_path):
    world = Stiff([("READY", "metal", (300, 200))], trigger=0, stop_after=4)  # trigger shut, follower open
    world.run(tmp_path)
    assert world.episodes["begun"] == 0  # the push after 1.5 s did not start it
    assert "Open the leader's gripper" in world.status.warning


def test_with_the_trigger_already_open_the_episode_starts_as_usual(tmp_path):
    world = Stiff([("READY", "metal", (300, 200)), ("READY", "stop", None)], trigger=60, dino="metal")
    store = world.run(tmp_path)
    [record] = world.kept(store)
    assert record["ended"] == "lifted" and world.status.warning == ""


def test_the_script_can_still_drive_a_leader_whose_gripper_works(tmp_path):
    recording = {**RECORDING, "start": {**RECORDING["start"], "drive_leader_gripper": True}}
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], dino="metal")
    store = world.run(tmp_path, recording)
    assert world.kept(store)[0]["ended"] == "lifted"

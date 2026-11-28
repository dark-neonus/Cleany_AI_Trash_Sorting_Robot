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


def library(root=None):
    """One training object per button: the session refuses a record without a chosen object."""
    from item_registry import Item, Registry

    items = {i: Item(i, cls, i) for i, cls in (("m01", "metal"), ("p01", "plastic"), ("o01", "other"))}
    return Registry(items, root=root)


CHOICE = {"metal": "m01", "plastic": "p01", "pick_other": "o01", "other": "o01"}


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
        self.registry = library()

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
                    if command in CHOICE and self.commands.item == "":
                        self.commands.item = CHOICE[command]  # the object chosen in the panel
                    self.commands.put(command)

    def paused(self):
        return self.estop_at is not None and self.estop_at <= self.clock.t < self.estop_at + 1

    def run(self, tmp_path, recording=RECORDING):
        store = PickStore(tmp_path, recording["outputs"], lambda path, rgb: Path(path).write_bytes(b"jpg"))
        self.status = Status()
        session = PickSession(self, self, self.detector, self.embed, self.decide, self, self, store, POSES, CONFIG,
                              recording, Hooks(self.log), self.commands, self.status, clock=self.clock,
                              should_stop=lambda: self.stop or self.clock.t > 600, paused=self.paused,
                              registry=self.registry)
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
    assert len(list((store.crops / "metal").glob("m01_*.jpg"))) == 1 and record["item_id"] == "m01"
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


def test_pick_other_records_an_episode_of_class_other(tmp_path):
    world = World([("READY", "pick_other", (300, 200)), ("READY", "stop", None)])
    store = world.run(tmp_path)
    [record] = world.kept(store)
    assert record["material"] == "other" and record["kind"] == "episode" and record["ended"] == "lifted"
    assert record["session"] == store.session
    assert len(list((store.crops / "other").glob("o01_*.jpg"))) == 1
    assert list((store.yolo / "labels").glob("pick_*.txt"))[0].read_text().startswith("2 ")
    assert world.drops == 1 and world.status.counts["other"] == 1 and world.status.counts["saved"] == 0


def test_the_arm_in_view_is_never_taken_for_the_item(tmp_path):
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], dino="metal")
    detect = world.detector
    arm = {"box": [215, 2, 415, 100], "class": "item", "conf": 0.99}  # YOLO sees the arm, with or without an item
    world.detector = lambda frame: [arm, *detect(frame)]
    [record] = world.kept(world.run(tmp_path))
    assert record["target_box"] == pytest.approx([300, 200, 360, 260], abs=4)
    assert record["yolo_boxes"] == [[300, 200, 360, 260]]

    empty = World([("READY", "metal", None), ("READY", "stop", None)])
    empty.detector = lambda frame: [arm]
    assert empty.kept(empty.run(tmp_path / "empty")) == [] and empty.episodes["begun"] == 0


def test_slivers_of_shifted_edges_do_not_stretch_the_box():
    empty, frame = tray(), tray([(300, 200)])
    empty[20:460, 600:608] = 20  # a slot in the tray wall
    frame[20:460, 603:611] = 20  # the same slot, shifted by 3 px since the empty photo
    assert changed_box(empty, frame, (0, 0, 640, 480), 25) == pytest.approx([300, 200, 360, 260], abs=4)


def test_a_clear_item_is_found_by_its_creases_when_the_colour_hardly_changes():
    empty = tray()
    frame = empty.copy()
    for y in range(200, 360, 12):  # creases and highlights of a clear bottle: thin, faint overall
        frame[y:y + 3, 240:340] = 150
    assert changed_box(empty, frame, (0, 0, 640, 480), 90) == pytest.approx([240, 200, 340, 351], abs=20)  # padded a little: no sharp outline


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
    assert "a metal object" in session.refuse("plastic") and session.refuse("metal") is None
    assert session.refuse("other")  # a can is not saved as class other


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
    assert s.target_phase == "pilot" and s.targets["pilot"]["metal"] == 23 and s.targets["pilot"]["other"] == 15


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


def test_the_followers_gripper_opens_by_itself_to_the_hover_opening_then_follows_the_trigger(tmp_path):
    world = Stiff([("READY", "metal", (300, 200))], trigger=10, stop_after=4)
    seen = []
    send = world.send
    world.send = lambda action: (seen.append((world.phase, action[GRIPPER])), send(action))[1]
    world.run(tmp_path)
    opening = RECORDING["start"].get("hover_gripper", 60)
    armed = [g for phase, g in seen if phase == "ARMED"]
    assert armed[0] == opening  # the follower opened to the hover opening on its own
    assert armed[-1] == 10  # then it followed the trigger
    assert max(abs(b - a) for a, b in zip(armed, armed[1:])) <= 4  # a few units a frame


def test_pushing_the_leader_starts_the_episode_wherever_the_trigger_is(tmp_path):
    world = Stiff([("READY", "metal", (300, 200)), ("READY", "stop", None)], trigger=0, dino="metal")
    store = world.run(tmp_path)
    [record] = world.kept(store)
    assert record["ended"] == "lifted" and world.status.warning == ""


def test_the_script_can_still_drive_a_leader_whose_gripper_works(tmp_path):
    recording = {**RECORDING, "start": {**RECORDING["start"], "drive_leader_gripper": True}}
    world = World([("READY", "metal", (300, 200)), ("READY", "stop", None)], dino="metal")
    store = world.run(tmp_path, recording)
    assert world.kept(store)[0]["ended"] == "lifted"


def test_a_record_needs_an_object_chosen_in_the_library(tmp_path):
    world = World([("READY", "metal", (300, 200))])
    world.commands.item = "something typed"
    world.estop_at, world.stop = None, False
    store = PickStore(tmp_path, RECORDING["outputs"], lambda path, rgb: Path(path).write_bytes(b"jpg"))
    world.status = Status()
    PickSession(world, world, world.detector, world.embed, world.decide, world, world, store, POSES, CONFIG,
                RECORDING, Hooks(world.log), world.commands, world.status, clock=world.clock,
                should_stop=lambda: world.clock.t > 5, registry=world.registry).run()
    assert world.episodes["begun"] == 0 and world.kept(store) == []
    assert "Choose the item in the library" in world.status.warning
    optional = {**RECORDING, "items": {**RECORDING["items"], "required": False}}
    session = PickSession(world, world, world.detector, world.embed, world.decide, world, world, store, POSES,
                          CONFIG, optional, Hooks(world.log), world.commands, world.status, clock=world.clock,
                          registry=world.registry)
    assert session.refuse("metal") is None


def test_add_new_object_photographs_the_tray_and_chooses_the_new_object(tmp_path):
    import yaml as _yaml
    from item_registry import Registry

    world = World([("READY", "add_object", (300, 200)), ("READY", "metal", None), ("READY", "stop", None)],
                  dino="metal")
    world.registry = Registry(root=tmp_path / "objects")
    world.commands.new_object = ("metal can", "Hell Cola")
    store = world.run(tmp_path)
    folder = tmp_path / "objects" / "train" / "m-hell-cola"
    assert (folder / "thumb.jpg").exists() and (folder / "photo.jpg").exists() and (folder / "tray.jpg").exists()
    saved = _yaml.safe_load((folder / "item.yaml").read_text())
    assert saved["class"] == "metal" and saved["kind"] == "can" and saved["name"] == "Hell Cola"
    assert saved["recorded"] == 1 and saved["source"]["photo"] == "recorder"
    [record] = world.kept(store)
    assert record["item_id"] == "m-hell-cola" and record["kind"] == "episode"
    assert Registry.load(tmp_path / "objects").items["m-hell-cola"].recorded == 1


def test_add_new_object_with_an_empty_tray_adds_nothing(tmp_path):
    from item_registry import Registry

    world = World([("READY", "add_object", None), ("READY", "stop", None)])
    world.registry = Registry(root=tmp_path / "objects")
    world.run(tmp_path)
    assert not (tmp_path / "objects" / "train").exists() and "nothing on the tray" in world.status.warning


def test_a_discarded_record_leaves_no_library_picture(tmp_path):
    from item_registry import Registry

    world = World([("READY", "add_object", (300, 200)), ("READY", "metal", None), ("READY", "discard", None),
                   ("READY", "stop", None)])
    world.registry = Registry(root=tmp_path / "objects")
    world.commands.new_object = ("metal can", "Cola")
    world.run(tmp_path)
    folder = tmp_path / "objects" / "train" / "m-cola"
    assert (folder / "thumb.jpg").exists() and not (folder / "tray.jpg").exists()

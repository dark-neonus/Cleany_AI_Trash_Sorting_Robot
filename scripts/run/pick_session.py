"""Pick recording session: the states behind scripts/dataset/record_pick.py (docs/pick-dataset.md).

    SETUP      doors open and close (the tray is empty), both arms home, empty-tray photo
    READY      wait for Metal / Plastic / Pick other / Save other; Discard drops the last
               record; the previous record is kept (episode saved) when the next one starts or the
               session stops. The item must be chosen in the object library (objects/train) first;
               a held-out test item or one of another class is refused. Add new object: the
               object on the tray becomes a new library entry (photo, class, name)
    CLASSIFY   settle; the item's box is what differs from the empty tray (YOLO only cross-checks).
               Saves a labelled YOLO frame (class from the button) and a gallery crop
    DROP       Save other: no episode, the doors drop it into the mixed bin, then READY
               (Pick other: an object that is neither metal nor plastic gets a pick episode too;
               both are class `other`)
    HOVER      both arms to the hover pose, gripper open, as the pipeline starts its grasp
    ARMED      the leader holds hover until pushed push_deg (or Space): its torque goes off and
    RECORDING  the follower follows it; every frame goes to the dataset. Ends when the box
               pipeline's grasp check holds (fingers blocked and arm lifted), on End, or timeout
    PLACE      the leader is driven again; transit (above the tray: the item is let go there and
               falls back onto the tray) or its bin, gripper fully open
    HOME       both arms home, then READY

The leader is moved by script (mirroring every follower command) from SETUP to home, and from
HOVER to home again, except during RECORDING; it rests limp at home while READY. The red emergency stop releases the follower (arm_estop.py) and the leader;
an episode being recorded is discarded. Like box_states.py this module only talks to the
hardware through the objects it is given, so tests/test_pick_session.py runs it with fakes.
"""

from __future__ import annotations

import json
import queue
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from box_logic import (
    GRIPPER,
    JOINT_KEYS,
    GraspCheck,
    SettleGate,
    changed_box,
    crop_box,
    group_detections,
    hold_command,
    iou,
    trajectory,
)
from box_states import BoxPipeline, Paused, Stop
from item_registry import TYPES, Registry, RegistryError, read_records, slug

MATERIALS = ("metal", "plastic", "other")
YOLO_CLASSES = {"metal": 0, "plastic": 1, "other": 2}
# READY's buttons: command -> (material, with a pick episode). "other" only saves the picture and drops it
ACTIONS = {"metal": ("metal", True), "plastic": ("plastic", True), "pick_other": ("other", True),
           "other": ("other", False)}


# --- files: YOLO frames, gallery crops, records ------------------------------------------------

def safe_name(text: str) -> str:
    """Item names become file name prefixes: letters, digits and '-' only (no '_': build_gallery
    groups crops by the part before the last '_')."""
    return slug(text)


@dataclass
class Record:
    material: str
    item: str
    stamp: str
    files: list[Path] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    picture: np.ndarray | None = None  # the item's crop: its library picture once a record is kept


class PickStore:
    """Everything a session writes besides the LeRobot dataset."""

    def __init__(self, project_root: Path, outputs: dict, save_image, load_image=None):
        """save_image(path, rgb): writes a JPEG; load_image(path) -> rgb reads one (cv2 in the runner;
        without it the empty-tray photo is not checked against the previous one)."""
        self.yolo = project_root / outputs["yolo_frames"]
        self.crops = project_root / outputs["crops"]
        self.records = project_root / outputs["records"]
        self.save_image, self.load_image = save_image, load_image
        self.session = self._stamp()  # every record of this session carries it (contact sheets)
        for sub in ("images", "labels"):
            (self.yolo / sub).mkdir(parents=True, exist_ok=True)
        (self.yolo / "classes.txt").write_text("\n".join(YOLO_CLASSES) + "\n")
        self.records.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _stamp() -> str:
        return datetime.now().strftime("%Y%m%dT%H%M%S%f")[:-3]

    def _yolo_frame(self, stem: str, frame: np.ndarray, boxes: list[tuple[str, list[float]]], meta: dict) -> list[Path]:
        h, w = 480, 640  # boxes are in 640x480 coordinates whatever the frame size
        image, label = self.yolo / "images" / f"{stem}.jpg", self.yolo / "labels" / f"{stem}.txt"
        self.save_image(image, frame)
        lines = [f"{YOLO_CLASSES[c]} {(b[0] + b[2]) / 2 / w:.6f} {(b[1] + b[3]) / 2 / h:.6f} "
                 f"{(b[2] - b[0]) / w:.6f} {(b[3] - b[1]) / h:.6f}" for c, b in boxes]
        label.write_text("".join(f"{line}\n" for line in lines))
        with (self.yolo / "frames.jsonl").open("a") as f:
            f.write(json.dumps({"image": image.name, **meta}) + "\n")
        return [image, label]

    def empty_tray(self, frame: np.ndarray):
        """A negative YOLO frame (no items), kept at once."""
        stamp = self._stamp()
        self._yolo_frame(f"empty_{stamp}", frame, [], {"material": None, "kind": "empty_tray"})

    def last_empty(self) -> np.ndarray | None:
        """The newest empty-tray photo kept so far (an earlier session's, or a retake)."""
        photos = sorted((self.yolo / "images").glob("empty_*.jpg"))
        return self.load_image(photos[-1]) if photos and self.load_image is not None else None

    def classification(self, material: str, item: str, frame: np.ndarray, label_box, crop, meta: dict) -> Record:
        stamp = self._stamp()
        rec = Record(material, safe_name(item), stamp, data=dict(meta))
        boxes = [(material, label_box)] if label_box is not None else []
        rec.files += self._yolo_frame(f"pick_{stamp}", frame, boxes, {"material": material, "item": rec.item, **meta})
        if crop is not None:
            path = self.crops / material / f"{rec.item}_{stamp}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            self.save_image(path, crop)
            rec.files.append(path)
        return rec

    def commit(self, rec: Record, **extra):
        line = {"time": rec.stamp, "session": self.session, "material": rec.material, "item": rec.item,
                **rec.data, **extra}
        with self.records.open("a") as f:
            f.write(json.dumps(line) + "\n")

    def discard(self, rec: Record):
        for path in rec.files:
            path.unlink(missing_ok=True)
        frames = self.yolo / "frames.jsonl"  # drop its line from the YOLO frame index
        if frames.exists():
            kept = [ln for ln in frames.read_text().splitlines() if f"pick_{rec.stamp}." not in ln]
            frames.write_text("".join(f"{ln}\n" for ln in kept))

    def read(self) -> list[dict]:
        return read_records(self.records)

    def counts(self) -> dict[str, int]:
        """Episodes per material, and under "saved" the pictures saved without one."""
        counts = dict.fromkeys((*MATERIALS, "saved"), 0)
        for record in self.read():
            counts[record["material"] if record.get("kind") == "episode" else "saved"] += 1
        return counts


# --- status shown by the panel -------------------------------------------------------------------

@dataclass
class Status:
    phase: str = "CONNECTING"
    message: str = "Connecting to the arms, cameras and doors"
    warning: str = ""
    material: str | None = None
    counts: dict = field(default_factory=lambda: dict.fromkeys((*MATERIALS, "saved"), 0))
    session: int = 0  # records kept in this session
    targets: dict = field(default_factory=dict)  # phase -> {class: episodes} (docs/collection-plan.md)
    target_phase: str = ""
    item_counts: dict = field(default_factory=dict)  # item id -> kept episodes
    suggest: dict = field(default_factory=dict)  # class -> 'm03 Hell classic (1)', least recorded
    pending: str = ""  # what Discard would drop
    elapsed: float = 0.0
    timeout: float | None = None
    rec_fps: float = 0.0  # frames per second the dataset is really recorded at (RECORDING)
    last: str = ""
    frame: np.ndarray | None = None  # front camera
    wrist: np.ndarray | None = None  # wrist camera
    target_box: list | None = None
    change_box: list | None = None
    yolo_boxes: list = field(default_factory=list)
    library_version: int = 0  # bumped when an object is added to the library: the panel redraws it


class Commands:
    """Button and key presses from the panel, consumed by the session in its own thread."""

    def __init__(self):
        self.queue: queue.Queue[str] = queue.Queue()
        self.item = ""  # id of the library object chosen in the panel
        self.new_object = ("metal can", "")  # Add new object: (type, one of item_registry.TYPES; name)

    def put(self, command: str):
        self.queue.put(command)

    def get(self) -> str | None:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None

    def clear(self):
        while self.get() is not None:
            pass


# --- the session -----------------------------------------------------------------------------------

class PickSession(BoxPipeline):
    """BoxPipeline's moves, perception helpers and emergency-stop handling, plus the leader arm.

    arm: observe() -> obs (degrees + 'front', 'wrist'), send(action), extras() -> register values.
    leader: read() -> degrees, command(degrees), set_torque(on).
    embed(crops) -> (n, d) unit vectors; decide(vector) -> dino_classifier.Decision or None.
    recorder: begin(task, item), add(obs, action, extras), cancel(), save() -> episode index.
    """

    def __init__(self, arm, leader, detector, embed, decide, door, recorder, store: PickStore, poses: dict,
                 config: dict, recording: dict, hooks, commands: Commands, status: Status, clock=None,
                 should_stop=lambda: False, paused=lambda: False, registry: Registry | None = None):
        super().__init__(arm, detector, None, None, door, poses, config, hooks, clock=clock,
                         should_stop=should_stop, paused=paused)
        self.leader, self.embed, self.decide, self.recorder, self.store = leader, embed, decide, recorder, store
        self.rec_cfg, self.commands, self.status = recording, commands, status
        self.mirror = False  # the leader repeats every follower command
        self.material: str | None = None
        self.pick = True  # False: save the picture only, no episode
        self.record: Record | None = None  # classification of the current item
        self.item: dict | None = None  # embedding and box recorded with the episode
        self.pending: tuple[str, Record, dict] | None = None  # last record, kept unless discarded
        self.recording = False
        self.tray_unconfirmed = False  # the empty-tray photo may have an item in it
        self.registry = registry or Registry()
        self.require_item = (recording.get("items") or {}).get("required", True)
        targets = recording.get("targets") or {}
        self.status.targets = {k: v for k, v in targets.items() if isinstance(v, dict)}
        self.status.target_phase = targets.get("phase", "")
        self.status.counts = store.counts()
        self.refresh_items()

    # -- helpers ------------------------------------------------------------------------------------

    def send(self, command: dict):
        super().send(command)
        if self.mirror:
            self.leader.command(self.command)

    def set_phase(self, phase: str, message: str = "", **kw):
        s = self.status
        s.phase, s.message, s.elapsed, s.timeout = phase, message, 0.0, None
        for k, v in kw.items():
            setattr(s, k, v)
        self.log("phase", phase=phase)

    def warn(self, text: str):
        self.status.warning = text
        self.log("warning", text=text)

    def show(self, obs: dict):
        self.status.frame = obs.get("front")
        self.status.wrist = obs.get("wrist")

    def front_frames(self, n=None):
        for obs in super().front_frames(n):
            self.show(obs)
            yield obs

    def align_leader(self):
        """Torque on the leader where it is, then a minimum-jerk move onto the follower's pose, so
        mirroring starts without a jump."""
        self.mirror = False
        self.leader_torque(True)
        start = self.leader.read()
        target = self.joints(self.observe())
        m = self.cfg["motion"]
        for step in trajectory(start, target, m["speed_deg_s"], m["min_move_s"], m["fps"], m.get("ramp_s")):
            began = self.clock.now()
            self.check()
            self.leader.command(step)
            if self.command is not None:
                super().send(self.command)  # keep the follower where it is
            self.tick(began)
        self.mirror = True

    def refresh_items(self):
        """Per-item episode counts and the least-recorded training item per class, for the panel."""
        reg, records = self.registry, self.store.read()
        counts = reg.item_counts(records)
        self.status.item_counts = dict(counts)
        try:
            reg.write_counts(counts)  # N/target in each object's item.yaml
        except OSError as error:
            self.log("library_error", error=str(error))
        self.status.suggest = {}
        for cls in MATERIALS:
            item = reg.suggest(cls, records)
            if item is not None:
                self.status.suggest[cls] = f"{item.id} {item.label()} ({counts[item.id]})"

    def refuse(self, material: str) -> str | None:
        """Why this item may not be recorded as `material`, or None."""
        name = self.commands.item
        held = self.registry.held_out(name) if name else None
        if held is not None:
            return (f"'{name}' is held out for testing ({held.id}: {held.label()}): it must not be recorded. "
                    f"Put it back in the test bag")
        item = self.registry.by_name(name) if name else None
        if item is None and self.require_item:
            return ("Choose the item in the library first (click its picture), or put it on the tray and "
                    "Add new object")
        if item is not None and item.cls != material:
            return f"{item.id} is a {item.cls} object in the library, not {material}: check the item or the button"
        return None

    def add_object(self):
        """The object on the tray becomes a new training object in the library, chosen at once."""
        kind_name, name = self.commands.new_object
        if kind_name not in TYPES:
            self.warn(f"Unknown object type {kind_name!r}")
            return
        cls, kind = TYPES[kind_name]
        t, c = self.cfg["trigger"], self.cfg["classifier"]
        last = list(self.front_frames(3))[-1]["front"]
        box = changed_box(self.trigger.reference, last, self.region, t["item_diff"])
        if box is None:
            self.warn("Add new object: nothing on the tray. Put the object in the box, hands out, then Add again")
            return
        self.status.change_box = box
        crop = crop_box(last, box, c.get("crop_pad", 0.15))
        try:  # the front camera is mounted upside down: the library pictures are turned upright
            item = self.registry.add_object(cls, kind, name, np.ascontiguousarray(np.rot90(crop, 2)),
                                            self.store.save_image, np.ascontiguousarray(np.rot90(last, 2)),
                                            {"photo": "recorder", "session": self.store.session,
                                             "box": [round(float(v), 1) for v in box]},
                                            taken={r.get("item_id") for r in self.store.read()})
        except (RegistryError, OSError) as error:
            self.warn(f"Add new object failed: {error}")
            return
        self.commands.item = item.id
        self.status.library_version += 1
        self.status.warning = ""
        self.status.last = f"added {item.id} ({kind_name}) to the library: it is the chosen item now"
        self.refresh_items()
        self.log("object_added", id=item.id, cls=cls, kind=kind, name=item.name, box=box)

    def leader_torque(self, on: bool):
        """Torque on or off for the leader; servo error flags it reports (overload) are shown, not fatal."""
        seen, noted = len(getattr(self.leader, "warnings", ())), len(getattr(self.leader, "notes", ()))
        self.leader.set_torque(on)
        for text in getattr(self.leader, "warnings", ())[seen:]:
            self.warn(text)
        for text in getattr(self.leader, "notes", ())[noted:]:
            self.log("leader_note", text=text)  # expected (a hand on the trigger): in the log only

    def commit_pending(self):
        if self.pending is None:
            return
        kind, rec, extra = self.pending
        if kind == "episode":
            extra = {**extra, "episode": self.recorder.save()}
        self.store.commit(rec, kind=kind, **extra)
        item = self.registry.items.get(rec.data.get("item_id"))
        if item is not None:
            self.tray_picture(item, rec.picture)
        key = rec.material if kind == "episode" else "saved"
        self.status.counts[key] = self.status.counts.get(key, 0) + 1
        self.status.session += 1
        self.pending, self.status.pending = None, ""
        self.refresh_items()
        self.log("kept", kind=kind, material=rec.material, **extra)

    def discard_pending(self):
        if self.pending is None:
            return
        kind, rec, _ = self.pending
        if kind == "episode":
            self.recorder.cancel()
        self.store.discard(rec)
        self.pending, self.status.pending = None, ""
        self.status.last = f"discarded the last {kind if kind == 'episode' else 'other item'}"
        self.log("discarded", kind=kind, material=rec.material)

    # -- states -------------------------------------------------------------------------------------

    def start(self):
        self.set_phase("SETUP", "Arms home, doors open and close, then a photo of the empty tray")
        self.align_leader()
        self.move_to(self.poses["home"], "yolo")
        if self.door is not None:
            self.door.drop()  # whatever is on the tray falls into the mixed bin
        self.empty_photo(check=True)
        return "READY"

    def empty_photo(self, check: bool):
        """The reference every item is compared with. An item lying there when it is taken is never
        seen, so at start (check) it is compared with the previous empty photo: if they differ, nothing
        is recorded until Retake empty tray says the tray is empty (the light or the setup may have
        changed instead: then Retake too)."""
        frame = list(self.front_frames(5))[-1]["front"]
        self.trigger.set_reference(frame)
        previous = self.store.last_empty() if check else None
        t = self.cfg["trigger"]
        box = None if previous is None else changed_box(previous, frame, self.region, t["item_diff"])
        self.tray_unconfirmed = box is not None
        if self.tray_unconfirmed:
            self.status.change_box = box
            self.warn("The tray does not look empty (green box: what differs from the last empty photo). Take "
                      "everything out, then press Retake empty tray [E]")
        else:
            self.store.empty_tray(frame)
            self.status.warning = ""
        self.log("ready", reference="taken", unconfirmed=box)

    def ready(self):
        self.set_phase("READY", "Put an item on the tray, choose it in the library, then Metal, Plastic, "
                                "Pick other or Save other", target_box=None, yolo_boxes=[],
                       **({} if self.tray_unconfirmed else {"change_box": None}))
        if self.mirror:  # the leader rests at home: no torque while waiting
            self.mirror = False
            self.leader_torque(False)
        for _ in self.front_frames():
            command = self.commands.get()
            if command == "discard":
                self.discard_pending()
            elif command == "empty":
                self.empty_photo(check=False)
                self.status.last = "empty-tray photo taken"
                return "READY"
            elif self.tray_unconfirmed and (command in ACTIONS or command == "add_object"):
                self.warn("First empty the tray and press Retake empty tray [E]")
            elif command == "add_object":
                self.add_object()
                return "READY"  # READY again: its message, and the leader stays limp
            elif command in ACTIONS:
                material, pick = ACTIONS[command]
                reason = self.refuse(material)
                if reason is not None:
                    self.warn(reason)
                    continue
                self.commit_pending()
                self.material, self.pick = material, pick
                self.status.warning, self.status.material = "", material
                return "CLASSIFY"

    def classify_item(self):
        t, c = self.cfg["trigger"], self.cfg["classifier"]
        self.set_phase("CLASSIFY", f"Looking at the {self.material} item: keep hands off the tray")
        gate = SettleGate(self.region, t["pixel_diff"], t["still_fraction"], t["settle_s"])
        started = self.clock.now()
        for obs in self.front_frames():
            if gate.update(self.clock.now(), obs["front"]):
                break
            if self.clock.now() - started > t["settle_timeout_s"]:
                self.warn(f"The tray did not settle in {t['settle_timeout_s']} s: try again")
                return "READY"

        frames, seen = [], []
        for obs in self.front_frames(t["classify_frames"]):
            seen.append(self.detector(obs["front"]))
            frames.append(obs["front"])
        last = frames[-1]
        # The item is what differs from the empty tray. YOLO is only a cross-check: it takes the arm,
        # which hangs into the view, for an item, so its boxes that are not on the change are dropped
        change = changed_box(self.trigger.reference, last, self.region, t["item_diff"])
        if change is None:
            self.status.change_box, self.status.yolo_boxes = None, []
            self.warn("Nothing on the tray (no change from the empty tray). If the item was already there when "
                      "that photo was taken: take it out and press Retake empty tray [E]")
            return "READY"
        yolo = [it.box for it in group_detections(seen) if iou(change, it.box) > 0.3]
        self.status.change_box, self.status.yolo_boxes = change, yolo

        notes = []
        crops = [crop_box(f, change, c.get("crop_pad", 0.15)) for f in frames]
        crops = [cr for cr in crops if cr is not None]
        vectors = self.embed(crops) if crops else []
        embedding = vectors.mean(axis=0) if len(vectors) else None
        decision = self.decide(embedding) if embedding is not None else None
        if decision is not None and decision.cls != self.material:
            notes.append(f"DINO says {decision.cls} ({decision.reason}), you said {self.material}")

        crop = crop_box(last, change, c.get("crop_pad", 0.15))
        meta = {"label_from": "tray_change", "change_box": change, "yolo_boxes": yolo, "target_box": change,
                "dino": None if decision is None else {"cls": decision.cls, "reason": decision.reason,
                                                      "distances": decision.distances}}
        chosen = self.registry.by_name(self.commands.item) if self.commands.item else None
        if chosen is not None:
            meta["item_id"] = chosen.id
        self.record = self.store.classification(self.material, self.commands.item or "item", last, change, crop, meta)
        self.record.picture = crop
        self.item = {"embedding": embedding, "box": np.array(change, dtype=np.float32) / [640, 480, 640, 480]}
        self.status.target_box = change
        if notes:
            self.warn(" · ".join(notes))
        self.log("classified", material=self.material, **meta)
        return "HOVER" if self.pick else "DROP"

    def tray_picture(self, item, crop):
        """With the first kept record of an object, its crop on the tray becomes its library picture
        (tray.jpg: shown instead of the cut-out from the shelf photo)."""
        if crop is None or item.path is None or (item.path / "tray.jpg").exists():
            return
        try:
            self.store.save_image(item.path / "tray.jpg", np.ascontiguousarray(np.rot90(crop, 2)))
            self.status.library_version += 1
        except OSError as error:
            self.log("library_error", error=str(error))

    def drop(self):
        self.set_phase("DROP", "The doors drop the item into the mixed bin")
        if self.door is not None:
            self.door.drop()
        else:
            self.warn("No drop mechanism: take the item out by hand")
        self.pending = ("other", self.record, {})
        self.status.pending = "other item"
        self.status.last = "other item recorded"
        return "READY"

    def hover(self):
        self.set_phase("HOVER", "Both arms to the hover pose: hands off the leader")
        self.align_leader()
        opening = self.rec_cfg["start"].get("hover_gripper", self.cfg["motion"]["gripper_open"])
        self.move_to({**self.poses["hover"], GRIPPER: opening}, self.material)
        return "ARMED"

    def armed(self):
        s = self.rec_cfg["start"]
        hold = s.get("leader_hold", True)
        self.commands.clear()  # presses made before the arms got to hover do not count
        # A leader whose gripper the script cannot drive (a 12 V servo on 5 V): the follower's gripper
        # follows the trigger from here on, a few units per frame, so it is where the trigger is when
        # the episode starts (no snap, and the first recorded frames agree with the action)
        follow = not s.get("drive_leader_gripper", True)
        step = s.get("gripper_follow_step", 4)
        if hold:
            self.set_phase("ARMED", "Grab the leader and push it to start (or Space). Cancel: back home")
        else:
            self.mirror = False
            self.leader_torque(False)
            self.set_phase("ARMED", "Hold the leader, then Space to start. Cancel: back home")
        if follow:
            self.status.message += ". The follower's gripper follows your trigger"
        keys = tuple(k for k in JOINT_KEYS if k != GRIPPER) if follow else JOINT_KEYS  # the trigger is not a push
        started, baseline = self.clock.now(), None
        for _ in self.front_frames():
            command = self.commands.get()
            if command == "cancel":
                self.store.discard(self.record)  # nothing recorded with it: keep the files only with an episode
                return "HOME"
            now = self.leader.read() if (hold or follow) else None
            if follow:
                held = self.command[GRIPPER]
                self.command[GRIPPER] = held + max(-step, min(step, now[GRIPPER] - held))
            if command == "start":
                break
            if hold:
                if self.clock.now() - started < s["settle_s"] or baseline is None:
                    baseline = now
                    continue
                if max(abs(now[k] - baseline[k]) for k in keys) > s["push_deg"]:
                    break
        return "RECORDING"

    def record_episode(self):
        e, g = self.rec_cfg["episode"], self.cfg["grasp"]
        self.mirror = False
        self.leader_torque(False)
        task = self.rec_cfg["dataset"]["tasks"][self.material]
        self.recorder.begin(task, self.item)
        self.recording = True
        self.set_phase("RECORDING", "Lower, grasp, lift: it ends by itself once the item is lifted",
                       timeout=e["timeout_s"])
        check = GraspCheck(self.poses["hover"], g["blocked_deg"], g["lift_joint"], g["lift_deg"], g["hold_s"])
        started, reason, discard, frames = self.clock.now(), None, False, 0
        self.status.rec_fps = 0.0
        while reason is None:
            began = self.clock.now()
            self.check()
            command = self.commands.get()
            action = self.leader.read()
            super().send(action)
            obs = self.observe()
            self.show(obs)
            self.recorder.add(obs, action, self.arm.extras())
            frames += 1
            elapsed = self.clock.now() - started
            self.status.elapsed = elapsed
            if elapsed > 0.5:
                self.status.rec_fps = frames / elapsed
            if command == "end":
                reason = "end"
            elif command == "discard":
                reason, discard = "discarded", True
            elif e.get("end_on_grasp", True) and check.update(self.clock.now(), self.joints(obs), action):
                reason = "lifted"
            elif elapsed >= e["timeout_s"]:
                reason = "timeout"
            self.tick(began)
        self.recording = False
        seconds = round(self.clock.now() - started, 1)
        if discard:
            self.recorder.cancel()
            self.store.discard(self.record)
            self.status.last = f"episode discarded ({seconds} s)"
        else:
            self.pending = ("episode", self.record, {"seconds": seconds, "ended": reason})
            self.status.pending = "episode"
            slow = seconds > e["warn_after_s"]
            self.status.last = f"{self.material} episode: {seconds} s, ended: {reason}"
            if reason == "timeout" or slow:
                self.warn(f"Episode took {seconds} s ({reason}): the pipeline allows "
                          f"{self.cfg['grasp']['timeout_s']} s. Discard it unless it was clean")
        self.log("episode_end", reason=reason, seconds=seconds, discarded=discard)
        return "PLACE"

    def place(self):
        r = self.rec_cfg["release"]
        self.set_phase("PLACE", "Let go of the leader: both arms put the item down")
        self.align_leader()
        holding = hold_command(self.joints(self.observe())[GRIPPER], self.cfg["grasp"]["squeeze_deg"])
        self.move_to({**self.poses["transit"], GRIPPER: holding}, self.material)
        if r["where"] == "bin" and f"{self.material}_bin" in self.poses:  # other: no bin, let go at transit
            self.move_to({**self.poses[f"{self.material}_bin"], GRIPPER: holding}, self.material)
        self.move_to({**self.joints(self.observe()), GRIPPER: r["gripper"]}, self.material)
        self.hold(r["hold_s"], self.material)
        return "HOME"  # the gripper closes while the arm goes home, as in the pipeline

    def home(self):
        self.set_phase("HOME", "Both arms home")
        if not self.mirror:
            self.align_leader()
        self.move_to(self.poses["home"], "yolo")
        return "READY"

    def on_estop(self):
        """Emergency stop: the follower is released by arm_estop; release the leader too."""
        if self.recording:
            self.recording = False
            self.recorder.cancel()
            self.store.discard(self.record)
            self.warn("Emergency stop: the episode being recorded was discarded")
        self.mirror = False
        self.leader_torque(False)
        self.status.phase, self.status.message = "E-STOP", "Arm torque off. Press the red button again to resume"
        self.wait_while_paused()  # until released, then the follower re-engages where it is
        return "HOME"

    # -- loop ---------------------------------------------------------------------------------------

    HANDLERS = {"READY": "ready", "CLASSIFY": "classify_item", "DROP": "drop", "HOVER": "hover", "ARMED": "armed",
                "RECORDING": "record_episode", "PLACE": "place", "HOME": "home"}

    def run(self, max_states: int | None = None):
        """Until Stop. Any stop keeps the last finished record and discards a half-recorded episode."""
        state, count = "START", 0
        try:
            while max_states is None or count < max_states:
                try:
                    state = self.start() if state == "START" else getattr(self, self.HANDLERS[state])()
                except Paused:
                    resumed = self.on_estop()
                    state = "START" if state == "START" else resumed
                count += 1
        except Stop:
            self.log("stopped_by_user")
        finally:
            self.finish()

    def finish(self):
        """Keep the last record, cancel an episode cut short, both arms home, leader limp."""
        self.should_stop = lambda: False
        self.paused = lambda: False
        try:
            if self.recording:
                self.recording = False
                self.recorder.cancel()
                self.store.discard(self.record)
            self.commit_pending()
        except Exception as error:  # noqa: BLE001
            self.log("finish_error", error=f"{error.__class__.__name__}: {error}")
        try:
            self.set_phase("STOPPING", "Both arms home")
            self.align_leader()
            self.move_to(self.poses["home"], "yolo")
        except Exception as error:  # noqa: BLE001
            self.log("shutdown_error", error=f"{error.__class__.__name__}: {error}")
        finally:
            self.mirror = False
            try:
                self.leader_torque(False)
            except Exception as error:  # noqa: BLE001
                self.log("shutdown_error", error=f"{error.__class__.__name__}: {error}")
            self.set_phase("STOPPED", "Session stopped")


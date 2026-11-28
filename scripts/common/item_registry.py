"""Which physical item each pick record is, and whether it is held out for testing
(docs/collection-plan.md, objects/README.md).

  objects/                 the object library, one folder per physical object (or set of identical copies):
    train/<id>/              item.yaml (class, kind, name, target, recorded, ...) and thumb.jpg;
                             the recorder's panel shows these and every record names one of them
    test/<id>/               held out: never recorded, never shown in the panel
  config/item_labels.yaml  record time -> item id, for old records whose typed name was only a hint

Registry.load() also still reads a single items.yaml (the format before the library).

The split is by design: a test item stands for every copy of its design, and no record, YOLO frame,
gallery crop or episode of a test design may be in the training data (check_split).

A record is resolved to an item by its label, else by its typed name when that is an item id or
one of the item's names. Used by the recorder (item picker, counts, refusing test items),
scripts/tools/check_split.py and scripts/tools/build_gallery.py.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CLASSES = ("metal", "plastic", "other")
SPLITS = ("train", "test")
# What an object is within its class: the panel's "Add new object" offers these
TYPES = {"metal can": ("metal", "can"), "plastic bottle": ("plastic", "bottle"), "plastic cap": ("plastic", "cap"),
         "plastic other": ("plastic", "object"), "other": ("other", "object")}
PREFIX = {"metal": "m", "plastic": "p", "other": "o"}  # id prefix; caps get "c"
TARGET = 3  # records per training object (pick episodes; Other items: classify-and-drop records)
ITEM_FILE, THUMB_FILE, PHOTO_FILE, TRAY_FILE = "item.yaml", "thumb.jpg", "photo.jpg", "tray.jpg"


def slug(text: str) -> str:
    """The recorder's file-name form of a typed name (pick_session.safe_name)."""
    import re

    return re.sub(r"[^a-z0-9-]+", "-", str(text).strip().lower()).strip("-") or "item"


@dataclass
class Item:
    id: str
    cls: str
    design: str
    split: str = "train"
    brand: str = ""
    names: list[str] = field(default_factory=list)
    crushed: bool = False
    notes: str = ""
    kind: str = ""  # can, bottle, cap, glass, paper, object
    name: str = ""  # shown in the panel; brand + design when empty
    copies: int = 1  # identical copies this entry stands for (one design, one look)
    target: int = TARGET
    recorded: int = 0  # kept records, as last written by the recorder (records.jsonl is the truth)
    source: dict = field(default_factory=dict)  # where its thumbnail comes from (a photo and box, or the recorder)
    path: Path | None = None  # its library folder

    @property
    def keys(self) -> set[str]:
        """Every name a record may carry for this item, in file-name form."""
        return {slug(self.id), *(slug(n) for n in self.names)}

    @property
    def thumb(self) -> Path | None:
        """Its picture: the recorder's crop on the tray (tray.jpg) once recorded, else thumb.jpg."""
        if self.path is None:
            return None
        return next((self.path / f for f in (TRAY_FILE, THUMB_FILE) if (self.path / f).exists()), None)

    def label(self) -> str:
        if self.name:
            return self.name + (" (crushed)" if self.crushed and "crushed" not in self.name.lower() else "")
        bits = [self.brand, self.design.replace("-", " ")]
        return " ".join(b for b in bits if b) + (" (crushed)" if self.crushed else "")

    def to_yaml(self) -> dict:
        """item.yaml of its library folder (the split is the folder it is in)."""
        data = {"id": self.id, "class": self.cls, "kind": self.kind, "name": self.name, "brand": self.brand,
                "design": self.design, "copies": self.copies, "crushed": self.crushed, "names": self.names,
                "target": self.target, "recorded": self.recorded, "source": self.source, "notes": self.notes}
        return {k: v for k, v in data.items() if v not in ("", [], {}, None) or k in ("recorded",)}

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ITEM_FILE).write_text(yaml.safe_dump(self.to_yaml(), sort_keys=False, allow_unicode=True))


def item_from(raw: dict, where, split: str | None = None, path: Path | None = None) -> Item:
    item = Item(id=str(raw["id"]), cls=raw["class"], design=str(raw.get("design", raw["id"])),
                split=split or raw.get("split", "train"), brand=str(raw.get("brand", "")),
                names=[str(n) for n in raw.get("names") or []], crushed=bool(raw.get("crushed", False)),
                notes=str(raw.get("notes", "")), kind=str(raw.get("kind", "")), name=str(raw.get("name", "")),
                copies=int(raw.get("copies", 1)), target=int(raw.get("target", TARGET)),
                recorded=int(raw.get("recorded", 0)), source=dict(raw.get("source") or {}), path=path)
    if item.cls not in CLASSES:
        raise RegistryError(f"{where}: item {item.id}: class {item.cls!r} is not one of {CLASSES}")
    if item.split not in SPLITS:
        raise RegistryError(f"{where}: item {item.id}: split {item.split!r} is not train or test")
    return item


class RegistryError(ValueError):
    pass


@dataclass
class Registry:
    items: dict[str, Item] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # record time -> item id
    root: Path | None = None  # the library folder (objects/), where new objects are added

    @classmethod
    def load(cls, items_path: Path | None, labels_path: Path | None = None) -> Registry:
        """items_path: the library folder (objects/) or an items.yaml. Missing is an empty registry."""
        reg = cls()
        if items_path is not None and Path(items_path).is_dir():
            reg.root = Path(items_path)
            for split in SPLITS:
                for folder in sorted((reg.root / split).glob(f"*/{ITEM_FILE}")):
                    raw = yaml.safe_load(folder.read_text()) or {}
                    reg._add(item_from(raw, folder, split, folder.parent), folder)
        elif items_path is not None and Path(items_path).exists():
            data = yaml.safe_load(Path(items_path).read_text()) or {}
            for raw in data.get("items") or []:
                reg._add(item_from(raw, items_path), items_path)
        if labels_path is not None and Path(labels_path).exists():
            data = yaml.safe_load(Path(labels_path).read_text()) or {}
            reg.labels = {str(k): str(v) for k, v in data.items()}
        return reg

    def _add(self, item: Item, where) -> None:
        if item.id in self.items:
            raise RegistryError(f"{where}: item id {item.id} twice")
        self.items[item.id] = item

    # -- the library: new objects and their counts ---------------------------------------------------

    def new_id(self, cls: str, kind: str, name: str, taken: set[str] = frozenset()) -> str:
        prefix = "c" if kind == "cap" else PREFIX[cls]
        base = f"{prefix}-{slug(name)}" if name.strip() else prefix
        n, candidate = 1, base if name.strip() else f"{base}-1"
        while candidate in self.items or candidate in taken or (self.root is not None and any(
                (self.root / s / candidate).exists() for s in SPLITS)):
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def add_object(self, cls: str, kind: str, name: str, thumb, save_image, photo=None, source=None,
                   taken: set[str] = frozenset()) -> Item:
        """A new training object in the library: objects/train/<id>/ with item.yaml and thumb.jpg
        (save_image(path, rgb) writes the images). Returns it; it is in self.items at once.
        taken: ids that may not be given out again (those in the records: of deleted objects too)."""
        if self.root is None:
            raise RegistryError("no object library folder (items.registry in config/pick_recording.yaml)")
        if cls not in CLASSES:
            raise RegistryError(f"class {cls!r} is not one of {CLASSES}")
        item_id = self.new_id(cls, kind, name, taken)
        item = Item(id=item_id, cls=cls, design=item_id.split("-", 1)[-1], kind=kind, name=name.strip() or item_id,
                    source=dict(source or {}), path=self.root / "train" / item_id)
        item.path.mkdir(parents=True, exist_ok=True)
        save_image(item.path / THUMB_FILE, thumb)
        if photo is not None:
            save_image(item.path / PHOTO_FILE, photo)
        item.save()
        self.items = {**self.items, item.id: item}  # a new dict: the panel may be reading the old one
        return item

    def write_counts(self, counts: dict) -> list[str]:
        """Write each library object's kept-record count into its item.yaml (`recorded`); returns the ids changed."""
        changed = []
        for item in list(self.items.values()):
            n = int(counts.get(item.id, 0))
            if item.path is not None and item.path.exists() and item.split == "train" and item.recorded != n:
                item.recorded = n
                item.save()
                changed.append(item.id)
        return changed

    # -- lookups ------------------------------------------------------------------------------------

    def by_name(self, name: str) -> Item | None:
        key = slug(name)
        return next((it for it in self.items.values() if key in it.keys), None)

    def resolve(self, time: str, name: str = "") -> Item | None:
        """The item of a record (by its time stamp) or of a crop file: label first, then the name."""
        if str(time) in self.labels:
            return self.items.get(self.labels[str(time)])
        return self.by_name(name) if name else None

    def held_out(self, name: str) -> Item | None:
        """A test item this typed name points at: exact, or containing one of its names
        ('redbull-peach-2' -> Red Bull Peach). Errs on the side of refusing."""
        key = slug(name)
        for item in self.items.values():
            if item.split == "test" and any(k == key or (len(k) >= 4 and k in key) for k in item.keys):
                return item
        return None

    def test_designs(self) -> set[str]:
        return {it.design for it in self.items.values() if it.split == "test"}

    def train_items(self, cls: str | None = None) -> list[Item]:
        return [it for it in self.items.values() if it.split == "train" and (cls is None or it.cls == cls)]

    # -- counts -------------------------------------------------------------------------------------

    def resolve_record(self, r: dict) -> Item | None:
        """The item of a record: its item_id (written since the library), else label / typed name."""
        if r.get("item_id") in self.items and str(r.get("time", "")) not in self.labels:
            return self.items[r["item_id"]]
        return self.resolve(str(r.get("time", "")), r.get("item", ""))

    def item_counts(self, records: list[dict]) -> Counter:
        """Kept records per item id: pick episodes, and for Other objects (glass, paper) their
        classify-and-drop records. A pickable object put through Other does not count."""
        counts = Counter()
        for r in records:
            item = self.resolve_record(r)
            if item is not None and (r.get("kind") == "episode" or (item.cls == "other" and r.get("kind") == "other")):
                counts[item.id] += 1
        return counts

    def suggest(self, cls: str, records: list[dict]) -> Item | None:
        """The training item of this class with the fewest records (ties: registry order)."""
        counts = self.item_counts(records)
        items = self.train_items(cls)
        return min(items, key=lambda it: counts[it.id] / max(it.target, 1)) if items else None


def read_records(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def progress(counts: dict, targets: dict, phase: str) -> str:
    """'metal 12/23 · plastic 5/22 · other 3/15 · saved only 2  (pilot)': episodes against the targets."""
    goal = targets.get(phase, {}) if targets else {}
    parts = [f"{c} {counts.get(c, 0)}" + (f"/{goal[c]}" if c in goal else "") for c in CLASSES]
    parts.append(f"saved only {counts.get('saved', 0)}")
    return " · ".join(parts) + (f"  ({phase})" if goal else "")


# --- the split check ---------------------------------------------------------------------------------

def crop_files(crops: Path):
    """(path, class, item name, time) of every crop: <crops>/<class>/<item>_<time>.jpg."""
    for path in sorted(Path(crops).glob("*/*")):
        if path.suffix.lower() in (".jpg", ".jpeg", ".png") and "_" in path.stem:
            name, time = path.stem.rsplit("_", 1)
            yield path, path.parent.name, name, time


def check_split(reg: Registry, records: list[dict], crops: Path | None = None, yolo: Path | None = None,
                gallery_groups=None) -> tuple[list[str], list[str]]:
    """(problems, notes). A problem is held-out data in the training data, or a broken label;
    notes are things to look at (records not labelled yet)."""
    problems, notes = [], []
    tests = reg.test_designs()
    for item in reg.items.values():
        if item.split == "train" and item.design in tests:
            problems.append(f"item {item.id} is in training but its design {item.design} is held out")
    for time, item_id in reg.labels.items():
        if item_id not in reg.items:
            problems.append(f"label {time} -> {item_id}: no such item in the object library")

    unlabelled = Counter()
    for r in records:
        time, name = str(r.get("time", "")), r.get("item", "")
        item = reg.resolve_record(r)
        where = f"record {time} ({r.get('material')}, " + (
            f"episode {r['episode']})" if "episode" in r else f"{r.get('kind', '?')})")
        if item is None:
            if reg.held_out(name):
                problems.append(f"{where}: typed name {name!r} looks like held-out {reg.held_out(name).id}")
            elif r.get("material") in CLASSES:
                unlabelled[r.get("material")] += 1
            continue
        if item.split == "test":
            problems.append(f"{where} is held-out item {item.id} ({item.label()})")
        elif r.get("material") not in (item.cls, "other"):
            notes.append(f"{where}: labelled {item.id}, a {item.cls} item")
    if unlabelled:
        notes.append("not labelled yet: " + ", ".join(f"{n} {c}" for c, n in sorted(unlabelled.items()))
                     + " (scripts/tools/contact_sheet.py, then config/item_labels.yaml)")

    if crops is not None and Path(crops).exists():
        for path, _, name, time in crop_files(crops):
            item = reg.resolve(time, name) or reg.held_out(name)
            if item is not None and item.split == "test":
                problems.append(f"crop {path} is held-out item {item.id}")
    if yolo is not None and (Path(yolo) / "frames.jsonl").exists():
        for line in (Path(yolo) / "frames.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            frame = json.loads(line)
            time = frame["image"].removeprefix("pick_").rsplit(".", 1)[0]
            item = reg.resolve(time, frame.get("item") or "") or reg.held_out(frame.get("item") or "")
            if item is not None and item.split == "test":
                problems.append(f"YOLO frame {frame['image']} is held-out item {item.id}")
    for group in sorted(set(gallery_groups or [])):
        name = str(group).split("/", 1)[-1]
        item = reg.by_name(name) or reg.held_out(name)
        if item is not None and item.split == "test":
            problems.append(f"gallery group {group} is held-out item {item.id}")
    return problems, notes

"""Which physical item each pick record is, and whether it is held out for testing
(docs/collection-plan.md).

Two files, both written by the agent (Claude) after a session from its contact sheet
(scripts/tools/contact_sheet.py), never filled in by hand during recording:

  config/items.yaml        the items: id, class, brand, design, split (train / test), ...
  config/item_labels.yaml  record time -> item id, for records whose typed name was only a hint

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

CLASSES = ("metal", "plastic", "generic", "other")
PICKED = ("metal", "plastic", "generic")  # classes with a pick episode
SPLITS = ("train", "test")


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

    @property
    def keys(self) -> set[str]:
        """Every name a record may carry for this item, in file-name form."""
        return {slug(self.id), *(slug(n) for n in self.names)}

    def label(self) -> str:
        bits = [self.brand, self.design.replace("-", " ")]
        return " ".join(b for b in bits if b) + (" (crushed)" if self.crushed else "")


class RegistryError(ValueError):
    pass


@dataclass
class Registry:
    items: dict[str, Item] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # record time -> item id

    @classmethod
    def load(cls, items_path: Path | None, labels_path: Path | None = None) -> Registry:
        """Missing files are an empty registry (before the first session is labelled)."""
        reg = cls()
        if items_path is not None and Path(items_path).exists():
            data = yaml.safe_load(Path(items_path).read_text()) or {}
            for raw in data.get("items") or []:
                item = Item(id=str(raw["id"]), cls=raw["class"], design=str(raw.get("design", raw["id"])),
                            split=raw.get("split", "train"), brand=str(raw.get("brand", "")),
                            names=[str(n) for n in raw.get("names") or []], crushed=bool(raw.get("crushed", False)),
                            notes=str(raw.get("notes", "")))
                if item.cls not in CLASSES:
                    raise RegistryError(f"{items_path}: item {item.id}: class {item.cls!r} is not one of {CLASSES}")
                if item.split not in SPLITS:
                    raise RegistryError(f"{items_path}: item {item.id}: split {item.split!r} is not train or test")
                if item.id in reg.items:
                    raise RegistryError(f"{items_path}: item id {item.id} twice")
                reg.items[item.id] = item
        if labels_path is not None and Path(labels_path).exists():
            data = yaml.safe_load(Path(labels_path).read_text()) or {}
            reg.labels = {str(k): str(v) for k, v in data.items()}
        return reg

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

    def item_counts(self, records: list[dict]) -> Counter:
        """Kept pick episodes per item id."""
        counts = Counter()
        for r in records:
            if r.get("kind") == "episode":
                item = self.resolve(r.get("time", ""), r.get("item", ""))
                if item is not None:
                    counts[item.id] += 1
        return counts

    def suggest(self, cls: str, records: list[dict]) -> Item | None:
        """The training item of this class with the fewest episodes (ties: registry order)."""
        counts = self.item_counts(records)
        items = self.train_items(cls)
        return min(items, key=lambda it: counts[it.id]) if items else None


def read_records(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def class_counts(records: list[dict]) -> Counter:
    """Kept records per class (pick episodes for metal / plastic / generic; drops for other)."""
    return Counter(r["material"] for r in records)


def progress(counts: dict, targets: dict, phase: str) -> str:
    """'metal 12/23 · plastic 5/22 · generic 0/15 · other 3  (pilot)'."""
    goal = targets.get(phase, {}) if targets else {}
    parts = [f"{c} {counts.get(c, 0)}" + (f"/{goal[c]}" if c in goal else "") for c in ("metal", "plastic", "generic")]
    parts.append(f"other {counts.get('other', 0)}")
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
            problems.append(f"label {time} -> {item_id}: no such item in items.yaml")

    unlabelled = Counter()
    for r in records:
        time, name = str(r.get("time", "")), r.get("item", "")
        item = reg.resolve(time, name)
        where = f"record {time} ({r.get('material')}, " + (
            f"episode {r['episode']})" if "episode" in r else f"{r.get('kind', '?')})")
        if item is None:
            if reg.held_out(name):
                problems.append(f"{where}: typed name {name!r} looks like held-out {reg.held_out(name).id}")
            elif r.get("material") in PICKED:
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

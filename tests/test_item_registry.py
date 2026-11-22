"""Item registry, the split check, the gallery's skipping of held-out crops and the contact sheet
(scripts/common/item_registry.py, scripts/tools/check_split.py, contact_sheet.py, build_gallery.py)."""

import json
import sys
from pathlib import Path

import pytest
import yaml
from item_registry import Registry, RegistryError, check_split, progress, read_records

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "tools"))

ITEMS = {"items": [
    {"id": "m01", "class": "metal", "brand": "Hell", "design": "hell-classic", "names": ["hell classic"]},
    {"id": "m02", "class": "metal", "brand": "Monster", "design": "monster-green"},
    {"id": "p01", "class": "plastic", "design": "water-green-cap"},
    {"id": "m-redbull-peach", "class": "metal", "design": "redbull-peach", "split": "test",
     "names": ["redbull-peach", "red-bull-peach"]},
]}


def registry(tmp_path, items=ITEMS, labels=None):
    (tmp_path / "items.yaml").write_text(yaml.safe_dump(items, allow_unicode=True))
    (tmp_path / "labels.yaml").write_text(yaml.safe_dump(labels or {}))
    return Registry.load(tmp_path / "items.yaml", tmp_path / "labels.yaml")


def rec(time, material, item, episode=None):
    r = {"time": time, "session": "S1", "material": material, "item": item,
         "kind": "episode" if material != "other" else "other"}
    if episode is not None:
        r["episode"] = episode
    return r


def test_records_resolve_by_label_first_then_by_typed_name(tmp_path):
    reg = registry(tmp_path, labels={"T2": "m02"})
    assert reg.resolve("T1", "hell-classic").id == "m01"  # a name, in file-name form
    assert reg.resolve("T1", "m01").id == "m01"
    assert reg.resolve("T2", "hell-classic").id == "m02"  # the agent's label wins
    assert reg.resolve("T3", "some-can") is None


def test_held_out_names_are_refused_even_inside_longer_names(tmp_path):
    reg = registry(tmp_path)
    for typed in ("Red Bull Peach", "redbull-peach-2", "m-redbull-peach"):
        assert reg.held_out(typed).id == "m-redbull-peach"
    assert reg.held_out("redbull-green") is None and reg.held_out("hell classic") is None


def test_counts_and_the_least_recorded_suggestion(tmp_path):
    reg = registry(tmp_path)
    records = [rec("T1", "metal", "m01", 0), rec("T2", "metal", "m01", 1), rec("T3", "metal", "m02", 2),
               rec("T4", "other", "glass")]
    assert reg.item_counts(records) == {"m01": 2, "m02": 1}
    assert reg.suggest("metal", records).id == "m02"
    assert reg.suggest("plastic", records).id == "p01"
    assert reg.suggest("generic", records) is None  # no test item is ever suggested
    text = progress({"metal": 3, "plastic": 0, "generic": 0, "other": 1},
                    {"pilot": {"metal": 23, "plastic": 22, "generic": 15}}, "pilot")
    assert text == "metal 3/23 · plastic 0/22 · generic 0/15 · other 1  (pilot)"


def test_bad_registries_are_rejected(tmp_path):
    with pytest.raises(RegistryError, match="class"):
        registry(tmp_path, {"items": [{"id": "x", "class": "glass"}]})
    with pytest.raises(RegistryError, match="twice"):
        registry(tmp_path, {"items": [{"id": "x", "class": "metal"}, {"id": "x", "class": "metal"}]})
    assert Registry.load(tmp_path / "missing.yaml").items == {}  # before the first labelling


def test_the_split_check_finds_held_out_data_everywhere(tmp_path):
    reg = registry(tmp_path, labels={"T2": "m-redbull-peach", "T9": "nope"})
    crops, yolo = tmp_path / "crops", tmp_path / "yolo"
    (crops / "metal").mkdir(parents=True)
    for name in ("m01_T1", "some-can_T2", "red-bull-peach_T5"):
        (crops / "metal" / f"{name}.jpg").write_bytes(b"jpg")
    yolo.mkdir()
    (yolo / "frames.jsonl").write_text(json.dumps({"image": "pick_T2.jpg", "item": "some-can"}) + "\n")
    records = [rec("T1", "metal", "m01", 0), rec("T2", "metal", "some-can", 1), rec("T3", "plastic", "bottle", 2)]
    problems, notes = check_split(reg, records, crops, yolo, ["metal/m01", "metal/redbull-peach"])
    text = "\n".join(problems)
    assert "record T2 (metal, episode 1) is held-out item m-redbull-peach" in text
    assert "some-can_T2.jpg is held-out" in text and "red-bull-peach_T5.jpg is held-out" in text
    assert "YOLO frame pick_T2.jpg" in text and "gallery group metal/redbull-peach" in text
    assert "label T9 -> nope" in text
    assert "m01" not in text.replace("m-redbull", "")  # the training can is fine
    assert any("not labelled yet: 1 plastic" in n for n in notes)


def test_a_training_copy_of_a_held_out_design_is_a_leak(tmp_path):
    items = {"items": [*ITEMS["items"], {"id": "m09", "class": "metal", "design": "redbull-peach"}]}
    problems, _ = check_split(registry(tmp_path, items), [])
    assert problems == ["item m09 is in training but its design redbull-peach is held out"]


def test_the_gallery_skips_held_out_crops_and_groups_by_item(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    import build_gallery
    import numpy as np

    reg = registry(tmp_path, labels={"T4": "m02"})
    (tmp_path / "crops" / "metal").mkdir(parents=True)
    for name in ("hell-classic_T1", "red-bull-peach_T2", "can_T4"):
        (tmp_path / "crops" / "metal" / f"{name}.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(build_gallery.cv2, "imread", lambda p: np.zeros((4, 4, 3), np.uint8))
    skipped = []
    groups = [g for _, _, g in build_gallery.folder_crops(tmp_path / "crops", reg, skipped)]
    assert groups == ["metal/m02", "metal/m01"] and [p.name for p in skipped] == ["red-bull-peach_T2.jpg"]


def test_contact_sheet_numbers_the_records_of_a_session(tmp_path):
    pytest.importorskip("PIL")
    import contact_sheet
    from PIL import Image

    reg = registry(tmp_path)
    crops = tmp_path / "crops"
    (crops / "metal").mkdir(parents=True)
    Image.new("RGB", (80, 60), "red").save(crops / "metal" / "m01_T1.jpg")
    records = [rec("T1", "metal", "m01", 0), {**rec("T2", "plastic", "bottle", 1), "session": "S2"}]
    assert [r["time"] for r in contact_sheet.pick_session(records, "latest")] == ["T2"]
    tiles, index = contact_sheet.record_tiles(contact_sheet.pick_session(records, "all"), reg, crops, tmp_path)
    pages = contact_sheet.write(tiles, index, tmp_path / "out", "session_all")
    assert len(pages) == 1 and Image.open(pages[0]).size == (8 * 200, 234)
    saved = yaml.safe_load((tmp_path / "out" / "session_all.yaml").read_text())
    assert saved[0] == {"n": 1, "time": "T1", "material": "metal", "typed": "m01", "episode": 0, "item": "m01"}
    assert saved[1]["item"] is None and tiles[1][0] is None  # no image yet, not labelled yet


def test_the_shipped_registry_loads_and_holds_out_the_agreed_designs():
    reg = Registry.load(ROOT / "config" / "items.yaml", ROOT / "config" / "item_labels.yaml")
    assert {"redbull-peach", "kvas-taras-pryanyi", "hell-peach-lemon", "mojo-lemonade"} <= reg.test_designs()
    assert reg.held_out("Red Bull Peach") and not reg.held_out("hell classic") and not reg.held_out("water green")
    assert read_records(ROOT / "nothing.jsonl") == []

"""Check that no held-out test item leaked into the training data (docs/collection-plan.md).

Usage (through scripts/tools/check_split.sh):
    check_split.sh            # records, gallery crops, YOLO frames and the DINO gallery

Reads config/items.yaml (which items are held out: split test, by design) and
config/item_labels.yaml (which item each record is), and looks at:
  data/pick_records.jsonl   every kept episode and Other item
  data/box_crops/           the gallery crops (build_gallery.sh skips held-out ones anyway)
  data/pick_yolo/           the labelled YOLO frames
  models/dino/gallery.npz   the gallery the pipeline uses

Exit code 1 when held-out data is found, or a label points at no item. Records that are not
labelled yet are listed as a note: make a contact sheet (contact_sheet.sh) and label them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))
from box_logic import load_yaml  # noqa: E402
from item_registry import Registry, RegistryError, check_split, read_records  # noqa: E402


def main():
    recording = load_yaml(PROJECT_ROOT / "config" / "pick_recording.yaml")
    pipeline = load_yaml(PROJECT_ROOT / recording["box_pipeline"])
    outputs, items = recording["outputs"], recording.get("items") or {}
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gallery", type=Path, default=PROJECT_ROOT / pipeline["classifier"]["gallery"])
    args = parser.parse_args()

    try:
        reg = Registry.load(PROJECT_ROOT / items.get("registry", "config/items.yaml"),
                            PROJECT_ROOT / items.get("labels", "config/item_labels.yaml"))
    except RegistryError as error:
        sys.exit(f"Error: {error}")
    if not reg.items:
        sys.exit("Error: config/items.yaml has no items: nothing to check against")
    groups = None
    if args.gallery.exists():
        with np.load(args.gallery, allow_pickle=False) as data:
            groups = data["groups"] if "groups" in data.files else None
    records = read_records(PROJECT_ROOT / outputs["records"])
    problems, notes = check_split(reg, records, PROJECT_ROOT / outputs["crops"], PROJECT_ROOT / outputs["yolo_frames"],
                                  groups)

    held = [it for it in reg.items.values() if it.split == "test"]
    print(f"{len(reg.items)} items ({len(held)} held out: {', '.join(sorted(reg.test_designs()))}), "
          f"{len(records)} records, {len(reg.labels)} labels, gallery: {'checked' if groups is not None else 'none'}")
    for note in notes:
        print(f"  note: {note}")
    if problems:
        print(f"\n{len(problems)} problems (held-out data in training, or broken labels):")
        for problem in problems:
            print(f"  ! {problem}")
        print("\nRemove those records' episodes, frames and crops (or fix the label), then rebuild the gallery.")
        sys.exit(1)
    print("No held-out item in the training data.")


if __name__ == "__main__":
    main()
